"""End-to-end pipeline. Each step reads/writes files in runs/<run_id>/ so any step can be re-run alone."""
from __future__ import annotations

import json
import logging
import re
import shutil
import time
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from . import store, timefmt
from .analysis import datapack, metrics as M, screener
from .collectors import crypto, events, news, options, prices, sec, social, x as xsrc
from .config import ASSETS_DIR, RUNS_DIR, Settings
from .http import Http, SourceError
from .llm import make_client, resolve_provider
from .llm.handoff import HandoffInvalid, HandoffPending
from .market_calendar import ET, SessionPlan, upcoming_sessions
from .media import comfy, render, tts
from .publish import package
from .writing import factcheck
from .writing.writer import Writer, scene_plan

log = logging.getLogger(__name__)

STEPS = ["collect", "screen", "edit", "write", "voice", "visuals", "render", "package"]
ETF_LIKE = {"SPY", "QQQ", "DIA", "IWM", "VOO", "VTI", "TQQQ", "SQQQ", "SOXL", "SOXS", "UVXY", "VXX", "ARKK", "TLT",
            "GLD", "SLV", "USO", "SMH", "XBI", "KRE", "HYG", "IBIT", "ETHA", "BITO", "SPXL", "SPXS", "TSLL", "NVDL", "MSTU"}
_SUFFIX = re.compile(r"[,.]?\s+(inc|corp|corporation|co|company|ltd|limited|plc|holdings?|group|n\.?v|s\.?a|ag|se|"
                     r"incorporated|class [abc]|/de/?|/md/?|com)\.?$", re.I)


def pretty_name(title: str) -> str:
    name = title.strip()
    for _ in range(3):
        name = _SUFFIX.sub("", name).strip(" ,.")
    if name.isupper():
        name = " ".join(w if len(w) <= 3 and w not in {"THE"} else w.capitalize() for w in name.split())
    return name or title


def with_times(s: Settings, macro: list[dict]) -> list[dict]:
    """Add viewer-facing times: New York first, then Los Angeles / Beijing (config `time_zones`)."""
    out = []
    for e in macro:
        dt = datetime.fromisoformat(e["datetime_et"])
        out.append(e | {f"time_{lang}": timefmt.multi(dt, lang, timefmt.zones_for(s, lang), with_day=True)
                        for lang in ("zh", "en")} | {f"spoken_{lang}": timefmt.spoken(dt, lang) for lang in ("zh", "en")})
    return out


