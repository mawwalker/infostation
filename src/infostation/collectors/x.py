"""X (Twitter) posts: an agent-supplied JSON file, plus an optional API v2 recent-search.

No bearer token and no file is a skip, not a failure. The caller decides whether grokbot mode
should stop and wait for the file. Tweet text is context for the writer; fact-check ignores it.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema

from ..config import ROOT
from ..http import Http, SourceError

log = logging.getLogger(__name__)

_CASHTAG = re.compile(r"\$([A-Za-z]{1,5}(?:\.[A-Za-z])?)\b")
DEFAULT_ACCOUNTS = ["DeItaone", "FirstSquawk"]
API_URL = "https://api.x.com/2/tweets/search/recent"

X_POSTS_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["posts"],
    "properties": {
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": True,
                "required": ["id", "url", "author", "created_at", "text"],
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "url": {"type": "string", "minLength": 1},
                    "author": {
                        "type": "object",
                        "additionalProperties": True,
                        "required": ["handle"],
                        "properties": {
                            "handle": {"type": "string", "minLength": 1},
                            "name": {"type": "string"},
                            "followers": {"type": ["integer", "null"]},
                        },
                    },
                    "created_at": {"type": "string", "minLength": 1},
                    "text": {"type": "string", "minLength": 1},
                    "metrics": {
                        "type": "object",
                        "additionalProperties": True,
                        "properties": {
                            "likes": {"type": ["integer", "null"]},
                            "reposts": {"type": ["integer", "null"]},
                            "replies": {"type": ["integer", "null"]},
                            "quotes": {"type": ["integer", "null"]},
                            "impressions": {"type": ["integer", "null"]},
                        },
                    },
                    "matched": {
                        "type": "object",
                        "additionalProperties": True,
                        "properties": {
                            "ticker": {"type": ["string", "null"]},
                            "cashtag": {"type": ["string", "null"]},
                            "topic": {"type": ["string", "null"]},
                        },
                    },
                },
            },
        },
    },
}


class XInputError(ValueError):
    """The agent file is present but not usable. The message lists every problem."""


def cashtag(symbol: str) -> str | None:
    """$NVDA, $BRK.B. Futures and index symbols (ES=F, ^GSPC) are not cashtags."""
    s = symbol.upper().replace("-", ".")
    if re.fullmatch(r"[A-Z]{1,5}(?:\.[A-Z])?", s):
        return f"${s}"
    return None


def dedupe_tickers(symbols: list[str], limit: int = 80) -> list[str]:
    out, seen = [], set()
    for raw in symbols:
        sym = str(raw).upper().strip()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
        if len(out) >= limit:
            break
    return out


def schema_errors(instance: object, schema: dict, limit: int = 20) -> list[str]:
    validator = jsonschema.Draft202012Validator(schema)
    out = []
    for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path)):
        loc = "/".join(str(p) for p in err.absolute_path) or "(root)"
        out.append(f"{loc}: {err.message}")
        if len(out) >= limit:
            break
    return out


def parse_x_posts(raw: object) -> dict:
    """Accept `{"posts": [...]}` or a bare list. Coerce a few agent-shaped variants, then validate."""
    if isinstance(raw, list):
        raw = {"posts": raw}
    if not isinstance(raw, dict):
        raise XInputError("x_posts must be a JSON object {\"posts\": [...]} or an array of posts, "
                          f"got {type(raw).__name__}.")
    posts = raw.get("posts")
    if not isinstance(posts, list):
        raise XInputError("(root): 'posts' is required and must be an array. "
                          "Example: {\"posts\": [{\"id\": \"1\", \"url\": \"https://x.com/u/status/1\", "
                          "\"author\": {\"handle\": \"name\"}, \"created_at\": \"2026-10-21T12:00:00Z\", "
                          "\"text\": \"...\", \"matched\": {\"ticker\": \"NVDA\"}}]}")
    cleaned = []
    for i, post in enumerate(posts):
        if not isinstance(post, dict):
            raise XInputError(f"posts/{i}: must be an object, got {type(post).__name__}.")
        item = dict(post)
        if isinstance(item.get("id"), int):
            item["id"] = str(item["id"])
        author = item.get("author")
        if isinstance(author, str):
            item["author"] = {"handle": author.lstrip("@")}
        elif isinstance(author, dict) and isinstance(author.get("handle"), str):
            author = dict(author)
            author["handle"] = author["handle"].lstrip("@")
            item["author"] = author
        cleaned.append(item)
    errors = schema_errors({"posts": cleaned}, X_POSTS_SCHEMA)
    if errors:
        raise XInputError("x_posts.json failed schema validation:\n" + "\n".join(f"- {e}" for e in errors))
    return {"posts": [normalize_post(p) for p in cleaned]}


def load_x_posts(path: Path) -> list[dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise XInputError(f"{path} is not valid JSON ({e}). Write one JSON object, not markdown.") from e
    except OSError as e:
        raise XInputError(f"could not read {path}: {e}") from e
    return parse_x_posts(raw)["posts"]


def _as_symbol(token: str) -> str:
    """Pipeline ticker: NVDA, BRK-B. Cashtags use a dot ($BRK.B); the watchlist uses a hyphen."""
    return token.upper().replace("$", "").replace(".", "-").strip()


def normalize_post(post: dict, allowed: set[str] | None = None) -> dict:
    matched = dict(post.get("matched") or {})
    ticker = _as_symbol(matched.get("ticker") or "") or None
    if not ticker:
        tag = matched.get("cashtag") or ""
        m = _CASHTAG.search(tag if str(tag).startswith("$") else f"${tag}") if tag else None
        ticker = _as_symbol(m.group(1)) if m else None
    if not ticker:
        found = [_as_symbol(m.group(1)) for m in _CASHTAG.finditer(post.get("text") or "")]
        if allowed:
            allowed_norm = {_as_symbol(a) for a in allowed}
            found = [t for t in found if t in allowed_norm]
        ticker = found[0] if found else None
    matched["ticker"] = ticker
    matched["cashtag"] = cashtag(ticker) if ticker else matched.get("cashtag")
    text = " ".join((post.get("text") or "").split())
    return {
        "id": str(post["id"]),
        "url": post["url"],
        "author": {
            "handle": (post.get("author") or {}).get("handle", "").lstrip("@"),
            "name": (post.get("author") or {}).get("name") or (post.get("author") or {}).get("handle", ""),
            "followers": (post.get("author") or {}).get("followers"),
        },
        "created_at": post.get("created_at") or "",
        "text": text[:2000],
        "metrics": post.get("metrics") or {},
        "matched": matched,
    }


def posts_for_prompt(posts: list[dict], limit: int = 20) -> list[dict]:
    """Short, quotable slice for the writer. Likes and follower counts stay in the object but are not facts."""

    def engagement(p: dict) -> int:
        m = p.get("metrics") or {}
        return sum(int(m.get(k) or 0) for k in ("likes", "reposts", "replies", "quotes"))

    ranked = sorted(posts, key=engagement, reverse=True)[:limit]
    out = []
    for p in ranked:
        item = dict(p)
        item["text"] = (p.get("text") or "")[:500]
        out.append(item)
    return out


def buzz_by_ticker(posts: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in posts:
        ticker = (p.get("matched") or {}).get("ticker")
        if not ticker:
            continue
        row = out.setdefault(ticker, {"posts": 0, "engagement": 0})
        row["posts"] += 1
        m = p.get("metrics") or {}
        row["engagement"] += sum(int(m.get(k) or 0) for k in ("likes", "reposts", "replies", "quotes"))
    return out


def find_x_posts_file(run_dir: Path, inbox: str | None, run_id: str) -> Path | None:
    """Per-run file wins. Inbox is optional: `<inbox>/<run_id>.json`, then `<inbox>/x_posts.json`."""
    local = run_dir / "inputs" / "x_posts.json"
    if local.exists():
        return local
    if not inbox:
        return None
    root = Path(inbox)
    if not root.is_absolute():
        root = ROOT / root
    for name in (f"{run_id}.json", "x_posts.json"):
        path = root / name
        if path.exists():
            return path
    return None


def merge_posts(*groups: list[dict], limit: int) -> list[dict]:
    by_id: dict[str, dict] = {}
    for group in groups:
        for post in group:
            by_id.setdefault(post["id"], post)
    posts = sorted(by_id.values(), key=lambda p: p.get("created_at") or "", reverse=True)
    return posts[:limit]


def build_x_request(*, run_id: str, session: str, tickers: list[str], accounts: list[str], topics: list[str],
                    start: datetime, end: datetime, output_path: Path) -> dict:
    tags = [tag for sym in tickers if (tag := cashtag(sym))]
    handles = []
    for account in accounts:
        handle = account if str(account).startswith("@") else f"@{account}"
        if handle not in handles:
            handles.append(handle)
    return {
        "kind": "x_request",
        "name": "x_request",
        "run_id": run_id,
        "session": session,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "time_window": {
            "start": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
            "description": "Keep posts whose created_at falls in this window. Times are ISO 8601.",
        },
        "cashtags": tags,
        "tickers": tickers,
        "accounts": handles,
        "topics": topics,
        "instructions": (
            "Search X for these cashtags and accounts inside the time window (post search, timelines, news). "
            "Keep posts that are about the tickers or today's session. "
            f"Write a JSON object matching `schema` to {output_path}. "
            "An empty posts array is valid when nothing relevant turned up. Do not invent posts. "
            "Set matched.ticker to the cashtag you searched (NVDA, not $NVDA). "
            "Numbers inside posts are quotable context only — market figures stay in the data pack."
        ),
        "output_file": str(output_path),
        "schema": X_POSTS_SCHEMA,
    }


def _rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _queries(tickers: list[str], accounts: list[str], width: int = 450) -> list[str]:
    groups: list[list[str]] = []
    cur: list[str] = []
    for sym in tickers:
        tag = cashtag(sym)
        if not tag:
            continue
        trial = " OR ".join(cur + [tag])
        if cur and len(trial) > width:
            groups.append(cur)
            cur = [tag]
        else:
            cur.append(tag)
    if cur:
        groups.append(cur)
    queries = ["(" + " OR ".join(g) + ") -is:retweet" for g in groups[:3]]
    handles = [a.lstrip("@") for a in accounts if a][:6]
    if handles:
        queries.append("(" + " OR ".join(f"from:{h}" for h in handles) + ") -is:retweet")
    return queries


def search_recent(http: Http, token: str, tickers: list[str], accounts: list[str], start: datetime,
                  end: datetime, max_posts: int) -> list[dict]:
    """Recent-search. Raises SourceError on HTTP failure. Empty result is an empty list."""
    now = datetime.now(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    if end_utc > now - timedelta(seconds=20):
        end_utc = now - timedelta(seconds=20)
    start_utc = start.astimezone(timezone.utc)
    if start_utc >= end_utc:
        start_utc = end_utc - timedelta(hours=12)
    allowed = {t.upper().replace("-", ".") for t in tickers}
    allowed |= {t.replace(".", "-") for t in allowed}
    found: list[dict] = []
    headers = {"Authorization": f"Bearer {token}"}
    for query in _queries(tickers, accounts):
        if len(found) >= max_posts:
            break
        params = {
            "query": query,
            "max_results": min(100, max(10, max_posts)),
            "start_time": _rfc3339(start_utc),
            "end_time": _rfc3339(end_utc),
            "tweet.fields": "created_at,public_metrics,author_id,lang",
            "expansions": "author_id",
            "user.fields": "username,name,public_metrics",
        }
        data = http.json(API_URL, params=params, headers=headers, timeout=20)
        if data.get("errors") and not data.get("data"):
            raise SourceError(f"api.x.com: {data['errors'][0].get('message', data['errors'][0])}")
        users = {u["id"]: u for u in (data.get("includes") or {}).get("users") or []}
        for tweet in data.get("data") or []:
            found.append(_from_api(tweet, users, allowed))
    return merge_posts(found, limit=max_posts)


def _from_api(tweet: dict, users: dict, allowed: set[str]) -> dict:
    author = users.get(tweet.get("author_id"), {})
    metrics = tweet.get("public_metrics") or {}
    handle = author.get("username") or "unknown"
    tid = str(tweet["id"])
    text = tweet.get("text") or ""
    post = {
        "id": tid,
        "url": f"https://x.com/{handle}/status/{tid}",
        "author": {
            "handle": handle,
            "name": author.get("name") or handle,
            "followers": (author.get("public_metrics") or {}).get("followers_count"),
        },
        "created_at": tweet.get("created_at") or "",
        "text": text,
        "metrics": {
            "likes": metrics.get("like_count"),
            "reposts": metrics.get("retweet_count"),
            "replies": metrics.get("reply_count"),
            "quotes": metrics.get("quote_count"),
            "impressions": metrics.get("impression_count"),
        },
        "matched": {},
    }
    return normalize_post(post, allowed=allowed)
