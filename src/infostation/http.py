"""Shared HTTP client: retries, per-host throttling, SEC-compliant User-Agent, small disk cache."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import CACHE_DIR

log = logging.getLogger(__name__)

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)

# Minimum seconds between requests to the same host. SEC allows 10 req/s; stay well under.
HOST_MIN_INTERVAL = {
    "www.sec.gov": 0.15,
    "data.sec.gov": 0.15,
    "api.stocktwits.com": 1.0,
    "news.google.com": 0.8,
    "api.nasdaq.com": 0.5,
    "apewisdom.io": 0.5,
    "api.coingecko.com": 1.5,
    "finnhub.io": 1.1,
}


class SourceError(RuntimeError):
    """A data source failed in a way the caller should degrade around."""


class Http:
    def __init__(self, sec_user_agent: str):
        self.sec_user_agent = sec_user_agent
        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=16)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def _throttle(self, host: str) -> None:
        interval = HOST_MIN_INTERVAL.get(host, 0.0)
        if not interval:
            return
        with self._lock:
            wait = self._last.get(host, 0.0) + interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()

    def get(self, url: str, *, params: dict | None = None, headers: dict | None = None,
            timeout: float = 20, cache_ttl: float = 0) -> requests.Response | _CachedResponse:
        host = urlparse(url).netloc
        if cache_ttl:
            cached = _cache_read(url, params, cache_ttl)
            if cached is not None:
                return cached
        h = {"User-Agent": self.sec_user_agent if host.endswith("sec.gov") else BROWSER_UA,
             "Accept": "application/json, application/xml, text/xml, */*"}
        if host.endswith("sec.gov"):
            h["Accept-Encoding"] = "gzip, deflate"
        if headers:
            h.update(headers)
        self._throttle(host)
        try:
            resp = self.session.get(url, params=params, headers=h, timeout=timeout)
        except requests.RequestException as e:
            raise SourceError(f"{host}: {e}") from e
        if resp.status_code >= 400:
            raise SourceError(f"{host}: HTTP {resp.status_code} for {resp.url[:120]}")
        if cache_ttl:
            _cache_write(url, params, resp.content)
        return resp

    def json(self, url: str, **kw: Any) -> Any:
        resp = self.get(url, **kw)
        try:
            return resp.json()
        except ValueError as e:
            raise SourceError(f"non-JSON response from {url[:120]}") from e


class _CachedResponse:
    status_code = 200

    def __init__(self, content: bytes):
        self.content = content
        self.text = content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content)


def _cache_path(url: str, params: dict | None) -> Path:
    key = hashlib.sha1((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
    return CACHE_DIR / "http" / key[:2] / key


def _cache_read(url: str, params: dict | None, ttl: float) -> _CachedResponse | None:
    p = _cache_path(url, params)
    if p.exists() and time.time() - p.stat().st_mtime < ttl:
        return _CachedResponse(p.read_bytes())
    return None


def _cache_write(url: str, params: dict | None, content: bytes) -> None:
    p = _cache_path(url, params)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
