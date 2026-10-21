"""Programmatic number check: every figure spoken in a script must be traceable to the data pack.

The LLM is told to only use numbers from DATA; this module verifies it. A spoken number passes if some
data value rounds to it (respecting the precision it was written with, and common unit scalings such as
billion / 亿 / 万亿). Dates, times, ordinals and small counts are ignored.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

_NUM = re.compile(r"(?<![A-Za-z0-9_.])(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)")
UNIT_SCALE = {
    "万亿": 1e12, "亿": 1e8, "万": 1e4, "千": 1e3,
    "trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3,
    "t": 1e12, "b": 1e9, "bn": 1e9, "m": 1e6, "k": 1e3,
}
_UNIT_RE = re.compile(r"^\s*(万亿|亿|万|千|trillion|billion|million|thousand|bn|t|b|m|k)(?![a-z0-9])", re.I)
_SKIP_TOKEN = re.compile(r"^(b5-1|-?k\b|-?q\b)", re.I)          # 10b5-1 plans, 10-K / 10-Q filings
_HEDGE = re.compile(r"(over|more than|nearly|almost|about|around|roughly|approximately|超过|超|逾|近|约|将近|大约|接近)\s*\$?\s*$", re.I)
_DATE_AFTER = re.compile(r"^\s*(年|月|日|号|点|时|分钟|秒|th\b|st\b|nd\b|rd\b|:\d)", re.I)
_DATE_BEFORE = re.compile(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*$|第\s*$|q\s*$|top\s*$|no\.\s*$", re.I)
_TECH_AFTER = re.compile(r"^\s*(-?\s*(日|天|周|个月|day|week|month|year)|日均线|天均线|-day|-week)", re.I)


@dataclass
class Issue:
    number: str
    context: str

    def __str__(self) -> str:
        return f"{self.number!r} in “…{self.context}…”"


# Social posts are quotable context. A figure that appears only inside them is not a market source.
SKIP_KEYS = {"x_posts", "x_buzz"}


def collect_values(data: object) -> list[float]:
    """All numeric values that appear in the data pack (numbers and digit runs inside strings)."""
    vals: list[float] = []

    def walk(x: object) -> None:
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            if math.isfinite(x):
                vals.append(float(x))
        elif isinstance(x, str):
            for m in _NUM.finditer(x):
                try:
                    v = float(m.group(1).replace(",", ""))
                except ValueError:
                    continue
                vals.append(v)
                um = _UNIT_RE.match(x[m.end():m.end() + 10])
                if um:
                    vals.append(v * UNIT_SCALE[um.group(1).lower()])
        elif isinstance(x, dict):
            for k, v in x.items():
                if str(k) in SKIP_KEYS:
                    continue
                walk(v)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and str(k).endswith("_billion"):
                    vals.append(float(v) * 1e9)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)

    walk(data)
    return vals


def _matches(spoken: float, decimals: int, scale: float, values: list[float], pct_context: bool,
             hedged: bool = False) -> bool:
    tol = 0.5 * 10 ** (-decimals) * scale * 1.0001
    target = spoken * scale
    if hedged:                                       # "over 13.1 million" for 13.17M is fine
        tol = max(tol, 0.03 * abs(target))
    for v in values:
        for cand in (v, abs(v)):
            if abs(cand - abs(target)) <= tol or abs(cand - target) <= tol:
                return True
            if pct_context and abs(cand * 100 - abs(target)) <= tol:   # ratio stored as fraction
                return True
            if abs(target) >= 1000 and cand and abs(cand - abs(target)) / abs(cand) < 0.005:
                return True
            unit = scale * 10 ** (-decimals)              # truncation instead of rounding: 4.126 → "4.12"
            if abs(math.trunc(abs(cand) / unit + 1e-9) * unit - abs(target)) <= unit * 1e-6:
                return True
    return False


def check_text(text: str, values: list[float]) -> list[Issue]:
    issues: list[Issue] = []
    for m in _NUM.finditer(text):
        raw = m.group(1)
        before, after = text[max(0, m.start() - 12):m.start()], text[m.end():m.end() + 12]
        if _DATE_AFTER.match(after) or _DATE_BEFORE.search(before) or _SKIP_TOKEN.match(text[m.end():m.end() + 5]):
            continue
        num = float(raw.replace(",", ""))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        if 1990 <= num <= 2100 and decimals == 0:
            continue                                # years
        if _TECH_AFTER.match(after) and num in (5, 10, 20, 50, 52, 100, 200):
            continue                                # "50-day average", "52周"
        pct = after.lstrip().startswith(("%", "％", "个百分点", "percent", "basis", "bp"))
        um = _UNIT_RE.match(after)
        scale = UNIT_SCALE[um.group(1).lower()] if um else 1.0
        if decimals == 0 and abs(num) <= 12 and not pct and not um and "$" not in before[-2:]:
            continue                                # small counts: "3 stocks", "两周内第2次"
        if _matches(num, decimals, scale, values, pct, bool(_HEDGE.search(before))):
            continue
        ctx = (text[max(0, m.start() - 18):m.end() + 10]).replace("\n", " ")
        issues.append(Issue(raw + (um.group(1) if um else ""), ctx))
    if "百分之" in text:
        issues.append(Issue("百分之", "numbers must be written as digits"))
    return issues


def check_script(script: dict, data_pack: object) -> list[Issue]:
    values = collect_values(data_pack)
    issues: list[Issue] = []
    for sc in script.get("scenes", []):
        for field in ("narration", "title"):
            issues.extend(check_text(sc.get(field, ""), values))
        for b in sc.get("bullets", []):
            issues.extend(check_text(b, values))
    return issues


def dumps_for_prompt(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)
