"""Deterministic fallbacks used when the LLM is unavailable. Plain, but every number comes straight from data."""
from __future__ import annotations


def _pct(x: float | None, lang: str) -> str:
    if x is None:
        return "—"
    if lang == "zh":
        return f"{'上涨' if x >= 0 else '下跌'}{abs(x):.2f}%"
    return f"{'up' if x >= 0 else 'down'} {abs(x):.2f}%"


def editor_fallback(view: dict, n: int) -> dict:
    cands = view.get("candidates", [])
    sentiment = []
    for c in cands:
        st = c.get("stocktwits") or {}
        b, s = st.get("bullish", 0), st.get("bearish", 0)
        score = int(round(50 + 50 * (b - s) / (b + s))) if (b + s) else 50
        sentiment.append({"symbol": c["symbol"], "score": score,
                          "bull_point": {"zh": "数据不足", "en": "insufficient data"},
                          "bear_point": {"zh": "数据不足", "en": "insufficient data"}})
    stories = [{"symbol": c["symbol"], "angle": "; ".join(c.get("reasons", [])) or "notable move",
                "evidence": c.get("reasons", []),
                "hook": {"zh": f"{c['name']} {_pct(c['metrics']['change_pct'], 'zh')}",
                         "en": f"{c['name']} {_pct(c['metrics']['change_pct'], 'en')}"}}
               for c in cands[:n]]
    return {"market_theme": {"zh": "今日市场概览", "en": "Today's market at a glance"},
            "sentiment": sentiment, "stories": stories, "source": "template"}


def script_fallback(lang: str, session: str, view: dict, editor: dict, scenes: list[dict], brand: str) -> dict:
    zh = lang == "zh"
    mk = {m["symbol"]: m for m in view.get("market", [])}
    out_scenes = []
    stories = {f"story{i + 1}": s for i, s in enumerate(view.get("stories", []))}
    for sc in scenes:
        t = sc["type"]
        if t == "intro":
            title = view["date"]
            text = (f"欢迎收看{brand}，今天是{view['date']}。" if zh else f"Welcome to {brand}. It's {view['date']}.") + \
                   (editor["market_theme"][lang] if editor.get("market_theme") else "")
        elif t == "market":
            title = "大盘表现" if zh else "Market overview"
            parts = []
            for sym in ("SPY", "QQQ", "DIA", "IWM"):
                m = mk.get(sym)
                if m:
                    parts.append(f"{m['name_zh' if zh else 'name_en']}{_pct(m['change_pct'], lang)}" if zh
                                 else f"the {m['name_en']} {_pct(m['change_pct'], lang)}")
            text = ("，".join(parts) + "。") if zh else ("; ".join(parts).capitalize() + ".")
        elif t == "sectors":
            secs = sorted(view.get("sectors", []), key=lambda s: s["change_pct"], reverse=True)
            title = "板块轮动" if zh else "Sector rotation"
            if secs:
                a, b = secs[0], secs[-1]
                text = (f"板块方面，{a['name_zh']}领涨，{_pct(a['change_pct'], lang)}；{b['name_zh']}表现最弱，{_pct(b['change_pct'], lang)}。"
                        if zh else f"{a['name_en']} led, {_pct(a['change_pct'], lang)}, while {b['name_en']} lagged, {_pct(b['change_pct'], lang)}.")
            else:
                text = ""
        elif t == "movers":
            g = view.get("movers", {}).get("gainers", [])[:3]
            title = "异动个股" if zh else "Top movers"
            text = ("涨幅居前的有：" + "，".join(f"{x['name']}{_pct(x['change_pct'], lang)}" for x in g) + "。") if zh else \
                   ("Top gainers: " + ", ".join(f"{x['name']} {_pct(x['change_pct'], lang)}" for x in g) + ".")
        elif t == "story":
            s = stories.get(sc["id"], {})
            m = s.get("metrics", {})
            title = s.get("name", s.get("symbol", ""))
            text = (f"{title}收于{m.get('close')}美元，{_pct(m.get('change_pct'), lang)}。" if zh else
                    f"{title} closed at {m.get('close')} dollars, {_pct(m.get('change_pct'), lang)}.")
            if s.get("headlines"):
                h = s["headlines"][0]
                text += (f"据{h['source']}报道：{h['title']}。" if zh else f" {h['source']} reports: {h['title']}.")
        elif t == "crypto":
            a = {x["symbol"]: x for x in view.get("crypto", {}).get("assets", [])}
            btc = a.get("BTC")
            title = "加密市场" if zh else "Crypto"
            text = (f"比特币报{btc['price']:.0f}美元，24小时{_pct(btc['change_pct'], lang)}。" if zh else
                    f"Bitcoin trades at {btc['price']:.0f} dollars, {_pct(btc['change_pct'], lang)} over 24 hours.") if btc else ""
        elif t == "calendar":
            title = "前瞻" if zh else "What's ahead"
            ev = view.get("calendar", {}).get("earnings", [])[:4]
            text = ("接下来值得关注的财报：" + "，".join(e["name"] for e in ev) + "。") if zh else \
                   ("Earnings to watch: " + ", ".join(e["name"] for e in ev) + ".")
        else:
            title = "感谢收看" if zh else "Thanks for watching"
            text = "以上内容不构成投资建议，我们下期见。" if zh else "This is not financial advice. See you next time."
        out_scenes.append({"id": sc["id"], "type": t, "title": str(title), "bullets": [], "narration": text})
    return {"video_title": f"{brand} {view['date']}", "thumbnail_text": view["date"], "thumbnail_subtext": brand,
            "description": editor["market_theme"][lang], "tags": ["stocks", "market", "crypto"], "scenes": out_scenes}


def thread_fallback(scripts: dict[str, dict], cards: list[str]) -> dict[str, list[dict]]:
    out = {}
    for lang, sc in scripts.items():
        posts = []
        for s in sc["scenes"]:
            if s["narration"]:
                text = s["narration"][:120] if lang == "zh" else s["narration"][:250]
                posts.append({"text": text, "card": None})
        out[lang] = posts[:7]
    return out
