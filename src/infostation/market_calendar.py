"""Decide which trading session a run is about (timezone + holiday aware)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

ET = ZoneInfo("America/New_York")
_cal = None


def nyse():
    global _cal
    if _cal is None:
        _cal = xcals.get_calendar("XNYS")
    return _cal


@dataclass
class SessionPlan:
    session: str            # recap | premarket
    target_date: date       # recap: the session being reviewed; premarket: the session about to open
    prev_date: date         # the session before target_date
    now_et: datetime

    @property
    def run_id(self) -> str:
        return f"{self.target_date.isoformat()}_{self.session}"


def _is_session(d: date) -> bool:
    return nyse().is_session(pd.Timestamp(d))


def _prev_session(d: date) -> date:
    return nyse().previous_session(pd.Timestamp(d)).date()


def _next_session(d: date) -> date:
    return nyse().next_session(pd.Timestamp(d)).date()


def last_completed_session(now_et: datetime) -> date:
    today = now_et.date()
    if _is_session(today) and now_et.time() >= time(16, 15):
        return today
    return _prev_session(today) if _is_session(today) else nyse().date_to_session(pd.Timestamp(today), "previous").date()


def plan_session(session: str = "auto", now: datetime | None = None, target: date | None = None) -> SessionPlan:
    now_et = (now or datetime.now(tz=ET)).astimezone(ET)
    today = now_et.date()

    if session == "auto":
        if _is_session(today) and now_et.time() < time(9, 30):
            session = "premarket"
        else:
            session = "recap"

    if target is None:
        if session == "recap":
            target = last_completed_session(now_et)
        else:
            target = today if _is_session(today) and now_et.time() < time(9, 30) else \
                nyse().date_to_session(pd.Timestamp(today + timedelta(days=1)), "next").date()
    elif not _is_session(target):
        raise ValueError(f"{target} is not an NYSE trading day")

    return SessionPlan(session=session, target_date=target, prev_date=_prev_session(target), now_et=now_et)


def upcoming_sessions(after: date, n: int) -> list[date]:
    out, d = [], after
    for _ in range(n):
        d = _next_session(d)
        out.append(d)
    return out
