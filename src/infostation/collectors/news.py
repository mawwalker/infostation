"""Headlines: Google News RSS per ticker, a handful of market-wide feeds, optional Finnhub company news."""
from __future__ import annotations

import calendar
import logging
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser

from ..http import Http, SourceError

log = logging.getLogger(__name__)

# Quote pages, price-prediction SEO and listicles that Google News mixes into ticker searches.
_JUNK = re.compile(r"stock (quote|price|forecast)|price (today|prediction|forecast|target \d{4})|quote & news|"
                   r"stock chart|historical prices|should you buy|top \d+ stocks|\bvs\.? .* which", re.I)


def _parse_feed(http: Http, url: str) -> list[dict]:
    resp = http.get(url, timeout=20)
    feed = feedparser.parse(resp.content)
    items = []
    for e in feed.entries:
        published = None
        if getattr(e, "published_parsed", None):
            published = datetime.fromtimestamp(calendar.timegm(e.published_parsed), tz=timezone.utc)
        source = getattr(getattr(e, "source", None), "title", None) or feed.feed.get("title", "")
        title = e.get("title", "").strip()
        # Google News appends " - Publisher" to every title
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        items.append({"title": title, "source": source, "url": e.get("link", ""),
                      "published": published.isoformat() if published else None,
                      "summary": _strip_html(e.get("summary", ""))[:300]})
    return items


def ticker_news(http: Http, symbol: str, company: str, per_ticker: int, since: datetime) -> list[dict]:
    name = company.replace(",", "").replace(" Inc.", "").replace(" Corporation", "").strip()
    q = f'"{name}" OR "{symbol} stock" when:2d'
    url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en"
    try:
        items = _parse_feed(http, url)
    except SourceError as e:
        log.warning("google news %s failed: %s", symbol, e)
        return []
    items = [i for i in items if not i["published"] or datetime.fromisoformat(i["published"]) >= since]
    seen, out = set(), []
    for i in items:
        if _JUNK.search(i["title"]):
            continue
        key = i["title"].lower()[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append(i)
    return out[:per_ticker]


def market_news(http: Http, feeds: list[str], since: datetime, limit: int = 40) -> list[dict]:
    items: list[dict] = []
    for url in feeds:
        try:
            items.extend(_parse_feed(http, url))
        except SourceError as e:
            log.warning("feed failed %s: %s", url, e)
    items = [i for i in items if i["published"] and datetime.fromisoformat(i["published"]) >= since]
    items.sort(key=lambda i: i["published"], reverse=True)
    return items[:limit]


def finnhub_news(http: Http, api_key: str | None, symbol: str, as_of: date) -> list[dict]:
    if not api_key:
        return []
    try:
        data = http.json("https://finnhub.io/api/v1/company-news",
                         params={"symbol": symbol, "from": (as_of - timedelta(days=2)).isoformat(),
                                 "to": as_of.isoformat(), "token": api_key})
    except SourceError as e:
        log.info("finnhub news %s failed: %s", symbol, e)
        return []
    return [{"title": d.get("headline", ""), "source": d.get("source", ""), "url": d.get("url", ""),
             "published": datetime.fromtimestamp(d["datetime"], tz=timezone.utc).isoformat() if d.get("datetime") else None,
             "summary": (d.get("summary") or "")[:300]} for d in data[:8]]


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s).replace("&nbsp;", " ").strip()
