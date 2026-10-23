"""Premarket earnings split, clocks, and the EPS basis label on the card."""
from __future__ import annotations

from datetime import date, datetime

from infostation.collectors.events import eps_basis_from_summary, reports
from infostation.config import load_settings
from infostation.market_calendar import ET
from infostation.media.render import calendar_data, earnings_data
from infostation.premarket import llm_health_detail, report_times, split_reports


def test_bmo_already_reported_is_not_upcoming():
    prev, day = "2026-10-20", "2026-10-21"
    now = datetime(2026, 10, 21, 7, 30, tzinfo=ET)
    reps = [
        {"symbol": "NFLX", "date": prev, "timing": "AMC", "eps_actual": 0.87, "report_time_et": None},
        {"symbol": "PM", "date": day, "timing": "TBD", "eps_actual": 2.4, "report_time_et": None},
        {"symbol": "TMO", "date": day, "timing": "BMO", "eps_actual": None,
         "report_time_et": "2026-10-21T06:30:00-04:00"},
        {"symbol": "TSLA", "date": day, "timing": "AMC", "eps_actual": None,
         "report_time_et": "2026-10-21T16:05:00-04:00"},
        {"symbol": "XYZ", "date": day, "timing": "DURING", "eps_actual": None, "report_time_et": None},
        {"symbol": "ABT", "date": day, "timing": "BMO", "eps_actual": None,
         "report_time_et": "2026-10-21T08:00:00-04:00"},
    ]
    overnight, tonight = split_reports(reps, prev, day, now)
    assert [r["symbol"] for r in overnight] == ["NFLX", "PM", "TMO"]
    assert [r["symbol"] for r in tonight] == ["TSLA", "ABT"]


def test_report_times_use_the_clock_or_a_session_label():
    times = report_times(None, {"timing": "AMC", "report_time_et": "2026-10-21T16:05:00-04:00"})
    assert times["time_zh"] == "美东 16:05（洛杉矶 13:05 / 北京次日 4:05）"
    assert times["time_en"] == "4:05 p.m. ET (1:05 p.m. PT)"
    assert report_times(None, {"timing": "AMC"}) == {"time_zh": "盘后", "time_en": "after the close"}


def test_eps_basis_from_yahoo_summary_and_on_the_card(monkeypatch):
    assert eps_basis_from_summary(
        {"quoteSummary": {"result": [{"earningsHistory": {"defaultMethodology": "gaap"}}]}}) == "GAAP"
    assert eps_basis_from_summary(
        {"quoteSummary": {"result": [{"earningsHistory": {"defaultMethodology": "nongaap"}}]}}) == "adjusted"
    assert eps_basis_from_summary({}) is None
    assert eps_basis_from_summary(None) is None

    def yahoo(sym, d):
        return {"timing": "BMO", "eps_basis": "GAAP", "eps_actual": 1.2, "eps_estimate": 1.0,
                "surprise_pct": 20.0, "report_time_et": "2026-10-21T06:30:00-04:00"}

    monkeypatch.setattr("infostation.collectors.events._yahoo_report", yahoo)

    class Http:
        def json(self, url, params=None, **kwargs):
            return {"data": {"rows": [{
                "symbol": "PM", "name": "Philip Morris", "marketCap": "$300,000,000,000",
                "time": "time-not-supplied", "eps": "$1.20", "epsForecast": "$1.00", "surprise": "20",
                "fiscalQuarterEnding": "Sep/2026",
            }]}}

    row = reports(Http(), [date(2026, 10, 21)], set(), 0)[0]
    assert row["eps_basis"] == "GAAP"
    assert row["timing"] == "BMO"
    zh = earnings_data([row | {"premarket_change_pct": 1.5}], "premarket", "zh")
    en = earnings_data([{**row, "eps_basis": "adjusted", "premarket_change_pct": 1.5}], "premarket", "en")
    assert zh["rows"][0]["eps_basis"] == "GAAP"
    assert en["rows"][0]["eps_basis"] == "adjusted"
    blank = earnings_data([{"symbol": "X", "name": "X", "eps_actual": 1, "eps_estimate": 1,
                            "eps_surprise_pct": None, "premarket_change_pct": None}], "premarket", "zh")
    assert blank["rows"][0]["eps_basis"] is None


def _nasdaq_http(rows: list[dict]):
    class Http:
        def json(self, url, params=None, **kwargs):
            return {"data": {"rows": rows}}
    return Http()


