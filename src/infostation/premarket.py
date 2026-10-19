"""Pre-market brief: a short X thread + image cards before the US open. No voice, no video.

Steps: collect → write → render (cards only) → package. Runs in the same runs/<date>_premarket/ layout as the recap.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, time, timezone

import pandas as pd

from . import store, timefmt
from .collectors import crypto, events, news, prices
from .http import SourceError
from .market_calendar import ET
from .media import render
from .pipeline import Run, pretty_name, with_times
from .publish import package
from .writing.writer import Writer

log = logging.getLogger(__name__)

TITLES = {
    "zh": {"board": "期货与海外市场", "earnings": "隔夜财报", "movers": "盘前异动", "calendar": "今日日程"},
    "en": {"board": "Futures & overseas", "earnings": "Overnight earnings", "movers": "Pre-market movers",
           "calendar": "Today's schedule"},
}
LABELS = {
    "zh": {"market": "盘前看板", "ah": "隔夜财报", "movers": "盘前异动", "gainers": "盘前领涨", "losers": "盘前领跌",
           "calendar": "今日看点", "earnings": "今日财报"},
    "en": {"market": "PRE-MARKET", "ah": "OVERNIGHT EARNINGS", "movers": "PRE-MARKET", "gainers": "Pre-market gainers",
           "losers": "Pre-market losers", "calendar": "TODAY", "earnings": "Reporting today"},
}
AS_OF = {"zh": "数据截至 ", "en": "Data as of "}


class PremarketRun(Run):
    STEPS = ["collect", "write", "render", "package"]

    def step_collect(self) -> None:
        s, http, d, prev = self.s, self.http, self.plan.target_date, self.plan.prev_date
        watch = set(s.get("universe.watchlist"))
        big = float(s.get("calendar.earnings_min_market_cap", 2e10))
        now = datetime.now(ET)
        t_pre = datetime.combine(d, time(4, 0), ET).timestamp()            # pre-market session opens 4:00 ET
        since = datetime.combine(prev, time(16, 0), ET).astimezone(timezone.utc)

        board_cfg = s.get("premarket.board")
        live = prices.live_quotes([b["symbol"] for b in board_cfg])
        try:
            hist = prices.fetch_daily([b["symbol"] for b in board_cfg], http, period="3mo")
        except SourceError as e:
            log.warning("board history unavailable: %s", e)
            hist = pd.DataFrame(columns=["symbol", "date", "close"])
        board, sparks = [], {}
        for b in board_cfg:
            q = live.get(b["symbol"])
            if not q:
                continue
            g = hist[(hist["symbol"] == b["symbol"]) & (hist["date"] < d)].sort_values("date")
            sparks[b["symbol"]] = [round(float(x), 4) for x in g["close"].iloc[-29:]] + [round(q["last"], 4)]
            board.append({"symbol": b["symbol"], "name_zh": b["name_zh"], "name_en": b["name_en"],
                          "last": round(q["last"], 2), "change_pct": q["change_pct"], "unit": b.get("unit", "price")})
        self.health("premarket_board", len(board) >= 0.7 * len(board_cfg), f"{len(board)}/{len(board_cfg)}")

        reps = events.reports(http, [prev, d], watch, big)
        def out_already(r: dict) -> bool:          # results published (EPS in) or the scheduled time has passed
            return r["eps_actual"] is not None or bool(r["report_time_et"] and datetime.fromisoformat(r["report_time_et"]) <= now)

        overnight = [r for r in reps if ((r["date"] == prev.isoformat() and r["timing"] == "AMC")
                                         or (r["date"] == d.isoformat() and r["timing"] == "BMO")) and out_already(r)]
        tonight = [r for r in reps if r["date"] == d.isoformat() and r not in overnight and r["timing"] != "DURING"]
        self.health("earnings", bool(reps), f"{len(overnight)} reported overnight, {len(tonight)} still to report today")

        last = store.query("SELECT run_id, stories FROM runs WHERE session = 'recap' AND status = 'done' "
                           "AND target_date < ? ORDER BY target_date DESC LIMIT 1", [d.isoformat()])
        recent = set((last["stories"].iloc[0] or "").split(",")) - {""} if len(last) else set()
        quotes = prices.extended_quotes(sorted(watch | recent | {r["symbol"] for r in overnight}))
        self.health("premarket_quotes", bool(quotes), f"{len(quotes)} symbols")

        def pre(sym: str) -> dict | None:
            q = quotes.get(sym) or {}
            return q if q.get("pre_price") and (q.get("pre_time") or 0) >= t_pre else None

        min_chg = float(s.get("premarket.movers_min_change_pct", 1.5))
        min_cap = float(s.get("premarket.movers_min_market_cap", 1e10))
        n = int(s.get("premarket.max_movers", 5))
        reported = {r["symbol"] for r in overnight}
        movers = []
        for sym in quotes:
            q = pre(sym)
            if not q or abs(q["pre_change_pct"]) < min_chg or sym in reported:
                continue
            if sym not in watch and (q.get("market_cap") or 0) < min_cap:
                continue
            movers.append({"symbol": sym, "name": pretty_name(q["name"]), "change_pct": q["pre_change_pct"],
                           "close": q["pre_price"], "prev_close": q["regular_price"], "volume_ratio": None})
        gainers = sorted((m for m in movers if m["change_pct"] > 0), key=lambda m: -m["change_pct"])[:n]
        losers = sorted((m for m in movers if m["change_pct"] < 0), key=lambda m: m["change_pct"])[:n]

        earn_rows = []
        for r in overnight[:6]:
            q = pre(r["symbol"])
            earn_rows.append({"symbol": r["symbol"], "name": pretty_name(r["name"]), "timing": r["timing"],
                              "report_date": r["date"], "fiscal_quarter": r.get("fiscal_quarter"),
                              "eps_actual": r["eps_actual"], "eps_estimate": r["eps_estimate"],
                              "eps_surprise_pct": r["eps_surprise_pct"], "market_cap_billion": round(r["market_cap"] / 1e9),
                              "previous_close": q["regular_price"] if q else None,
                              "premarket_price": q["pre_price"] if q else None,
                              "premarket_change_pct": q["pre_change_pct"] if q else None})

        # Headlines for whatever the thread will talk about
        focus = [(e["symbol"], e["name"]) for e in earn_rows[:4]] + \
                [(m["symbol"], m["name"]) for m in sorted(gainers + losers, key=lambda m: -abs(m["change_pct"]))[:6]]
        heads = {}
        for sym, name in focus:
            heads[sym] = [{"title": h["title"], "source": h["source"]}
                          for h in news.ticker_news(http, sym, name, 3, since)]
        for row in earn_rows + gainers + losers:
            row["headlines"] = heads.get(row["symbol"], [])
        self.health("ticker_news", any(heads.values()) or not focus, f"{sum(map(len, heads.values()))} headlines")
        mnews = news.market_news(http, s.get("news.market_feeds", []), since)
        self.health("market_news", bool(mnews), f"{len(mnews)} headlines")

        cr = crypto.collect(http, s.get("crypto.symbols"), s.get("crypto.funding_symbols"), d)
        self.health("crypto", bool(cr["assets"]), f"{len(cr['assets'])} assets")
        macro = events.macro(http, d, d, s.get("calendar.macro_impact", ["High"]))
        self.health("macro_calendar", True, f"{len(macro)} events today")

        prev_theme = None
        if len(last):
            ed = self.dir.parent / last["run_id"].iloc[0] / "editor.json"
            if ed.exists():
                prev_theme = json.loads(ed.read_text(encoding="utf-8")).get("market_theme")

        self.save("brief.json", {
            "session": "premarket", "date": d.isoformat(), "prev_session": prev.isoformat(),
            "as_of": {lang: timefmt.multi(now, lang, timefmt.zones_for(s, lang)) for lang in ("zh", "en")},
            "board": board,
            "earnings_overnight": earn_rows,
            "premarket_movers": {"gainers": gainers, "losers": losers},
            "earnings_tonight": [{"symbol": r["symbol"], "name": pretty_name(r["name"]), "timing": r["timing"],
                                  "eps_estimate": r["eps_estimate"], "market_cap_billion": round(r["market_cap"] / 1e9)}
                                 for r in tonight[:8]],
            "macro_today": with_times(s, macro),
            "crypto": {"assets": cr["assets"], "fear_greed": cr["fear_greed"], "global": cr["global"]},
            "market_headlines": [{"title": h["title"], "source": h["source"]} for h in mnews[:20]],
            "previous_recap_theme": prev_theme,
        })
        self.save("render_extra.json", {"sparks": sparks})

    # ---------- write ----------
    def card_ids(self, brief: dict) -> list[str]:
        mv = brief["premarket_movers"]
        return (["board"] + (["earnings"] if brief["earnings_overnight"] else [])
                + (["movers"] if mv["gainers"] or mv["losers"] else [])
                + (["calendar"] if brief["macro_today"] or brief["earnings_tonight"] else []))

    def step_write(self) -> None:
        brief = self.load("brief.json")
        out = Writer(self.s, self.agy).premarket_threads(brief, self.card_ids(brief))
        self.health("llm_threads", out.pop("_source") == "llm", "")
        self.save("thread_check.json", out.pop("_factcheck"))
        self.save("threads.json", out)

    # ---------- render (cards only) ----------
    def props(self, lang: str, brief: dict, sparks: dict) -> dict:
        s, d = self.s, self.plan.target_date
        T = TITLES[lang]

        def scene(sid: str, typ: str, data: dict) -> dict:
            return {"id": sid, "type": typ, "title": T[sid], "bullets": [], "chapter": T[sid], "audio": None,
                    "durationInFrames": 1, "captions": [], "data": data}

        scenes = [scene("board", "market", {"rows": [
            {"symbol": b["symbol"], "label": b[f"name_{lang}"], "close": b["last"], "change_pct": b["change_pct"],
             "unit": b["unit"], "spark": sparks.get(b["symbol"], [])} for b in brief["board"]]})]
        if brief["earnings_overnight"]:
            scenes.append(scene("earnings", "earnings", render.earnings_data(brief["earnings_overnight"], "premarket", lang)))
        mv = brief["premarket_movers"]
        if mv["gainers"] or mv["losers"]:
            scenes.append(scene("movers", "movers", {"gainers": mv["gainers"], "losers": mv["losers"]}))
        if brief["macro_today"] or brief["earnings_tonight"]:
            cal = {"macro": brief["macro_today"],
                   "earnings": [{"date": d.isoformat(), "symbol": e["symbol"], "name": e["name"], "time": e["timing"]}
                                for e in brief["earnings_tonight"]]}
            scenes.append(scene("calendar", "calendar", render.calendar_data(s, cal, lang)))
        return {
            "lang": lang, "fps": 30, "width": 1920, "height": 1080,
            "brand": {"name": s.get(f"brand.name_{lang}"), "handle": s.get("brand.handle")},
            "dateLabel": render.date_label(d, lang), "sessionLabel": render.SESSION["premarket"][lang],
            "colors": s.get(f"video.up_down.{lang}"), "labels": render.LABELS[lang] | LABELS[lang],
            "bgImage": None, "bgm": None, "bgmVolume": 0, "tape": [], "scenes": scenes,
            "footnote": AS_OF[lang] + brief["as_of"][lang],
        }

    def step_render(self) -> None:
        brief, extra = self.load("brief.json"), self.load("render_extra.json")
        rdir = self.dir / "render"
        jobs = []
        for lang in self.langs:
            props = self.props(lang, brief, extra["sparks"])
            self.save(f"props_{lang}.json", props)
            for sc in props["scenes"]:
                jobs.append({"kind": "still", "composition": "Card", "props": {"briefing": props, "sceneId": sc["id"]},
                             "out": str(rdir / f"cards_{lang}" / f"{sc['id']}.png")})
        self.public.mkdir(parents=True, exist_ok=True)
        render.run_remotion(jobs, self.public, int(self.s.get("video.concurrency", 8)), self.dir / "render_job.json")

    # ---------- package ----------
    def step_package(self) -> None:
        brief, threads, check = self.load("brief.json"), self.load("threads.json"), self.load("thread_check.json")
        rdir = self.dir / "render"
        for lang in self.langs:
            cards = {cid: rdir / f"cards_{lang}" / f"{cid}.png" for cid in self.card_ids(brief)}
            package.thread_only(self.dir, lang, threads.get(lang, []), cards)
        package.premarket_review(self.dir, brief, threads, check, self.state["health"])
        self.state["finished"] = datetime.now().isoformat(timespec="seconds")
        store.record_run(self.plan.run_id, self.plan.session, self.plan.target_date.isoformat(), "done", [],
                         self.state["started"], self.state["finished"],
                         {k: v["ok"] for k, v in self.state["health"].items()})


def run_class(session: str) -> type[Run]:
    return PremarketRun if session == "premarket" else Run
