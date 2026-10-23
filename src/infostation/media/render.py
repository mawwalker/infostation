"""Build Remotion props from the data pack + script + voice timeline, then render video and stills."""
from __future__ import annotations

import json
import logging
import math
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path

from .. import timefmt
from ..config import VIDEO_DIR, Settings

log = logging.getLogger(__name__)

LABELS = {
    "zh": {"market": "大盘", "sectors": "板块", "movers": "异动", "gainers": "领涨", "losers": "领跌", "vol": "量比",
           "story": "主线", "keypoints": "要点", "sentiment": "散户情绪", "bull": "看多", "bear": "看空",
           "headlines": "相关新闻", "crypto": "加密货币", "prices": "主流币 24h", "feargreed": "恐惧贪婪指数",
           "weekago": "一周前", "dominance": "BTC 市占率", "funding": "永续资金费率 (8h)", "calendar": "前瞻",
           "earnings": "财报日程", "macro": "宏观数据", "nfa": "不构成投资建议", "ah": "盘后财报", "eps": "每股收益",
           "est": "预期", "surprise": "超预期幅度", "move": "盘后涨跌", "noquote": "暂无报价"},
    "en": {"market": "MARKETS", "sectors": "SECTORS", "movers": "MOVERS", "gainers": "Top gainers", "losers": "Top losers",
           "vol": "Vol", "story": "STORY", "keypoints": "Key points", "sentiment": "Retail sentiment", "bull": "bull",
           "bear": "bear", "headlines": "Headlines", "crypto": "CRYPTO", "prices": "Majors 24h", "feargreed": "Fear & Greed",
           "weekago": "Week ago", "dominance": "BTC dominance", "funding": "Perp funding (8h)", "calendar": "AHEAD",
           "earnings": "Earnings", "macro": "Macro", "nfa": "Not financial advice", "ah": "AFTER HOURS", "eps": "EPS",
           "est": "est.", "surprise": "Surprise", "move": "After hours", "noquote": "no quote yet"},
}
CHAPTERS = {
    "zh": {"intro": "开场", "market": "大盘概览", "sectors": "板块轮动", "movers": "异动个股", "story": "主线",
           "crypto": "加密市场", "calendar": "前瞻日历", "outro": "总结",
           "earnings": "盘后财报"},
    "en": {"intro": "Intro", "market": "Market overview", "sectors": "Sectors", "movers": "Top movers", "story": "Story",
           "crypto": "Crypto", "calendar": "What's ahead", "outro": "Wrap-up",
           "earnings": "After-hours earnings"},
}
SESSION = {"recap": {"zh": "盘后复盘", "en": "After-the-Bell Recap"}, "premarket": {"zh": "盘前速览", "en": "Pre-Market Brief"}}
DISCLAIMER = {
    "zh": "本视频由程序采集公开数据并经 AI 辅助生成，仅供信息参考，不构成任何投资建议。投资有风险，决策需独立判断。",
    "en": "This video is produced from public data with AI assistance for informational purposes only and is not investment advice.",
}
CTA = {"zh": "订阅频道 · 每个交易日更新", "en": "Subscribe for a recap every trading day"}
WEEKDAY_ZH = "一二三四五六日"
FNG_ZH = {"Extreme Fear": "极度恐惧", "Fear": "恐惧", "Neutral": "中性", "Greed": "贪婪", "Extreme Greed": "极度贪婪"}
TIMING_ZH = {"BMO": "盘前", "AMC": "盘后", "TBD": "待定"}
IMPACT_ZH = {"High": "高", "Medium": "中", "Low": "低"}
IMPACT_EN = {"Medium": "Med"}


def date_label(d: date, lang: str) -> str:
    if lang == "zh":
        return f"{d.year}年{d.month}月{d.day}日 周{WEEKDAY_ZH[d.weekday()]}"
    return d.strftime("%a, %b %-d, %Y")


def _stats(story: dict, lang: str) -> list[dict]:
    m, o = story["metrics"], story.get("options") or {}
    ins = ((story.get("sec") or {}).get("insider") or {})
    zh = lang == "zh"

    def tone(x):
        return "up" if (x or 0) > 0 else "down" if (x or 0) < 0 else "neutral"

    out = []
    if m.get("change_5d_pct") is not None:
        out.append({"label": "5日涨跌" if zh else "5-day", "value": f"{m['change_5d_pct']:+.2f}%", "tone": tone(m["change_5d_pct"])})
    if m.get("volume_ratio"):
        out.append({"label": "量比 (20日)" if zh else "Vol vs 20d", "value": f"{m['volume_ratio']:.1f}x"})
    if o.get("implied_move_pct"):
        out.append({"label": "期权隐含波动" if zh else "Implied move", "value": f"±{o['implied_move_pct']:.1f}%"})
    if o.get("put_call_volume") is not None:
        out.append({"label": "Put/Call 成交比" if zh else "Put/Call vol", "value": f"{o['put_call_volume']:.2f}"})
    sells, buys = ins.get("open_market_sell_usd") or 0, ins.get("open_market_buy_usd") or 0
    if sells or buys:
        net = buys - sells
        out.append({"label": "内部人净买卖" if zh else "Insider net", "value": f"{'+' if net >= 0 else '−'}${abs(net) / 1e6:.1f}M", "tone": tone(net)})
    if len(out) < 5 and m.get("change_ytd_pct") is not None:
        out.append({"label": "年初至今" if zh else "YTD", "value": f"{m['change_ytd_pct']:+.1f}%", "tone": tone(m["change_ytd_pct"])})
    if len(out) < 5 and m.get("rsi14") is not None:
        out.append({"label": "RSI(14)", "value": f"{m['rsi14']:.0f}"})
    return out[:5]