def test_year_ago_eps_is_not_this_reports_actual(monkeypatch):
    """Nasdaq `eps` is last year's number while surprise is N/A. Use Yahoo, or nothing."""
    yahoo = {
        "WDC": {"eps_actual": 4.64, "eps_estimate": 4.10, "surprise_pct": 13.17, "eps_basis": "adjusted",
                "timing": "AMC", "report_time_et": "2026-10-22T16:05:00-04:00"},
        "FIX": {},
        "ISRG": {"eps_actual": 3.00, "eps_estimate": 2.64, "surprise_pct": 13.64, "eps_basis": "GAAP"},
    }
    monkeypatch.setattr("infostation.collectors.events._yahoo_report", lambda sym, d: dict(yahoo.get(sym, {})))
    rows = reports(_nasdaq_http([
        {"symbol": "WDC", "name": "Western Digital", "marketCap": "$50,000,000,000",
         "time": "time-after-hours", "eps": "$1.64", "epsForecast": "$3.99", "surprise": "N/A"},
        {"symbol": "FIX", "name": "Comfort Systems", "marketCap": "$40,000,000,000",
         "time": "time-pre-market", "eps": "$8.25", "epsForecast": "$13.50", "surprise": "N/A"},
        {"symbol": "ISRG", "name": "Intuitive Surgical", "marketCap": "$150,000,000,000",
         "time": "time-after-hours", "eps": "$2.53", "epsForecast": "$2.13", "surprise": "N/A"},
        {"symbol": "NFLX", "name": "Netflix", "marketCap": "$280,000,000,000",
         "time": "time-after-hours", "eps": "$0.87", "epsForecast": "$0.82", "surprise": "6.1"},
    ]), [date(2026, 10, 23)], set(), 0)
    by = {r["symbol"]: r for r in rows}
    assert by["WDC"]["eps_actual"] == 4.64
    assert by["WDC"]["eps_estimate"] == 4.10
    assert by["WDC"]["eps_basis"] == "adjusted"
    assert by["WDC"]["eps_actual"] != 1.64
    assert by["FIX"]["eps_actual"] is None
    assert by["FIX"]["eps_estimate"] == 13.50
    assert by["ISRG"]["eps_actual"] == 3.00
    assert by["ISRG"]["eps_estimate"] == 2.64
    assert by["ISRG"]["eps_basis"] == "GAAP"
    # Surprise already posted: Nasdaq's own eps is this report.
    assert by["NFLX"]["eps_actual"] == 0.87
    assert by["NFLX"]["eps_estimate"] == 0.82
    card = earnings_data([by["WDC"] | {"premarket_change_pct": 1.0}], "premarket", "en")
    assert card["rows"][0]["eps"] == 4.64
    assert card["rows"][0]["eps_basis"] == "adjusted"


def test_calendar_card_shows_the_full_earnings_clock():
    zh = calendar_data(None, {"macro": [], "earnings": [{
        "date": "2026-10-21", "symbol": "TSLA", "name": "Tesla",
        "time": "美东 16:05（洛杉矶 13:05 / 北京次日 4:05）",
    }]}, "zh")["earnings"][0]
    assert zh["time"] == "美东 16:05"
    assert zh["timeSub"] == "洛杉矶 13:05 / 北京次日 4:05"
    en = calendar_data(None, {"macro": [], "earnings": [{
        "date": "2026-10-21", "symbol": "TSLA", "name": "Tesla",
        "time": "4:05 p.m. ET (1:05 p.m. PT)",
    }]}, "en")["earnings"][0]
    assert en["time"] == "4:05 p.m. ET"
    assert en["timeSub"] == "1:05 p.m. PT"
    short = calendar_data(None, {"macro": [], "earnings": [{
        "date": "2026-10-21", "symbol": "X", "name": "X", "time": "BMO",
    }]}, "zh")["earnings"][0]
    assert short["time"] == "盘前"
    assert "timeSub" not in short


def test_llm_health_detail_names_provider_and_model():
    settings = load_settings()
    settings.env.pop("INFOSTATION_LLM", None)
    settings.raw["llm"].pop("provider_override", None)
    settings.raw["llm"]["provider"] = "agy"
    assert llm_health_detail(settings, "llm") == "agy gemini-4-argon-medium"
    settings.raw["llm"]["provider"] = "grokbot"
    assert llm_health_detail(settings, "llm") == "grokbot"
    assert llm_health_detail(settings, "template") == "template"
