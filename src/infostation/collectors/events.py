"""Calendar: earnings (Nasdaq public API + Yahoo for timing/results) and macro events (ForexFactory weekly feed)."""
from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time

import yfinance as yf

from ..http import Http, SourceError
from ..market_calendar import ET

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


def _num(x) -> float | None:
    try:
        v = float(str(x).replace("$", "").replace(",", "").replace("(", "-").replace(")", ""))
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def eps_basis_from_summary(payload: dict | None) -> str | None:
    """Yahoo `earningsHistory.defaultMethodology`: `gaap` or `nongaap` (adjusted). Missing → no label."""
    try:
        history = (payload or {})["quoteSummary"]["result"][0]["earningsHistory"]
        method = history.get("defaultMethodology")
    except (AttributeError, KeyError, IndexError, TypeError):
        return None
    return {"gaap": "GAAP", "nongaap": "adjusted"}.get(str(method).strip().lower())


def _yahoo_eps_basis(ticker) -> str | None:
    try:
        payload = ticker._analysis._fetch(["earningsHistory"])
    except Exception as e:
        log.debug("yahoo eps basis %s failed: %s", getattr(ticker, "ticker", "?"), e)
        return None
    return eps_basis_from_summary(payload)


def _yahoo_report(sym: str, d: date) -> dict:
    """Report time and EPS for `sym` on `d` from Yahoo's earnings calendar (Nasdaq drops the time once reported)."""
    try:
        ticker = yf.Ticker(sym)
    except Exception as e:
        log.debug("yahoo earnings dates %s failed: %s", sym, e)
        return {}
    try:
        ed = ticker.get_earnings_dates(limit=8)
    except Exception as e:
        log.debug("yahoo earnings dates %s failed: %s", sym, e)
        ed = None
    basis = _yahoo_eps_basis(ticker)
    found: dict = {}
    if ed is not None and not ed.empty:
        for ts, row in ed.iterrows():
            t = ts.tz_convert(ET) if ts.tzinfo else ts.tz_localize(ET)
            if t.date() != d:
                continue
            hm = t.time()
            timing = "BMO" if hm < time(9, 30) else "AMC" if hm >= time(16, 0) else "DURING"
            if hm == time(0, 0):
                timing = "TBD"
            found = {"timing": timing, "report_time_et": t.isoformat() if timing != "TBD" else None,
                     "eps_actual": _num(row.get("Reported EPS")), "eps_estimate": _num(row.get("EPS Estimate")),
                     "surprise_pct": _num(row.get("Surprise(%)"))}
            break
    if basis:
        found["eps_basis"] = basis
    return found


def reports(http: Http, days: list[date], keep: set[str], min_cap: float) -> list[dict]:
    """Companies reporting on `days` (symbol in `keep` or market cap ≥ min_cap), with timing and results so far.

    timing: BMO (before 9:30 ET) | AMC (after 16:00 ET) | DURING | TBD. EPS fields are None until reported.

    Nasdaq leaves last year's EPS in `eps` and `surprise` as ``N/A`` until it posts this report.
    That year-ago figure is not the actual. Yahoo's number for this date wins; with no surprise
    and no Yahoo actual, `eps_actual` stays empty.
    """
    rows = []
    for d in days:
        try:
            data = http.json("https://api.nasdaq.com/api/calendar/earnings", params={"date": d.isoformat()})
        except SourceError as e:
            log.warning("nasdaq earnings %s failed: %s", d, e)
            continue
        for r in ((data or {}).get("data") or {}).get("rows") or []:
            sym, cap = r.get("symbol", ""), _money(r.get("marketCap"))
            if sym in keep or cap >= min_cap:
                rows.append((d, sym, cap, r))

    def one(item: tuple) -> dict:
        d, sym, cap, r = item
        y = _yahoo_report(sym, d)
        timing = {"time-pre-market": "BMO", "time-after-hours": "AMC"}.get(r.get("time")) or y.get("timing") or "TBD"
        eps = _num(r.get("eps"))
        est = _num(r.get("epsForecast"))
        if est is None:
            est = y.get("eps_estimate")
        surprise = _num(r.get("surprise"))
        if y.get("eps_actual") is not None:
            # Nasdaq's `eps` is the year-ago print (surprise "N/A") until the row updates.
            # Yahoo's earnings dates are the reported figure for this date.
            eps = y["eps_actual"]
            surprise = y.get("surprise_pct")
            if y.get("eps_estimate") is not None:
                est = y["eps_estimate"]
        elif surprise is None:
            eps = None
        if surprise is None and eps is not None and est:
            surprise = (eps - est) / abs(est) * 100
        return {"date": d.isoformat(), "symbol": sym, "name": r.get("name", ""), "timing": timing,
                "report_time_et": y.get("report_time_et"), "market_cap": cap,
                "eps_actual": eps, "eps_estimate": est, "eps_basis": y.get("eps_basis"),
                "eps_surprise_pct": round(surprise, 2) if surprise is not None else None,
                "fiscal_quarter": r.get("fiscalQuarterEnding")}

    with ThreadPoolExecutor(max_workers=6) as ex:
        out = list(ex.map(one, rows))
    out.sort(key=lambda r: (r["date"], -r["market_cap"]))
    return out


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
