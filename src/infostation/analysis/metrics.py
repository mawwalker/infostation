"""Per-symbol technical metrics computed from the long price frame."""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd


def _rsi(close: pd.Series, n: int = 14) -> float | None:
    if len(close) <= n:
        return None
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up.iloc[-1] / down.iloc[-1] if down.iloc[-1] else math.inf
    return round(100 - 100 / (1 + rs), 1)


def compute(prices: pd.DataFrame, as_of: date) -> dict[str, dict]:
    """Metrics for every symbol that has a bar on `as_of` (stale symbols are dropped)."""
    out: dict[str, dict] = {}
    for sym, g in prices.groupby("symbol"):
        g = g.sort_values("date")
        g = g[g["date"] <= as_of]
        if len(g) < 21 or g["date"].iloc[-1] != as_of:
            continue
        c, v = g["close"].astype(float), g["volume"].astype(float)
        last, prev = c.iloc[-1], c.iloc[-2]
        rets = c.pct_change().dropna()
        vol60 = rets.iloc[-61:-1].std() if len(rets) > 20 else rets.std()
        ret1 = (last / prev - 1) * 100
        avg_vol20 = v.iloc[-21:-1].mean()
        hi52, lo52 = g["high"].iloc[-252:].max(), g["low"].iloc[-252:].min()
        ytd = g[pd.to_datetime(g["date"]).dt.year == as_of.year]
        out[sym] = {
            "close": round(float(last), 4),
            "prev_close": round(float(prev), 4),
            "change_pct": round(float(ret1), 2),
            "change_5d_pct": round(float((last / c.iloc[-6] - 1) * 100), 2) if len(c) > 5 else None,
            "change_1m_pct": round(float((last / c.iloc[-22] - 1) * 100), 2) if len(c) > 21 else None,
            "change_ytd_pct": round(float((last / ytd["close"].iloc[0] - 1) * 100), 2) if len(ytd) > 1 else None,
            "gap_pct": round(float((g["open"].iloc[-1] / prev - 1) * 100), 2),
            "move_z": round(float(abs(ret1 / 100) / vol60), 2) if vol60 and not np.isnan(vol60) else 0.0,
            "volume": float(v.iloc[-1]),
            "volume_ratio": round(float(v.iloc[-1] / avg_vol20), 2) if avg_vol20 else None,
            "high_52w": round(float(hi52), 2),
            "low_52w": round(float(lo52), 2),
            "pct_from_52w_high": round(float((last / hi52 - 1) * 100), 1),
            "rsi14": _rsi(c),
            "above_sma50": bool(last > c.iloc[-50:].mean()) if len(c) >= 50 else None,
            "above_sma200": bool(last > c.iloc[-200:].mean()) if len(c) >= 200 else None,
        }
    return out


def spark(prices: pd.DataFrame, symbol: str, as_of: date, n: int = 30) -> list[float]:
    g = prices[(prices["symbol"] == symbol) & (prices["date"] <= as_of)].sort_values("date")
    return [round(float(x), 4) for x in g["close"].iloc[-n:]]


def candles(prices: pd.DataFrame, symbol: str, as_of: date, n: int = 60) -> list[dict]:
    g = prices[(prices["symbol"] == symbol) & (prices["date"] <= as_of)].sort_values("date").iloc[-n:]
    return [{"date": d.isoformat(), "open": round(float(o), 4), "high": round(float(h), 4), "low": round(float(lo), 4),
             "close": round(float(cl), 4), "volume": float(vol)}
            for d, o, h, lo, cl, vol in zip(g["date"], g["open"], g["high"], g["low"], g["close"], g["volume"])]
