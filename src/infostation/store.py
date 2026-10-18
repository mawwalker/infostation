"""DuckDB history store: every run appends here, so the station gets more valuable over time."""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

import duckdb
import pandas as pd

from .config import DATA_DIR

DB_PATH = DATA_DIR / "market_memory.duckdb"

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices_daily (
    symbol VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE,
    PRIMARY KEY (symbol, date));
CREATE TABLE IF NOT EXISTS social_mentions (
    source VARCHAR, symbol VARCHAR, date DATE, rank INTEGER, mentions INTEGER, upvotes INTEGER,
    rank_24h_ago INTEGER, mentions_24h_ago INTEGER, PRIMARY KEY (source, symbol, date));
CREATE TABLE IF NOT EXISTS stocktwits_daily (
    symbol VARCHAR, date DATE, bullish INTEGER, bearish INTEGER, messages INTEGER,
    PRIMARY KEY (symbol, date));
CREATE TABLE IF NOT EXISTS sentiment_scores (
    symbol VARCHAR, date DATE, score INTEGER, bull_point VARCHAR, bear_point VARCHAR,
    PRIMARY KEY (symbol, date));
CREATE TABLE IF NOT EXISTS filings (
    accession VARCHAR PRIMARY KEY, symbol VARCHAR, cik BIGINT, form VARCHAR, filed DATE,
    items VARCHAR, url VARCHAR);
CREATE TABLE IF NOT EXISTS insider_tx (
    accession VARCHAR, idx INTEGER, symbol VARCHAR, owner VARCHAR, title VARCHAR, code VARCHAR,
    shares DOUBLE, price DOUBLE, value DOUBLE, tx_date DATE, planned BOOLEAN,
    PRIMARY KEY (accession, idx));
CREATE TABLE IF NOT EXISTS crypto_daily (
    symbol VARCHAR, date DATE, price DOUBLE, change_pct DOUBLE, quote_volume DOUBLE, funding_rate DOUBLE,
    PRIMARY KEY (symbol, date));
CREATE TABLE IF NOT EXISTS runs (
    run_id VARCHAR PRIMARY KEY, session VARCHAR, target_date DATE, status VARCHAR,
    stories VARCHAR, started TIMESTAMP, finished TIMESTAMP, notes VARCHAR);
"""


@contextmanager
def connect() -> Iterator[duckdb.DuckDBPyConnection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    try:
        con.execute(SCHEMA)
        yield con
    finally:
        con.close()


def upsert(table: str, df: pd.DataFrame) -> int:
    """INSERT OR REPLACE a dataframe whose columns match the table."""
    if df is None or df.empty:
        return 0
    with connect() as con:
        con.register("_incoming", df)
        cols = ", ".join(df.columns)
        con.execute(f"INSERT OR REPLACE INTO {table} ({cols}) SELECT {cols} FROM _incoming")
        con.unregister("_incoming")
    return len(df)


def query(sql: str, params: list[Any] | None = None) -> pd.DataFrame:
    with connect() as con:
        return con.execute(sql, params or []).df()


def record_run(run_id: str, session: str, target_date: str, status: str, stories: list[str],
               started: str, finished: str | None, notes: dict | None = None) -> None:
    upsert("runs", pd.DataFrame([{
        "run_id": run_id, "session": session, "target_date": target_date, "status": status,
        "stories": ",".join(stories), "started": started, "finished": finished,
        "notes": json.dumps(notes or {}, ensure_ascii=False),
    }]))


def recently_featured(before_date: str, days: int) -> set[str]:
    df = query(
        "SELECT stories FROM runs WHERE status = 'done' AND target_date < ? "
        "AND target_date >= CAST(? AS DATE) - INTERVAL (?) DAY",
        [before_date, before_date, days],
    )
    out: set[str] = set()
    for s in df.get("stories", []):
        out.update(x for x in (s or "").split(",") if x)
    return out