def build_props(s: Settings, lang: str, view: dict, render_extra: dict, script: dict, timeline: list[dict],
                editor: dict, bg_rel: str | None, bgm_rel: str | None, target: date, session: str) -> dict:
    fps = int(s.get("video.fps", 30))
    tl = {t["id"]: t for t in timeline}
    names = {r["symbol"]: r[f"name_{lang}"] for r in view.get("market", [])}
    stories = {f"story{i + 1}": st for i, st in enumerate(view.get("stories", []))}
    scenes = []
    for sc in script["scenes"]:
        t = tl.get(sc["id"])
        dur = (t["duration"] if t else 3.0) + 0.6
        typ = sc["type"]
        chapter = CHAPTERS[lang][typ]
        if typ == "intro":
            hooks = sc.get("bullets") or [x["hook"][lang] for x in editor["stories"]]
            data = {"theme": editor["market_theme"][lang], "hooks": hooks[:3]}
        elif typ == "market":
            data = {"rows": [{"symbol": r["symbol"], "label": r[f"name_{lang}"], "close": r["close"],
                              "change_pct": r["change_pct"], "unit": r["unit"], "spark": r["spark"]}
                             for r in render_extra["market"]]}
        elif typ == "sectors":
            data = {"rows": [{"symbol": r["symbol"], "label": r[f"name_{lang}"], "change_pct": r["change_pct"],
                              "change_5d_pct": r.get("change_5d_pct")} for r in view["sectors"]]}
        elif typ == "movers":
            data = view["movers"]
        elif typ == "story":
            st = stories[sc["id"]]
            sent = st.get("retail_sentiment")
            stw = st.get("stocktwits") or {}
            chapter = f"{chapter} {sc['id'][5:]} · {st['symbol']}"
            data = {"symbol": st["symbol"], "name": st["name"], "close": st["metrics"]["close"],
                    "change_pct": st["metrics"]["change_pct"], "change_abs": st["metrics"]["change_abs"],
                    "stats": _stats(st, lang), "candles": render_extra["candles"][st["symbol"]],
                    "sentiment": {"score": sent["score_0_100"], "bull": sent["bull_point"][lang], "bear": sent["bear_point"][lang],
                                  "bullish": stw.get("bullish", 0), "bearish": stw.get("bearish", 0)} if sent else None,
                    "headlines": [{"title": h["title"], "source": h["source"]} for h in st.get("headlines", [])[:3]]}
        elif typ == "crypto":
            c = view.get("crypto") or {}
            g = c.get("global") or {}
            data = {"assets": c.get("assets", []),
                    "funding": [{"symbol": k, "rate_pct": v} for k, v in (c.get("funding") or {}).items()],
                    "fearGreed": ({**c["fear_greed"], "label": FNG_ZH.get(c["fear_greed"]["label"], c["fear_greed"]["label"])}
                                  if lang == "zh" and c.get("fear_greed") else c.get("fear_greed")),
                    "dominance": g.get("btc_dominance"),
                    "totalMcapT": round(g["total_mcap_usd"] / 1e12, 2) if g.get("total_mcap_usd") else None,
                    "btcHistory": [{"date": k["date"], "close": k["close"]} for k in render_extra.get("btc_history", [])]}
        elif typ == "earnings":
            data = earnings_data(view.get("after_hours", []), "after_hours", lang)
        elif typ == "calendar":
            data = calendar_data(s, view.get("calendar") or {}, lang)
        else:
            data = {"theme": editor["market_theme"][lang], "disclaimer": DISCLAIMER[lang], "cta": CTA[lang]}
        scenes.append({"id": sc["id"], "type": typ, "title": sc["title"],
                       "bullets": [] if typ == "intro" else sc.get("bullets", [])[:3],
                       "chapter": chapter, "audio": f"audio/{t['audio']}" if t else None,
                       "durationInFrames": int(math.ceil(dur * fps)), "captions": t["captions"] if t else [],
                       "data": data})
    tape = [{"label": names.get(r["symbol"], r["symbol"]), "change_pct": r["change_pct"]} for r in view.get("market", [])]
    tape += [{"label": st["symbol"], "change_pct": st["metrics"]["change_pct"]} for st in view.get("stories", [])]
    return {
        "lang": lang, "fps": fps, "width": int(s.get("video.width", 1920)), "height": int(s.get("video.height", 1080)),
        "brand": {"name": s.get(f"brand.name_{lang}"), "handle": s.get("brand.handle")},
        "dateLabel": date_label(target, lang), "sessionLabel": SESSION[session][lang],
        "colors": s.get(f"video.up_down.{lang}"), "labels": LABELS[lang], "bgImage": bg_rel,
        "bgm": bgm_rel, "bgmVolume": float(s.get("video.bgm_volume", 0.07)), "tape": tape, "scenes": scenes,
    }