class Run:
    STEPS = STEPS

    def __init__(self, settings: Settings, plan: SessionPlan):
        self.s = settings
        self.plan = plan
        self.dir = RUNS_DIR / plan.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.dir / "state.json"
        self.state: dict[str, Any] = json.loads(self.state_path.read_text()) if self.state_path.exists() else \
            {"done": [], "health": {}, "started": datetime.now().isoformat(timespec="seconds")}
        self.http = Http(settings.sec_user_agent)
        self.public = self.dir / "public"
        self.state["llm_provider"] = resolve_provider(settings)
        self.llm = make_client(settings, self.dir)

    # ---------- persistence ----------
    def save(self, name: str, obj: Any) -> None:
        (self.dir / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def load(self, name: str) -> Any:
        return json.loads((self.dir / name).read_text(encoding="utf-8"))

    def mark(self, step: str) -> None:
        if step not in self.state["done"]:
            self.state["done"].append(step)
        self.state.pop("handoff", None)
        self.flush()

    def flush(self) -> None:
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=1))

    def health(self, source: str, ok: bool, detail: str = "", status: str | None = None) -> None:
        if status is None:
            status = "ok" if ok else "failed"
        self.state["health"][source] = {"ok": ok, "status": status, "detail": detail}

    @property
    def langs(self) -> list[str]:
        return self.s.languages

    def _x_window(self) -> tuple[datetime, datetime]:
        """Previous close through now, or through the session's relevant end when the date is in the past."""
        now = datetime.now(ET)
        start = datetime.combine(self.plan.prev_date, dtime(16, 0), ET)
        if self.plan.target_date == now.date() and now > start:
            end = now
        elif self.plan.session == "premarket":
            end = datetime.combine(self.plan.target_date, dtime(9, 25), ET)
        else:
            end = datetime.combine(self.plan.target_date, dtime(20, 0), ET)
        if end <= start:
            end = start + timedelta(hours=18)
        return start, end

    def resolve_x(self, tickers: list[str], topics: list[str]) -> list[dict]:
        """Load `inputs/x_posts.json` (or the inbox) and, when `X_BEARER_TOKEN` is set, recent-search.

        Grokbot mode writes `handoff/x_request.json` and waits until a valid file is present,
        unless the API search itself succeeded. A missing token is skipped, not a failure.
        """
        if not self.s.get("x.enabled", True):
            self.health("x_posts", True, "disabled", status="skipped")
            self.health("x_api", True, "disabled", status="skipped")
            self.save("x_used.json", [])
            return []
        tickers = xsrc.dedupe_tickers(list(tickers))
        output = self.dir / "inputs" / "x_posts.json"
        provider = resolve_provider(self.s)
        request_path = self.dir / "handoff" / "x_request.json"
        start, end = self._x_window()
        accounts = list(self.s.get("x.accounts") or xsrc.DEFAULT_ACCOUNTS)
        if provider == "grokbot":
            output.parent.mkdir(parents=True, exist_ok=True)
            payload = xsrc.build_x_request(
                run_id=self.plan.run_id, session=self.plan.session, tickers=tickers, accounts=accounts,
                topics=topics, start=start, end=end, output_path=output)
            request_path.parent.mkdir(parents=True, exist_ok=True)
            request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        file_posts: list[dict] | None = None
        path = xsrc.find_x_posts_file(self.dir, self.s.get("x.inbox"), self.plan.run_id)
        if path:
            try:
                file_posts = xsrc.load_x_posts(path)
            except xsrc.XInputError as e:
                self.health("x_posts", False, str(e)[:300], status="failed")
                raise HandoffInvalid("x_request", request_path, path, str(e), kind="x_request") from e
            self.health("x_posts", True, f"{len(file_posts)} posts from {path.name}", status="ok")
        else:
            self.health("x_posts", True, "no file", status="skipped")

        token = self.s.env.get("X_BEARER_TOKEN")
        api_posts: list[dict] = []
        api_status = "skipped"
        if not token:
            self.health("x_api", True, "X_BEARER_TOKEN not set", status="skipped")
        else:
            try:
                api_posts = xsrc.search_recent(
                    self.http, token, tickers, accounts, start, end, int(self.s.get("x.max_posts", 25)))
                api_status = "ok"
                self.health("x_api", True, f"{len(api_posts)} posts", status="ok")
            except SourceError as e:
                api_status = "failed"
                log.warning("x api failed: %s", e)
                self.health("x_api", False, str(e)[:200], status="failed")

        if provider == "grokbot" and file_posts is None and api_status != "ok":
            log.info("waiting for X posts at %s", output)
            raise HandoffPending("x_request", request_path, output, kind="x_request")

        posts = xsrc.merge_posts(file_posts or [], api_posts, limit=int(self.s.get("x.max_posts", 25)))
        self.save("x_used.json", posts)
        return posts

    # ---------- steps ----------
    def step_collect(self) -> None:
        s, http, d = self.s, self.http, self.plan.target_date
        fixed = [b["symbol"] for b in s.get("market_board")] + [x["symbol"] for x in s.get("sectors")]
        watch = list(s.get("universe.watchlist"))

        ape = social.apewisdom(http, d)
        self.health("apewisdom", bool(ape), f"{len(ape)} tickers")
        screens = prices.screen_symbols(s.get("universe.yahoo_screens"), int(s.get("universe.screen_count", 15)))
        self.health("yahoo_screens", bool(screens), ", ".join(f"{k}:{len(v)}" for k, v in screens.items()))

        blacklist = set(s.get("universe.ticker_blacklist", []))
        names: dict[str, str] = {}
        caps: dict[str, float] = {}
        for rows in screens.values():
            for q in rows:
                if q["quote_type"] in (None, "EQUITY"):
                    names[q["symbol"]] = q["name"]
                    caps[q["symbol"]] = q["market_cap"]
        ape_syms = [r["symbol"] for r in ape[: int(s.get("universe.apewisdom_top", 40))]
                    if r["symbol"] not in blacklist and r["symbol"] not in ETF_LIKE and re.fullmatch(r"[A-Z]{1,5}", r["symbol"])]
        for r in ape:
            names.setdefault(r["symbol"], r["name"])
        unknown = [x for x in ape_syms if x not in caps and x not in watch]
        caps.update(prices.market_caps(unknown))
        universe = sorted(set(watch) | set(ape_syms) | set(caps))
        try:
            tmap = sec.ticker_to_cik(http)
            self.health("sec_ticker_map", True, f"{len(tmap)} tickers")
        except Exception as e:
            self.health("sec_ticker_map", False, str(e))

        px = prices.fetch_daily(sorted(set(universe) | set(fixed)), http, period="1y")
        got = px["symbol"].nunique()
        self.health("prices", got > 0.8 * len(set(universe) | set(fixed)), f"{got} symbols")
        px.to_csv(self.dir / "prices.csv.gz", index=False)

        cr = crypto.collect(http, s.get("crypto.symbols"), s.get("crypto.funding_symbols"), d)
        self.health("crypto", bool(cr["assets"]), f"{len(cr['assets'])} assets, F&G={bool(cr['fear_greed'])}")

        big = float(s.get("calendar.earnings_min_market_cap", 2e10))
        ahead = upcoming_sessions(d, int(s.get("calendar.earnings_days_ahead", 3)))
        earn = events.earnings(http, ahead, big, set(watch))
        # Who reported yesterday after the close / today, with timing + EPS (screener flag and the after-hours scene)
        reported = events.reports(http, [self.plan.prev_date, d], set(universe) | set(watch), big)
        macro_days = upcoming_sessions(d, int(s.get("calendar.macro_days_ahead", 5)))
        macro = events.macro(http, macro_days[0], macro_days[-1], s.get("calendar.macro_impact", ["High"]))
        self.health("earnings_calendar", bool(earn or reported), f"{len(earn)} upcoming, {len(reported)} reported")
        self.health("macro_calendar", True, f"{len(macro)} events")

        since = datetime.now(timezone.utc) - timedelta(hours=36)
        mnews = news.market_news(http, s.get("news.market_feeds", []), since)
        self.health("market_news", bool(mnews), f"{len(mnews)} headlines")

        self.save("collected.json", {
            "universe": universe, "fixed": fixed, "names": names, "caps": caps, "apewisdom": ape,
            "crypto": cr, "earnings": earn, "reported": reported, "macro": macro, "market_news": mnews,
        })

    def step_screen(self) -> None:
        s, http, d = self.s, self.http, self.plan.target_date
        col = self.load("collected.json")
        px = pd.read_csv(self.dir / "prices.csv.gz", parse_dates=["date"])
        px["date"] = px["date"].dt.date
        met = M.compute(px, d)
        if not met:
            self.state["done"] = [x for x in self.state["done"] if x != "collect"]   # a retry must re-download
            raise RuntimeError(f"no price bars for {d} — market data not updated yet?")

        try:
            tmap_titles = {}
            data = self.http.json("https://www.sec.gov/files/company_tickers.json", cache_ttl=7 * 86400)
            tmap_titles = {v["ticker"].upper(): v["title"] for v in data.values()}
        except Exception:
            pass
        names = {sym: col["names"].get(sym) or pretty_name(tmap_titles.get(sym, sym)) for sym in met}

        fixed = set(col["fixed"])
        exclude = fixed | ETF_LIKE
        watch = set(s.get("universe.watchlist"))
        caps = {k: v for k, v in col["caps"].items()}
        for w in watch:
            caps.setdefault(w, 0.0)            # watchlist: unknown cap is fine
        min_cap = float(s.get("universe.min_market_cap", 2e9))
        # Unknown cap only allowed for watchlist names; drop other unknowns (ETFs, junk tickers).
        eligible = {k: v for k, v in met.items() if k in watch or caps.get(k, 0) > 0}
        ape_map = {r["symbol"]: r for r in col["apewisdom"]}
        timing = lambda r: r.get("timing", r.get("time"))     # noqa: E731  ("time" = runs collected before 2026-10-18)
        rep = {r["symbol"] for r in col["reported"]
               if (r["date"] == d.isoformat() and timing(r) != "AMC") or (r["date"] == self.plan.prev_date.isoformat() and timing(r) == "AMC")}
        cooldown = store.recently_featured(d.isoformat(), int(s.get("screening.cooldown_days", 2)))
        missing_caps = [w for w in watch if not caps.get(w)]
        caps.update({k: v for k, v in prices.market_caps(missing_caps).items() if v})
        mover_preview = screener.movers({k: v for k, v in eligible.items() if caps.get(k, 0) > 0}, caps,
                                        float(s.get("screening.movers_min_market_cap", min_cap)), exclude)
        x_tickers = xsrc.dedupe_tickers(
            [row["symbol"] for side in mover_preview.values() for row in side] + list(watch)
            + [r["symbol"] for r in col["apewisdom"][:20]] + list(s.get("crypto.symbols") or []))
        x_posts = self.resolve_x(x_tickers, topics=["recap", "earnings"])
        x_buzz = xsrc.buzz_by_ticker(x_posts)
        ranked = screener.score_universe(eligible, ape_map, rep, caps, min_cap, cooldown, exclude, watch, x_buzz)
        top = ranked[: int(s.get("screening.candidates", 18))]
        syms = [r["symbol"] for r in top]
        log.info("candidates: %s", ", ".join(f"{r['symbol']}({r['score']})" for r in top))

        sec_data = sec.collect(http, syms, d, int(s.get("screening.sec_lookback_days", 5)))
        self.health("sec_edgar", bool(sec_data), f"{len(sec_data)} companies")
        stw = social.stocktwits(http, syms, d)
        self.health("stocktwits", bool(stw), f"{len(stw)} symbols")
        reddit = social.reddit_posts(http, s.env.get("REDDIT_CLIENT_ID"), s.env.get("REDDIT_CLIENT_SECRET"), syms)
        if s.env.get("REDDIT_CLIENT_ID"):
            self.health("reddit", bool(reddit), f"{len(reddit)} symbols")
        since = datetime.now(timezone.utc) - timedelta(days=2)
        cands = []
        n_news = 0
        for r in top:
            sym = r["symbol"]
            heads = news.ticker_news(http, sym, names[sym], int(s.get("news.per_ticker", 8)), since)
            heads += news.finnhub_news(http, s.env.get("FINNHUB_API_KEY"), sym, d)
            n_news += len(heads)
            mine = [p for p in x_posts if (p.get("matched") or {}).get("ticker") in {sym, sym.replace("-", ".")}]
            cv = datapack.candidate_view(sym, names[sym], r, met[sym], ape_map.get(sym), stw.get(sym), heads[:8],
                                         sec_data.get(sym), sym in rep,
                                         x_posts=xsrc.posts_for_prompt(mine, 5), x_buzz=x_buzz.get(sym))
            if reddit.get(sym):
                cv["reddit_top_posts"] = reddit[sym][:5]
            cands.append(cv)
        self.health("ticker_news", n_news > 0, f"{n_news} headlines")

        mv = mover_preview
        for side in mv.values():
            for row in side:
                row["name"] = names.get(row["symbol"], row["symbol"])
        up = sum(1 for k, m in eligible.items() if k not in exclude and m["change_pct"] > 0)
        down = sum(1 for k, m in eligible.items() if k not in exclude and m["change_pct"] < 0)
        board = s.get("market_board")
        base = {
            "session": self.plan.session, "date": d.isoformat(), "prev_session": self.plan.prev_date.isoformat(),
            "market": datapack.market_rows(board, met, px, d),
            "sectors": [{"symbol": x["symbol"], "name_zh": x["name_zh"], "name_en": x["name_en"],
                         "change_pct": met[x["symbol"]]["change_pct"], "change_5d_pct": met[x["symbol"]].get("change_5d_pct")}
                        for x in s.get("sectors") if x["symbol"] in met],
            "breadth": {"universe_size": up + down, "advancers": up, "decliners": down},
            "movers": mv,
            "megacaps": [{"symbol": k, "name": names.get(k, k), "change_pct": eligible[k]["change_pct"],
                          "market_cap_billion": round(caps[k] / 1e9)}
                         for k in sorted((k for k in eligible if caps.get(k, 0) >= 3e11), key=lambda k: -caps[k])][:12],
            "retail_trending": [{k: r[k] for k in ("symbol", "rank", "mentions", "mentions_24h_ago")}
                                for r in col["apewisdom"][:10]],
            "crypto": col["crypto"],
            "after_hours": self._after_hours(col, met, watch),
            "calendar": {"earnings": col["earnings"][:14], "macro": with_times(self.s, col["macro"][:12])},
            "market_headlines": [{"title": h["title"], "source": h["source"]} for h in col["market_news"][:25]],
            "x_posts": xsrc.posts_for_prompt(x_posts, int(s.get("x.max_posts", 25))),
        }
        self.save("research.json", {"base": base, "candidates": cands})

    def _after_hours(self, col: dict, met: dict, watch: set[str]) -> list[dict]:
        """Companies that reported after today's close: EPS vs estimate + after-hours move (tomorrow's headlines)."""
        d = self.plan.target_date
        big = float(self.s.get("calendar.earnings_min_market_cap", 2e10))
        amc = [r for r in col["reported"] if r["date"] == d.isoformat() and r.get("timing") == "AMC"
               and (r["market_cap"] >= big or r["symbol"] in watch)][: int(self.s.get("calendar.after_hours_max", 5))]
        if not amc:
            return []
        quotes = prices.extended_quotes([r["symbol"] for r in amc])
        missing = [r["symbol"] for r in amc if r["symbol"] not in met]
        if missing:                                   # reporters outside today's universe: closes from daily bars
            try:
                px = prices.fetch_daily(missing, self.http, period="3mo")
                met = met | M.compute(px, d)
            except Exception as e:
                log.warning("after-hours closes unavailable: %s", e)
        t_close = datetime.combine(d, dtime(16, 0), ET).timestamp()
        t_end = datetime.combine(d, dtime(20, 0), ET).timestamp()        # after-hours session of `d` only
        out = []
        for r in amc:
            sym, q = r["symbol"], quotes.get(r["symbol"]) or {}
            close = (met.get(sym) or {}).get("close")
            if close is None and q.get("regular_time") and datetime.fromtimestamp(q["regular_time"], ET).date() == d:
                close = q["regular_price"]
            ah = q.get("post_price") if t_close <= (q.get("post_time") or 0) <= t_end else None
            heads = news.ticker_news(self.http, sym, r["name"], 4, datetime.fromtimestamp(t_close, timezone.utc))
            out.append({"symbol": sym, "name": pretty_name(r["name"]), "fiscal_quarter": r.get("fiscal_quarter"),
                        "eps_actual": r["eps_actual"], "eps_estimate": r["eps_estimate"],
                        "eps_surprise_pct": r["eps_surprise_pct"], "market_cap_billion": round(r["market_cap"] / 1e9),
                        "close": round(close, 2) if close else None, "after_hours_price": ah,
                        "after_hours_change_pct": round((ah / close - 1) * 100, 2) if ah and close else None,
                        "headlines": [{"title": h["title"], "source": h["source"]} for h in heads[:4]]})
        self.health("after_hours", True, f"{len(out)} reports, {sum(1 for x in out if x['after_hours_price'])} with quotes")
        return out

    def step_edit(self) -> None:
        res = self.load("research.json")
        base, cands = res["base"], res["candidates"]
        w = Writer(self.s, self.llm)
        n = int(self.s.get("screening.stories", 3))
        view = datapack.strip_series(datapack.llm_view(base, cands))
        editor = w.editor(self.plan.session, self.plan.target_date.isoformat(), view, n)
        self.health("llm_editor", editor.get("source") == "llm", editor.get("source", ""))
        self.save("editor.json", editor)
        store.upsert("sentiment_scores", pd.DataFrame([
            {"symbol": x["symbol"], "date": self.plan.target_date, "score": x["score"],
             "bull_point": x["bull_point"]["en"], "bear_point": x["bear_point"]["en"]} for x in editor.get("sentiment", [])]))

        px = pd.read_csv(self.dir / "prices.csv.gz", parse_dates=["date"])
        px["date"] = px["date"].dt.date
        opts = {}
        for st in editor["stories"]:
            spot = next(c["metrics"]["close"] for c in cands if c["symbol"] == st["symbol"])
            opts[st["symbol"]] = options.snapshot(st["symbol"], spot)
        self.health("options", any(opts.values()), f"{sum(1 for v in opts.values() if v)}/{len(opts)} chains")
        wv = datapack.writer_view(base, cands, editor, opts)
        self.save("writer_view.json", wv)
        self.save("render_extra.json", {
            "market": base["market"],
            "candles": {st["symbol"]: M.candles(px, st["symbol"], self.plan.target_date, 60) for st in editor["stories"]},
            "btc_history": base["crypto"].get("btc_history", []),
        })

    def step_write(self) -> None:
        wv = datapack.strip_series(self.load("writer_view.json"))
        editor = self.load("editor.json")
        w = Writer(self.s, self.llm)
        scenes = scene_plan(len(editor["stories"]), len(wv.get("after_hours") or []))
        research = self.load("research.json")
        reference = {"writer": wv, "candidates": research["candidates"], "editor": editor.get("stories")}
        scripts = w.scripts(self.plan.session, wv, editor, scenes, reference)
        for lang, sc in scripts.items():
            theme_issues = factcheck.check_text(editor["market_theme"][lang], factcheck.collect_values(reference))
            sc["_factcheck"] = sc.get("_factcheck", []) + [f"[market theme] {i}" for i in theme_issues]
            self.save(f"script_{lang}.json", sc)
            self.health(f"llm_script_{lang}", sc.get("_source") == "llm",
                        f"{sc.get('_source')}, {len(sc.get('_factcheck', []))} unverified numbers")
        if self.s.get("factcheck.block_on_fail") and any(sc.get("_factcheck") for sc in scripts.values()):
            raise RuntimeError("fact check failed and factcheck.block_on_fail is set; see review.md / script_*.json")
        threads = w.threads(wv, scripts, render.card_ids(wv))
        self.save("threads.json", threads)

    def step_voice(self) -> None:
        scripts = {lang: self.load(f"script_{lang}.json")["scenes"] for lang in self.langs}
        audio_dir = self.public / "audio"
        if audio_dir.exists():
            shutil.rmtree(audio_dir)
        timelines = tts.synthesize_all(self.s, scripts, self.public, self.dir)
        for lang, tl in timelines.items():
            self.save(f"timeline_{lang}.json", tl)
        self.health("tts", True, self.s.get("tts.provider", "indextts"))

    def step_visuals(self) -> None:
        wv = self.load("writer_view.json")
        spy = next((r for r in wv["market"] if r["symbol"] == "SPY"), None)
        mood = "flat" if not spy or abs(spy["change_pct"]) < 0.5 else ("up" if spy["change_pct"] > 0 else "down")
        bg = None
        if self.s.get("comfy.enabled"):
            p = comfy.background(self.s.get("comfy.url"), self.s.get("comfy.model", "krea2"), mood,
                                 self.public / "img" / "bg.png", self.plan.run_id, int(self.s.get("comfy.timeout_sec", 180)))
            bg = "img/bg.png" if p else None
            self.health("comfyui", bool(p), "background generated" if p else "skipped/failed")
        bgm = None
        track = render.pick_bgm(ASSETS_DIR / "music", self.plan.run_id)
        if track:
            bgm = render.copy_into(track, self.public, f"music/bgm{track.suffix}")
        self.save("visuals.json", {"bg": bg, "bgm": bgm, "mood": mood})

    def step_render(self) -> None:
        wv, extra, editor, vis = (self.load(n) for n in ("writer_view.json", "render_extra.json", "editor.json", "visuals.json"))
        jobs = []
        rdir = self.dir / "render"
        for lang in self.langs:
            script = self.load(f"script_{lang}.json")
            tl = self.load(f"timeline_{lang}.json")
            props = render.build_props(self.s, lang, wv, extra, script, tl, editor, vis["bg"], vis["bgm"],
                                       self.plan.target_date, self.plan.session)
            self.save(f"props_{lang}.json", props)
            jobs.append({"kind": "video", "composition": "Briefing", "props": props, "out": str(rdir / f"{lang}_raw.mp4")})
            jobs.append({"kind": "still", "composition": "Thumbnail", "props": render.thumbnail_props(lang, script, props, wv),
                         "out": str(rdir / f"thumbnail_{lang}.png")})
            for cid in render.card_ids(wv):
                jobs.append({"kind": "still", "composition": "Card", "props": {"briefing": props, "sceneId": cid},
                             "out": str(rdir / f"cards_{lang}" / f"{cid}.png")})
        t0 = time.time()
        render.run_remotion(jobs, self.public, int(self.s.get("video.concurrency", 8)), self.dir / "render_job.json")
        for lang in self.langs:
            render.loudnorm(rdir / f"{lang}_raw.mp4", rdir / f"{lang}.mp4")
        log.info("render finished in %.0fs", time.time() - t0)

    def step_package(self) -> None:
        wv, editor = self.load("writer_view.json"), self.load("editor.json")
        threads = self.load("threads.json")
        scripts, durations = {}, {}
        rdir = self.dir / "render"
        for lang in self.langs:
            script, props = self.load(f"script_{lang}.json"), self.load(f"props_{lang}.json")
            scripts[lang] = script
            durations[lang] = sum(sc["durationInFrames"] for sc in props["scenes"]) / props["fps"]
            cards = {cid: rdir / f"cards_{lang}" / f"{cid}.png" for cid in render.card_ids(wv)}
            package.build(self.dir, lang, script, props, wv, threads.get(lang, []), rdir / f"{lang}.mp4",
                          rdir / f"thumbnail_{lang}.png", cards)
        package.review_md(self.dir, scripts, threads, self.state["health"], editor, durations)
        self.state["finished"] = datetime.now().isoformat(timespec="seconds")
        store.record_run(self.plan.run_id, self.plan.session, self.plan.target_date.isoformat(), "done",
                         [s["symbol"] for s in editor["stories"]], self.state["started"], self.state["finished"],
                         {k: v["ok"] for k, v in self.state["health"].items()})

    # ---------- driver ----------
    def execute(self, start: str | None = None, only: str | None = None, force: bool = False) -> Path:
        steps = self.STEPS
        if only:
            steps = [only]
        elif start:
            steps = steps[steps.index(start):]
        elif not force:
            steps = [st for st in steps if st not in self.state["done"]]
        if force and resolve_provider(self.s) == "grokbot":
            self.state.pop("handoff", None)
            shutil.rmtree(self.dir / "llm", ignore_errors=True)
            handoff_dir = self.dir / "handoff"
            if handoff_dir.exists():
                for stale in list(handoff_dir.glob("*.response.json")) + list(handoff_dir.glob("*.error.txt")):
                    stale.unlink()
            self.flush()
        if not steps:
            log.info("run %s already complete (use --force to redo)", self.plan.run_id)
            return self.dir / "upload"
        for st in steps:
            fn: Callable[[], None] = getattr(self, f"step_{st}")
            log.info("── step %s ──", st)
            t0 = time.time()
            try:
                fn()
            except (HandoffPending, HandoffInvalid) as e:
                self.state["handoff"] = {
                    "status": "invalid" if isinstance(e, HandoffInvalid) else "waiting",
                    "step": st, "name": e.name, "kind": e.kind,
                    "request": str(e.request), "response": str(e.response),
                    "detail": getattr(e, "detail", ""),
                }
                self.flush()
                store.record_run(self.plan.run_id, self.plan.session, self.plan.target_date.isoformat(), f"waiting:{st}",
                                 [], self.state["started"], None, {"handoff": e.name})
                raise
            except Exception:
                self.flush()
                store.record_run(self.plan.run_id, self.plan.session, self.plan.target_date.isoformat(), f"failed:{st}",
                                 [], self.state["started"], None, {"failed_step": st})
                raise
            self.mark(st)
            log.info("   %s done in %.0fs", st, time.time() - t0)
        return self.dir / "upload"


def cleanup_old_runs(retention_days: int) -> None:
    cutoff = time.time() - retention_days * 86400
    for d in RUNS_DIR.iterdir() if RUNS_DIR.exists() else []:
        if d.is_dir() and d.stat().st_mtime < cutoff:
            for sub in ("public", "render", "llm"):
                shutil.rmtree(d / sub, ignore_errors=True)
            for f in d.glob("prices.csv.gz"):
                f.unlink()
