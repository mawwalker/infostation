"""Forward-looking calendar: earnings (Nasdaq public API) and macro events (ForexFactory weekly feed)."""
from __future__ import annotations

import logging
from datetime import date, datetime

from ..http import Http, SourceError

log = logging.getLogger(__name__)


def _money(s: str | None) -> float:
    try:
        return float(str(s).replace("$", "").replace(",", "").replace("(", "-").replace(")", ""))
    except (TypeError, ValueError):
        return 0.0


def earnings(http: Http, days: list[date], min_cap: float, always: set[str]) -> list[dict]:
    out = []
    for d in days:
        try:
            data = http.json("https://api.nasdaq.com/api/calendar/earnings", params={"date": d.isoformat()})
        except SourceError as e:
            log.warning("nasdaq earnings %s failed: %s", d, e)
            continue
        for r in ((data or {}).get("data") or {}).get("rows") or []:
            cap = _money(r.get("marketCap"))
            sym = r.get("symbol", "")
            if cap < min_cap and sym not in always:
                continue
            out.append({"date": d.isoformat(), "symbol": sym, "name": r.get("name", ""),
                        "time": {"time-pre-market": "BMO", "time-after-hours": "AMC"}.get(r.get("time"), "TBD"),
                        "eps_forecast": r.get("epsForecast") or None, "market_cap": cap})
    out.sort(key=lambda r: (r["date"], -r["market_cap"]))
    return out


def reported_today(http: Http, d: date, min_cap: float) -> list[dict]:
    """Companies scheduled to report on `d` (used to explain why a stock moved)."""
    return earnings(http, [d], min_cap, set())


def macro(http: Http, start: date, end: date, impacts: list[str]) -> list[dict]:
    out = []
    for feed in ("thisweek", "nextweek"):
        try:
            data = http.json(f"https://nfs.faireconomy.media/ff_calendar_{feed}.json", cache_ttl=3 * 3600)
        except SourceError as e:
            log.info("forexfactory %s failed: %s", feed, e)
            continue
        for ev in data:
            if ev.get("country") != "USD" or ev.get("impact") not in impacts:
                continue
            ts = datetime.fromisoformat(ev["date"])
            if start <= ts.date() <= end:
                out.append({"datetime_et": ts.isoformat(), "date": ts.date().isoformat(), "event": ev["title"],
                            "impact": ev["impact"], "forecast": ev.get("forecast") or None,
                            "previous": ev.get("previous") or None})
    uniq = {(e["datetime_et"], e["event"]): e for e in out}
    return sorted(uniq.values(), key=lambda e: e["datetime_et"])