def eps_basis_label(code: str | None, lang: str) -> str | None:
    """Card label for Yahoo's EPS methodology. Empty when the feed did not say."""
    if code == "GAAP":
        return "GAAP"
    if code == "adjusted":
        return "调整后" if lang == "zh" else "adjusted"
    return None


def earnings_data(rows: list[dict], side: str, lang: str) -> dict:
    """Earnings table for the video / cards. side = after_hours | premarket (which extended-hours move to show)."""
    return {"moveLabel": LABELS[lang]["move"] if side == "after_hours" else ("盘前涨跌" if lang == "zh" else "Pre-market"),
            "rows": [{"symbol": r["symbol"], "name": r["name"], "eps": r.get("eps_actual"), "eps_est": r.get("eps_estimate"),
                      "eps_basis": eps_basis_label(r.get("eps_basis"), lang),
                      "surprise_pct": r.get("eps_surprise_pct"), "move_pct": r.get(f"{side}_change_pct")} for r in rows[:6]]}


def _split_clock(text: str) -> tuple[str, str | None]:
    """`美东 16:05（洛杉矶 …）` / `4:05 p.m. ET (1:05 p.m. PT)` → main clock plus the other zones."""
    for open_, close in (("（", "）"), ("(", ")")):
        if open_ in text and text.endswith(close):
            main, _, rest = text.partition(open_)
            return main.strip(), rest[:-len(close)].strip() or None
    return text, None


def calendar_data(s: Settings, cal: dict, lang: str) -> dict:
    zh = lang == "zh"
    zones = timefmt.zones_for(s, lang)
    macro = []
    for e in cal.get("macro", []):
        main, sub = timefmt.pair(datetime.fromisoformat(e["datetime_et"]), lang, zones)
        macro.append({"date": e["date"], "time": main, "timeSub": sub, "event": e["event"],
                      "impact": (IMPACT_ZH if zh else IMPACT_EN).get(e["impact"], e["impact"])})
    earnings = []
    for e in cal.get("earnings", []):
        label = TIMING_ZH.get(e["time"], e["time"]) if zh else e["time"]
        main, sub = _split_clock(label)
        row = {"date": e["date"], "symbol": e["symbol"], "name": e["name"], "time": main}
        if sub:
            row["timeSub"] = sub
        earnings.append(row)
    return {"earnings": earnings, "macro": macro}


def thumbnail_props(lang: str, script: dict, props: dict, view: dict) -> dict:
    return {"lang": lang, "text": script["thumbnail_text"], "subtext": script["thumbnail_subtext"],
            "brand": props["brand"]["name"], "dateLabel": props["dateLabel"], "colors": props["colors"],
            "bgImage": props["bgImage"],
            "badges": [{"label": st["symbol"], "change_pct": st["metrics"]["change_pct"]} for st in view.get("stories", [])[:3]],
            "chart": next((sc["data"]["candles"] and [c["close"] for c in sc["data"]["candles"]]
                           for sc in props["scenes"] if sc["type"] == "story"), [])}


def card_ids(view: dict) -> list[str]:
    return (["market", "sectors", "movers"] + [f"story{i + 1}" for i in range(len(view.get("stories", [])))]
            + (["afterhours"] if view.get("after_hours") else []) + ["crypto", "calendar"])


def run_remotion(jobs: list[dict], public_dir: Path, concurrency: int, job_path: Path) -> None:
    if not (VIDEO_DIR / "node_modules").exists():
        subprocess.run(["npm", "ci"], cwd=VIDEO_DIR, check=True)
    job_path.write_text(json.dumps({"publicDir": str(public_dir), "concurrency": concurrency, "jobs": jobs},
                                   ensure_ascii=False))
    proc = subprocess.run(["node", "render.mjs", str(job_path)], cwd=VIDEO_DIR, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for line in proc.stdout.splitlines():
        if line.startswith("[render]"):
            log.info(line)
    if proc.returncode != 0:
        tail = "\n".join(proc.stdout.splitlines()[-40:])
        raise RuntimeError(f"Remotion render failed:\n{tail}")


def loudnorm(src: Path, dst: Path) -> None:
    """Normalize to YouTube's -14 LUFS without re-encoding video."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-c:v", "copy",
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(dst)], check=True)


def pick_bgm(music_dir: Path, seed: str) -> Path | None:
    tracks = sorted([*music_dir.glob("*.mp3"), *music_dir.glob("*.m4a"), *music_dir.glob("*.wav")])
    if not tracks:
        return None
    return tracks[sum(map(ord, seed)) % len(tracks)]


def copy_into(src: Path, public_dir: Path, rel: str) -> str:
    dst = public_dir / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return rel
