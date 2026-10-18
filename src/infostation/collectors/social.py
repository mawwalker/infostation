"""Retail attention: ApeWisdom (Reddit/4chan mention counts), Stocktwits streams, optional Reddit OAuth."""
from __future__ import annotations

import html
import logging
import re
from datetime import date

import pandas as pd

from ..http import Http, SourceError
from .. import store

log = logging.getLogger(__name__)


def apewisdom(http: Http, as_of: date, pages: int = 2, filter_: str = "all-stocks") -> list[dict]:
    rows: list[dict] = []
    for page in range(1, pages + 1):
        try:
            d = http.json(f"https://apewisdom.io/api/v1.0/filter/{filter_}/page/{page}")
        except SourceError as e:
            log.warning("apewisdom page %d failed: %s", page, e)
            break
        for r in d.get("results", []):
            rows.append({
                "symbol": r["ticker"].upper(), "name": html.unescape(r.get("name", "")),
                "rank": int(r["rank"]), "mentions": int(r.get("mentions") or 0), "upvotes": int(r.get("upvotes") or 0),
                "rank_24h_ago": int(r["rank_24h_ago"]) if r.get("rank_24h_ago") else None,
                "mentions_24h_ago": int(r["mentions_24h_ago"]) if r.get("mentions_24h_ago") else None,
            })
        if page >= int(d.get("pages", 1)):
            break
    if rows and filter_ == "all-stocks":
        df = pd.DataFrame(rows).drop(columns=["name"])
        df.insert(0, "source", "apewisdom")
        df.insert(2, "date", as_of)
        store.upsert("social_mentions", df.drop_duplicates(["symbol"]))
    return rows


def stocktwits(http: Http, symbols: list[str], as_of: date) -> dict[str, dict]:
    """Last ~30 messages per symbol: self-tagged bull/bear counts + most-liked message bodies."""
    out: dict[str, dict] = {}
    for sym in symbols:
        try:
            d = http.json(f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json")
        except SourceError as e:
            log.info("stocktwits %s failed: %s", sym, e)
            continue
        msgs = d.get("messages", [])
        bull = bear = 0
        texts = []
        for m in msgs:
            s = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
            bull += s == "Bullish"
            bear += s == "Bearish"
            body = _clean(m.get("body", ""))
            if len(body) > 25:
                texts.append({"text": body[:280], "likes": (m.get("likes") or {}).get("total", 0), "tag": s})
        texts.sort(key=lambda t: t["likes"], reverse=True)
        sym_info = d.get("symbol") or {}
        out[sym] = {"bullish": bull, "bearish": bear, "messages": len(msgs), "top_messages": texts[:12],
                    "watchlist_count": sym_info.get("watchlist_count")}
    if out:
        store.upsert("stocktwits_daily", pd.DataFrame([
            {"symbol": s, "date": as_of, "bullish": v["bullish"], "bearish": v["bearish"], "messages": v["messages"]}
            for s, v in out.items()]))
    return out


def reddit_posts(http: Http, client_id: str | None, client_secret: str | None, symbols: list[str],
                 subreddits: tuple[str, ...] = ("wallstreetbets", "stocks")) -> dict[str, list[dict]]:
    """Optional: needs a Reddit 'script' app. Anonymous .json access is blocked (HTTP 403)."""
    if not (client_id and client_secret):
        return {}
    try:
        tok = http.session.post("https://www.reddit.com/api/v1/access_token",
                                auth=(client_id, client_secret), data={"grant_type": "client_credentials"},
                                headers={"User-Agent": "infostation/0.1"}, timeout=15).json()["access_token"]
    except Exception as e:
        log.warning("reddit auth failed: %s", e)
        return {}
    out: dict[str, list[dict]] = {}
    hdr = {"Authorization": f"bearer {tok}", "User-Agent": "infostation/0.1"}
    for sym in symbols:
        posts = []
        for sub in subreddits:
            try:
                d = http.json(f"https://oauth.reddit.com/r/{sub}/search", headers=hdr,
                              params={"q": f"${sym} OR {sym}", "restrict_sr": 1, "sort": "top", "t": "day", "limit": 8})
            except SourceError:
                continue
            for c in d.get("data", {}).get("children", []):
                p = c["data"]
                posts.append({"title": p["title"][:200], "score": p.get("score", 0), "comments": p.get("num_comments", 0),
                              "sub": sub})
        out[sym] = sorted(posts, key=lambda p: p["score"], reverse=True)[:8]
    return out


def _clean(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"https?://\S+", "", text)
    return re.sub(r"\s+", " ", text).strip()
