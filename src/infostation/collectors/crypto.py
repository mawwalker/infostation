"""Crypto snapshot: Binance public endpoints, CoinGecko fallback, alternative.me Fear & Greed."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

import pandas as pd

from ..http import Http, SourceError
from .. import store

log = logging.getLogger(__name__)

COINGECKO_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple", "BNB": "binancecoin",
                 "DOGE": "dogecoin", "ADA": "cardano", "AVAX": "avalanche-2", "LINK": "chainlink", "TON": "the-open-network"}


def collect(http: Http, symbols: list[str], funding_symbols: list[str], as_of: date) -> dict:
    out: dict = {"assets": [], "funding": {}, "fear_greed": None, "global": None, "btc_history": []}
    try:
        out["assets"] = _binance_tickers(http, symbols)
    except SourceError as e:
        log.warning("binance tickers failed (%s), using CoinGecko", e)
        try:
            out["assets"] = _coingecko_prices(http, symbols)
        except SourceError as e2:
            log.error("crypto prices unavailable: %s", e2)

    for sym in funding_symbols:
        try:
            d = http.json("https://fapi.binance.com/fapi/v1/premiumIndex", params={"symbol": f"{sym}USDT"})
            out["funding"][sym] = round(float(d["lastFundingRate"]) * 100, 4)  # percent per 8h
        except (SourceError, KeyError, ValueError) as e:
            log.warning("funding %s failed: %s", sym, e)

    try:
        d = http.json("https://api.alternative.me/fng/", params={"limit": 8})
        vals = d["data"]
        out["fear_greed"] = {"value": int(vals[0]["value"]), "label": vals[0]["value_classification"],
                             "week_ago": int(vals[7]["value"]) if len(vals) > 7 else None}
    except (SourceError, KeyError, ValueError, IndexError) as e:
        log.warning("fear&greed failed: %s", e)

    try:
        g = http.json("https://api.coingecko.com/api/v3/global")["data"]
        out["global"] = {"total_mcap_usd": round(g["total_market_cap"]["usd"]),
                         "mcap_change_24h_pct": round(g["market_cap_change_percentage_24h_usd"], 2),
                         "btc_dominance": round(g["market_cap_percentage"]["btc"], 2)}
    except (SourceError, KeyError) as e:
        log.warning("coingecko global failed: %s", e)

    try:
        out["btc_history"] = _binance_klines(http, "BTCUSDT", 90)
    except SourceError as e:
        log.warning("btc klines failed: %s", e)

    if out["assets"]:
        store.upsert("crypto_daily", pd.DataFrame([{
            "symbol": a["symbol"], "date": as_of, "price": a["price"], "change_pct": a["change_pct"],
            "quote_volume": a.get("quote_volume"), "funding_rate": out["funding"].get(a["symbol"]),
        } for a in out["assets"]]))
    return out


def _px(x: float) -> float:
    """Spoken-friendly precision: 81426.84 → 81427, 2393.2 → 2393.2, 0.1234 → 0.1234."""
    return round(x) if x >= 10000 else round(x, 2) if x >= 1 else round(x, 4)


def _binance_tickers(http: Http, symbols: list[str]) -> list[dict]:
    pairs = json.dumps([f"{s}USDT" for s in symbols], separators=(",", ":"))
    data = http.json("https://api.binance.com/api/v3/ticker/24hr", params={"symbols": pairs})
    by = {d["symbol"]: d for d in data}
    out = []
    for s in symbols:
        d = by.get(f"{s}USDT")
        if d:
            out.append({"symbol": s, "price": _px(float(d["lastPrice"])), "change_pct": round(float(d["priceChangePercent"]), 2),
                        "high": _px(float(d["highPrice"])), "low": _px(float(d["lowPrice"])),
                        "quote_volume": round(float(d["quoteVolume"]))})
    if not out:
        raise SourceError("binance returned no tickers")
    return out


def _coingecko_prices(http: Http, symbols: list[str]) -> list[dict]:
    ids = [COINGECKO_IDS[s] for s in symbols if s in COINGECKO_IDS]
    data = http.json("https://api.coingecko.com/api/v3/simple/price",
                     params={"ids": ",".join(ids), "vs_currencies": "usd",
                             "include_24hr_change": "true", "include_24hr_vol": "true"})
    out = []
    for s in symbols:
        d = data.get(COINGECKO_IDS.get(s, ""), {})
        if d:
            out.append({"symbol": s, "price": _px(d["usd"]), "change_pct": round(d.get("usd_24h_change", 0.0), 2),
                        "quote_volume": d.get("usd_24h_vol")})
    return out


def _binance_klines(http: Http, pair: str, days: int) -> list[dict]:
    data = http.json("https://data-api.binance.vision/api/v3/klines",
                     params={"symbol": pair, "interval": "1d", "limit": days})
    return [{"date": datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).date().isoformat(),
             "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4])} for k in data]
