"""SEC EDGAR: recent 8-K / Form 4 / periodic filings per ticker, with Form 4 transaction parsing.

Free, official, no key. SEC requires a User-Agent with a contact email and <=10 req/s.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import pandas as pd

from ..http import Http, SourceError
from .. import store

log = logging.getLogger(__name__)

ITEMS_8K = {
    "1.01": "material agreement", "1.02": "agreement terminated", "1.03": "bankruptcy",
    "1.05": "cybersecurity incident", "2.01": "acquisition/disposition completed", "2.02": "earnings results",
    "2.03": "new debt obligation", "2.05": "restructuring/layoffs", "2.06": "impairment",
    "3.01": "delisting notice", "3.02": "unregistered equity sale", "4.01": "auditor change",
    "4.02": "prior financials unreliable", "5.01": "change in control", "5.02": "executive/director change",
    "5.03": "bylaws amendment", "5.07": "shareholder vote", "7.01": "Reg FD disclosure",
    "8.01": "other material event", "9.01": "financial exhibits",
}
INTERESTING_FORMS = {"8-K", "8-K/A", "4", "10-Q", "10-K", "S-1", "S-3", "424B5", "SC 13D", "SC 13G", "SCHEDULE 13D", "SCHEDULE 13G", "6-K"}
TX_CODES = {"P": "open-market buy", "S": "open-market sell", "M": "option exercise", "F": "tax withholding",
            "A": "grant/award", "G": "gift", "D": "disposition to issuer", "C": "conversion", "X": "option exercise"}

_ticker_map: dict[str, int] | None = None


def ticker_to_cik(http: Http) -> dict[str, int]:
    global _ticker_map
    if _ticker_map is None:
        data = http.json("https://www.sec.gov/files/company_tickers.json", cache_ttl=7 * 86400)
        _ticker_map = {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}
    return _ticker_map


def collect(http: Http, symbols: list[str], as_of: date, lookback_days: int) -> dict[str, dict]:
    """Return {symbol: {"filings": [...], "insider": {...}}} for filings within the lookback window."""
    try:
        cmap = ticker_to_cik(http)
    except SourceError as e:
        log.error("SEC ticker map unavailable: %s", e)
        return {}
    since = as_of - timedelta(days=lookback_days)
    out: dict[str, dict] = {}
    filing_rows, tx_rows = [], []
    for sym in symbols:
        cik = cmap.get(sym.upper().replace(".", "-")) or cmap.get(sym.upper())
        if not cik:
            continue
        try:
            sub = http.json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        except SourceError as e:
            log.warning("SEC submissions %s failed: %s", sym, e)
            continue
        recent = sub.get("filings", {}).get("recent", {})
        filings = []
        for i, form in enumerate(recent.get("form", [])):
            filed = date.fromisoformat(recent["filingDate"][i])
            if filed < since:
                break
            if form not in INTERESTING_FORMS:
                continue
            acc = recent["accessionNumber"][i]
            doc = recent["primaryDocument"][i]
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"
            items = recent.get("items", [""] * (i + 1))[i] or ""
            f = {"form": form, "filed": filed.isoformat(), "accession": acc, "url": url,
                 "items": [f"{it} {ITEMS_8K.get(it, '')}".strip() for it in items.split(",") if it]}
            filings.append(f)
            filing_rows.append({"accession": acc, "symbol": sym, "cik": cik, "form": form, "filed": filed,
                                "items": items, "url": url})
        form4 = [f for f in filings if f["form"] == "4"][:15]
        txs = []
        for f in form4:
            try:
                txs.extend(_parse_form4(http, cik, f["accession"], f["url"]))
            except SourceError as e:
                log.debug("form4 parse failed %s: %s", f["url"], e)
        for idx, t in enumerate(txs):
            tx_rows.append({"accession": t["accession"], "idx": idx, "symbol": sym, "owner": t["owner"],
                            "title": t["title"], "code": t["code"], "shares": t["shares"], "price": t["price"],
                            "value": t["value"], "tx_date": t["date"], "planned": t["planned"]})
        out[sym] = {"filings": [f for f in filings if f["form"] != "4"], "insider": _summarize_insider(txs)}

    store.upsert("filings", pd.DataFrame(filing_rows))
    if tx_rows:
        store.upsert("insider_tx", pd.DataFrame(tx_rows).drop_duplicates(["accession", "idx"]))
    return out


def _parse_form4(http: Http, cik: int, accession: str, url: str) -> list[dict]:
    # primaryDocument is the XSL-rendered path (xslF345X05/foo.xml); the raw XML sits one level up.
    parts = url.split("/")
    if parts[-2].startswith("xsl"):
        url = "/".join(parts[:-2] + parts[-1:])
    resp = http.get(url, cache_ttl=30 * 86400)
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        raise SourceError(f"bad form4 xml {url}") from e
    owner = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName", "").strip()
    rel = root.find(".//reportingOwner/reportingOwnerRelationship")
    title = ""
    if rel is not None:
        title = rel.findtext("officerTitle", "") or ("Director" if rel.findtext("isDirector") in ("1", "true") else "")
        if not title and rel.findtext("isTenPercentOwner") in ("1", "true"):
            title = "10% owner"
    planned = root.findtext(".//aff10b5One", "").strip() in ("1", "true")
    txs = []
    for tx in root.findall(".//nonDerivativeTable/nonDerivativeTransaction"):
        code = tx.findtext("transactionCoding/transactionCode", "").strip()
        try:
            shares = float(tx.findtext("transactionAmounts/transactionShares/value", "0") or 0)
            price = float(tx.findtext("transactionAmounts/transactionPricePerShare/value", "0") or 0)
        except ValueError:
            continue
        ad = tx.findtext("transactionAmounts/transactionAcquiredDisposedCode/value", "").strip()
        txs.append({"accession": accession, "owner": owner, "title": title.strip(), "code": code,
                    "shares": shares if ad == "A" else -shares, "price": price,
                    "value": shares * price * (1 if ad == "A" else -1),
                    "date": tx.findtext("transactionDate/value", "")[:10] or None, "planned": planned})
    return txs


def _summarize_insider(txs: list[dict]) -> dict:
    buys = [t for t in txs if t["code"] == "P"]
    sells = [t for t in txs if t["code"] == "S"]
    top = sorted(buys + sells, key=lambda t: abs(t["value"]), reverse=True)[:5]
    return {
        "open_market_buy_usd": round(sum(t["value"] for t in buys)),
        "open_market_sell_usd": round(-sum(t["value"] for t in sells)),
        "planned_sell_share": round(sum(1 for t in sells if t["planned"]) / len(sells), 2) if sells else None,
        "notable": [{"owner": t["owner"], "title": t["title"], "action": TX_CODES.get(t["code"], t["code"]),
                     "value_usd": round(abs(t["value"])), "price": t["price"], "date": t["date"],
                     "10b5-1_plan": t["planned"]} for t in top],
    }
