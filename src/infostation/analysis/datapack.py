"""Assemble the views handed to the LLM and to the renderer.

- llm_view:    compact research pack for the editor (all candidates)
- writer_view: the editor's picks in full detail + market context (the fact-check reference)
- render data: writer_view plus chart series (candles, sparklines) for Remotion
"""
from __future__ import annotations

import pandas as pd

from . import metrics as M


def _round_cap(cap: float | None) -> float | None:
    return round(cap / 1e9, 1) if cap else None


def market_rows(board_cfg: list[dict], met: dict[str, dict], prices: pd.DataFrame, as_of) -> list[dict]:
    rows = []
    for b in board_cfg:
        m = met.get(b["symbol"])
        if not m:
            continue
        close = m["close"]
        if b.get("unit") == "yield":
            close = round(close, 3)     # ^TNX is quoted in percent
        rows.append({"symbol": b["symbol"], "name_zh": b["name_zh"], "name_en": b["name_en"], "close": round(close, 2),
                     "change_pct": m["change_pct"], "change_5d_pct": m.get("change_5d_pct"),
                     "change_ytd_pct": m.get("change_ytd_pct"), "unit": b.get("unit", "price"),
                     "spark": M.spark(prices, b["symbol"], as_of, 30)})
    return rows


def candidate_view(sym: str, name: str, row: dict, m: dict, ape: dict | None, st: dict | None,
                   heads: list[dict], sec: dict | None, reported: bool,
                   x_posts: list[dict] | None = None, x_buzz: dict | None = None) -> dict:
    return {
        "symbol": sym, "name": name, "score": row["score"], "reasons": row["reasons"],
        "metrics": {k: m.get(k) for k in ("close", "prev_close", "change_pct", "change_5d_pct", "change_1m_pct",
                                          "change_ytd_pct", "gap_pct", "volume_ratio", "pct_from_52w_high",
                                          "high_52w", "low_52w", "rsi14", "above_sma50", "above_sma200")}
                   | {"change_abs": round(m["close"] - m["prev_close"], 2), "market_cap_billion": _round_cap(row.get("market_cap"))},
        "apewisdom": {k: ape.get(k) for k in ("rank", "mentions", "mentions_24h_ago", "upvotes")} if ape else None,
        "stocktwits": {"bullish": st["bullish"], "bearish": st["bearish"], "messages": st["messages"],
                       "top_messages": [t["text"][:220] for t in st["top_messages"][:5]]} if st else None,
        "headlines": [{"title": h["title"], "source": h["source"], "published": (h.get("published") or "")[:16]}
                      for h in heads],
        "sec": sec or None,
        "earnings_reported": reported,
        "x_buzz": x_buzz,
        "x_posts": x_posts or [],
    }


def llm_view(base: dict, candidates: list[dict]) -> dict:
    return base | {"candidates": candidates}


def writer_view(base: dict, candidates: list[dict], editor: dict, options: dict[str, dict | None]) -> dict:
    by = {c["symbol"]: c for c in candidates}
    sent = {s["symbol"]: s for s in editor.get("sentiment", [])}
    stories = []
    for st in editor["stories"]:
        c = dict(by[st["symbol"]])
        c["stocktwits"] = dict(c["stocktwits"]) if c.get("stocktwits") else None
        s = sent.get(st["symbol"])
        c["retail_sentiment"] = {"score_0_100": s["score"], "bull_point": s["bull_point"], "bear_point": s["bear_point"]} if s else None
        c["options"] = options.get(st["symbol"])
        c["angle"] = st["angle"]
        stories.append(c)
    others = [{"symbol": c["symbol"], "name": c["name"], "change_pct": c["metrics"]["change_pct"],
               "reasons": c["reasons"]} for c in candidates if c["symbol"] not in {s["symbol"] for s in stories}]
    return base | {"stories": stories, "other_candidates": others[:8]}


def strip_series(view: dict) -> dict:
    """Remove chart series (sparklines) so the LLM prompt stays small."""
    out = dict(view)
    out["market"] = [{k: v for k, v in r.items() if k != "spark"} for r in view.get("market", [])]
    if "crypto" in view:
        out["crypto"] = {k: v for k, v in view["crypto"].items() if k != "btc_history"}
    return out
