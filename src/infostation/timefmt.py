"""Event times for viewers: New York time is the reference, Los Angeles / Beijing are shown next to it.

    multi(dt, "zh")  -> "美东周二 8:30（洛杉矶 5:30 / 北京 20:30）"
    multi(dt, "en")  -> "Tue 8:30 a.m. ET (5:30 a.m. PT)"
    pair(dt, "zh")   -> ("美东 08:30", "洛杉矶 05:30 · 北京 20:30")   # two-line cell on cards / video
A zone whose local date differs from New York's gets 次日 / 前一天 (en: "next day" / "prev day").
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ZONES = {"ET": ZoneInfo("America/New_York"), "PT": ZoneInfo("America/Los_Angeles"), "BJ": ZoneInfo("Asia/Shanghai")}
LABEL = {"zh": {"ET": "美东", "PT": "洛杉矶", "BJ": "北京"}, "en": {"ET": "ET", "PT": "PT", "BJ": "Beijing"}}
DEFAULT_ZONES = {"zh": ["ET", "PT", "BJ"], "en": ["ET", "PT"]}
WEEKDAY_ZH = "一二三四五六日"


def zones_for(settings, lang: str) -> list[str]:
    zs = (settings.get(f"time_zones.{lang}") if settings is not None else None) or DEFAULT_ZONES.get(lang, ["ET"])
    return ["ET"] + [z for z in zs if z != "ET" and z in ZONES]


def _clock(t: datetime, lang: str, pad: bool = False) -> str:
    if lang == "zh":
        return f"{t.hour:02d}:{t.minute:02d}" if pad else f"{t.hour}:{t.minute:02d}"
    h = t.hour % 12 or 12
    return f"{h}:{t.minute:02d} {'a.m.' if t.hour < 12 else 'p.m.'}"


def _shift(local: datetime, ref: datetime, lang: str) -> str:
    days = (local.date() - ref.date()).days
    if not days:
        return ""
    if lang == "zh":
        return "次日" if days > 0 else "前一天"
    return " next day" if days > 0 else " prev day"


def _weekday(t: datetime, lang: str) -> str:
    return f"周{WEEKDAY_ZH[t.weekday()]}" if lang == "zh" else t.strftime("%a")


def multi(dt: datetime, lang: str, zones: list[str] | None = None, with_day: bool = False) -> str:
    et = dt.astimezone(ZONES["ET"])
    zones = zones or DEFAULT_ZONES.get(lang, ["ET"])
    others = []
    for z in zones:
        if z == "ET":
            continue
        loc = dt.astimezone(ZONES[z])
        sh = _shift(loc, et, lang)
        if lang == "zh":
            others.append(f"{LABEL[lang][z]}{sh} {_clock(loc, lang)}")
        else:
            others.append(f"{_clock(loc, lang)} {LABEL[lang][z]}{sh}")
    day = _weekday(et, lang) if with_day else ""
    if lang == "zh":
        main = f"美东{day} {_clock(et, lang)}"
        return main + (f"（{' / '.join(others)}）" if others else "")
    main = f"{day + ' ' if day else ''}{_clock(et, lang)} ET"
    return main + (f" ({' / '.join(others)})" if others else "")


def _zh_spoken_clock(t: datetime) -> str:
    h, m = t.hour, t.minute
    part = "凌晨" if h < 5 else "早上" if h < 9 else "上午" if h < 12 else "中午" if h < 13 else "下午" if h < 18 else "晚上"
    h12 = h % 12 or 12
    return f"{part}{h12}点" + ("" if m == 0 else "半" if m == 30 else f"{m:02d}分")


def spoken(dt: datetime, lang: str) -> str:
    """For narration: zh says New York then Beijing time; en says Eastern time only."""
    et = dt.astimezone(ZONES["ET"])
    if lang == "zh":
        bj = dt.astimezone(ZONES["BJ"])
        return f"美东时间{_weekday(et, lang)}{_zh_spoken_clock(et)}，也就是北京时间{_weekday(bj, lang)}{_zh_spoken_clock(bj)}"
    clock = f"{et.hour % 12 or 12}" + (f":{et.minute:02d}" if et.minute else "") + (" a.m." if et.hour < 12 else " p.m.")
    return f"{clock} Eastern on {et.strftime('%A')}"


def pair(dt: datetime, lang: str, zones: list[str] | None = None) -> tuple[str, str]:
    et = dt.astimezone(ZONES["ET"])
    zones = zones or DEFAULT_ZONES.get(lang, ["ET"])
    main = f"美东 {_clock(et, lang, True)}" if lang == "zh" else f"{_clock(et, 'zh', True)} ET"
    subs = []
    for z in zones:
        if z == "ET":
            continue
        loc = dt.astimezone(ZONES[z])
        sh = _shift(loc, et, lang).strip()
        clock = _clock(loc, "zh", True)
        subs.append(f"{LABEL[lang][z]}{sh} {clock}" if lang == "zh" else f"{LABEL[lang][z]} {clock}{' +1d' if sh == 'next day' else ' -1d' if sh else ''}")
    return main, " · ".join(subs)
