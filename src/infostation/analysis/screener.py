"""Funnel layer 1→2: score the whole universe and keep the most newsworthy candidates."""
from __future__ import annotations

import math


def score_universe(metrics: dict[str, dict], social: dict[str, dict], earnings_syms: set[str],
                   caps: dict[str, float], min_cap: float, cooldown: set[str],
                   exclude: set[str], watchlist: set[str] | None = None) -> list[dict]:
    watchlist = watchlist or set()
    rows = []
    for sym, m in metrics.items():
        if sym in exclude:
            continue
        cap = caps.get(sym, 0.0)
        if cap and cap < min_cap:
            continue
        reasons = []
        z = min(m["move_z"], 6.0)
        s = 1.0 * z
        if abs(m["change_pct"]) >= 5:
            reasons.append(f"big move {m['change_pct']:+.1f}%")
        vr = m.get("volume_ratio") or 1.0
        s += 1.2 * min(math.log2(max(vr, 0.5)), 2.0)
        if vr >= 2:
            reasons.append(f"volume {vr:.1f}x 20d avg")
        soc = social.get(sym)
        if soc:
            growth = (soc["mentions"] + 5) / ((soc.get("mentions_24h_ago") or 0) + 5)
            s += 0.8 * math.log2(max(growth, 0.5)) + (0.8 if soc["rank"] <= 10 else 0.0)
            if growth >= 2:
                reasons.append(f"retail mentions {growth:.1f}x vs 24h ago")
            if soc["rank"] <= 10:
                reasons.append(f"#{soc['rank']} on retail chatter board")
        if sym in earnings_syms:
            s += 1.5
            reasons.append("reported earnings")
        if m.get("pct_from_52w_high", -100) >= -0.5:
            s += 0.5
            reasons.append("at 52-week high")
        # Audience relevance: viewers care more about names they own or follow.
        if cap >= 2e11:
            s += 1.2
        elif cap >= 5e10:
            s += 0.6
        if sym in watchlist:
            s += 0.8
        if sym in cooldown and z < 4:
            s -= 2.0
            reasons.append("featured recently (penalized)")
        rows.append({"symbol": sym, "score": round(s, 2), "reasons": reasons, "market_cap": cap})
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def movers(metrics: dict[str, dict], caps: dict[str, float], min_cap: float, exclude: set[str], n: int = 6) -> dict:
    eligible = [(s, m) for s, m in metrics.items()
                if s not in exclude and (caps.get(s, 0.0) == 0.0 or caps[s] >= min_cap)]
    eligible.sort(key=lambda x: x[1]["change_pct"], reverse=True)

    def row(s: str, m: dict) -> dict:
        return {"symbol": s, "change_pct": m["change_pct"], "close": m["close"], "volume_ratio": m.get("volume_ratio")}

    return {"gainers": [row(s, m) for s, m in eligible[:n]],
            "losers": [row(s, m) for s, m in reversed(eligible[-n:])]}
