"""Daily OHLCV: yfinance batch download first, Nasdaq public API per-symbol as fallback."""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from ..http import Http, SourceError
from .. import store

log = logging.getLogger(__name__)

_NASDAQ_SKIP = ("^", "=", ".NYB", "-USD")  # indices/futures/fx/crypto are not on the Nasdaq quote API


def fetch_daily(symbols: list[str], http: Http, period: str = "1y") -> pd.DataFrame:
    """Return long dataframe [symbol, date, open, high, low, close, volume]."""
    symbols = sorted(set(symbols))
    frames: list[pd.DataFrame] = []
    missing = set(symbols)
    try:
        raw = yf.download(symbols, period=period, interval="1d", auto_adjust=True, progress=False,
                          group_by="ticker", threads=True)
        for sym in symbols:
            try:
                sub = raw[sym] if isinstance(raw.columns, pd.MultiIndex) else raw
            except KeyError:
                continue
            sub = sub.dropna(subset=["Close"])
            if sub.empty:
                continue
            df = sub.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].reset_index()
            df = df.rename(columns={"Date": "date"})
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df.insert(0, "symbol", sym)
            frames.append(df)
            missing.discard(sym)
    except Exception as e:  # yfinance raises a zoo of exception types
        log.warning("yfinance batch download failed: %s", e)

    if missing:
        log.info("yfinance missing %d symbols, trying Nasdaq fallback: %s", len(missing), sorted(missing)[:10])
    for sym in sorted(missing):
        if any(t in sym for t in _NASDAQ_SKIP):
            continue
        try:
            frames.append(_nasdaq_history(sym, http, period_days=370 if period == "1y" else 100))
        except SourceError as e:
            log.warning("nasdaq history failed for %s: %s", sym, e)

    if not frames:
        raise SourceError("no price data from any source")
    out = pd.concat(frames, ignore_index=True)
    store.upsert("prices_daily", out[["symbol", "date", "open", "high", "low", "close", "volume"]])
    return out


def _nasdaq_history(sym: str, http: Http, period_days: int) -> pd.DataFrame:
    to = date.today()
    frm = to - timedelta(days=period_days)
    asset = "etf" if sym in {"SPY", "QQQ", "DIA", "IWM"} or sym.startswith("XL") else "stocks"
    data = http.json(
        f"https://api.nasdaq.com/api/quote/{sym.replace('-', '.')}/historical",
        params={"assetclass": asset, "fromdate": frm.isoformat(), "todate": to.isoformat(), "limit": 400},
    )
    rows = (((data or {}).get("data") or {}).get("tradesTable") or {}).get("rows") or []
    if not rows:
        raise SourceError(f"nasdaq: empty history for {sym}")

    def num(s: str) -> float:
        return float(str(s).replace("$", "").replace(",", "") or "nan")

    df = pd.DataFrame({
        "symbol": sym,
        "date": [pd.to_datetime(r["date"]).date() for r in rows],
        "open": [num(r["open"]) for r in rows],
        "high": [num(r["high"]) for r in rows],
        "low": [num(r["low"]) for r in rows],
        "close": [num(r["close"]) for r in rows],
        "volume": [num(r["volume"]) for r in rows],
    })
    return df.sort_values("date").reset_index(drop=True)


def screen_symbols(screens: list[str], count: int) -> dict[str, list[dict]]:
    """Yahoo predefined screens → {screen: [{symbol, name, market_cap, quote_type}]}."""
    out: dict[str, list[dict]] = {}
    for name in screens:
        try:
            res = yf.screen(name, count=count)
            out[name] = [{"symbol": q["symbol"], "name": q.get("shortName") or q.get("longName") or q["symbol"],
                          "market_cap": float(q.get("marketCap") or 0), "quote_type": q.get("quoteType")}
                         for q in res.get("quotes", []) if q.get("symbol")]
        except Exception as e:
            log.warning("yahoo screen %s failed: %s", name, e)
    return out


def market_caps(symbols: list[str]) -> dict[str, float]:
    """0.0 means unknown (ETFs, bad tickers, lookup failure)."""
    from concurrent.futures import ThreadPoolExecutor

    def one(sym: str) -> float:
        try:
            return float(yf.Ticker(sym).fast_info["marketCap"] or 0)
        except Exception:
            return 0.0

    with ThreadPoolExecutor(max_workers=6) as ex:
        return dict(zip(symbols, ex.map(one, symbols)))


def company_names(symbols: list[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for sym in symbols:
        try:
            info = yf.Ticker(sym).get_info()
            names[sym] = info.get("shortName") or info.get("longName") or sym
        except Exception:
            names[sym] = sym
    return names


def premarket_quotes(symbols: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for sym in symbols:
        try:
            info = yf.Ticker(sym).get_info()
            pre, prev = info.get("preMarketPrice"), info.get("regularMarketPreviousClose") or info.get("previousClose")
            if pre and prev:
                out[sym] = {"pre_price": pre, "pre_change_pct": (pre / prev - 1) * 100}
        except Exception as e:
            log.debug("premarket quote failed %s: %s", sym, e)
    return out
