"""Options positioning for featured tickers only (yfinance chains are heavy and rate-limited)."""
from __future__ import annotations

import logging
import math

import yfinance as yf

log = logging.getLogger(__name__)


def snapshot(symbol: str, spot: float, n_expiries: int = 2) -> dict | None:
    try:
        tk = yf.Ticker(symbol)
        exps = list(tk.options)[:n_expiries]
    except Exception as e:
        log.info("options list failed %s: %s", symbol, e)
        return None
    if not exps:
        return None
    call_vol = put_vol = call_oi = put_oi = 0.0
    implied_move = atm_iv = None
    for i, exp in enumerate(exps):
        try:
            ch = tk.option_chain(exp)
        except Exception as e:
            log.info("option chain failed %s %s: %s", symbol, exp, e)
            continue
        c, p = ch.calls.fillna(0), ch.puts.fillna(0)
        call_vol += float(c["volume"].sum())
        put_vol += float(p["volume"].sum())
        call_oi += float(c["openInterest"].sum())
        put_oi += float(p["openInterest"].sum())
        if i == 0 and spot:
            # ATM straddle mid / spot ≈ expected move to first expiry
            k = c.iloc[(c["strike"] - spot).abs().argsort()[:1]]
            pk = p[p["strike"] == float(k["strike"].iloc[0])]
            if not k.empty and not pk.empty:
                cm = _mid(k.iloc[0])
                pm = _mid(pk.iloc[0])
                if cm and pm:
                    implied_move = (cm + pm) / spot * 100
                atm_iv = float(k["impliedVolatility"].iloc[0]) * 100
    if not (call_vol or call_oi):
        return None
    return {
        "expiries": exps,
        "put_call_volume": round(put_vol / call_vol, 2) if call_vol else None,
        "put_call_oi": round(put_oi / call_oi, 2) if call_oi else None,
        "call_volume": int(call_vol), "put_volume": int(put_vol),
        "implied_move_pct": round(implied_move, 1) if implied_move else None,
        "atm_iv_pct": round(atm_iv, 1) if atm_iv and not math.isnan(atm_iv) else None,
    }


def _mid(row) -> float | None:
    bid, ask, last = float(row.get("bid", 0)), float(row.get("ask", 0)), float(row.get("lastPrice", 0))
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    return last or None
