from datetime import date, datetime

from infostation.market_calendar import ET, plan_session
from infostation.media.tts import normalize_for_speech, split_sentences
from infostation.pipeline import pretty_name


def test_weekend_auto_is_recap_of_friday():
    p = plan_session("auto", now=datetime(2026, 10, 18, 10, 0, tzinfo=ET))   # Sunday
    assert (p.session, p.target_date) == ("recap", date(2026, 10, 16))


def test_before_close_recaps_previous_session():
    p = plan_session("auto", now=datetime(2026, 10, 20, 12, 0, tzinfo=ET))   # Tuesday midday
    assert (p.session, p.target_date) == ("recap", date(2026, 10, 19))


def test_after_close_recaps_today():
    p = plan_session("auto", now=datetime(2026, 10, 20, 17, 0, tzinfo=ET))
    assert p.target_date == date(2026, 10, 20)


def test_early_morning_is_premarket():
    p = plan_session("auto", now=datetime(2026, 10, 20, 7, 30, tzinfo=ET))
    assert (p.session, p.target_date, p.prev_date) == ("premarket", date(2026, 10, 20), date(2026, 10, 19))


def test_split_sentences():
    assert split_sentences("英伟达收跌3.21%。资金流向能源！为什么？", "zh") == ["英伟达收跌3.21%。", "资金流向能源！", "为什么？"]
    en = split_sentences("The U.S. dollar rose 0.5% today. Shares of Apple Inc. fell. Bitcoin hit $81,427.", "en")
    assert en == ["The U.S. dollar rose 0.5% today.", "Shares of Apple Inc. fell.", "Bitcoin hit $81,427."]


def test_normalize_for_speech():
    assert normalize_for_speech("量比2.1x，$NVDA", "zh") == "量比2.1倍，NVDA"
    assert normalize_for_speech("S&P up, volume 3x, BTC $81,427", "en") == "S and P up, volume 3 times, BTC $81427"


def test_pretty_name():
    assert pretty_name("NVIDIA CORP") == "Nvidia"
    assert pretty_name("Meta Platforms, Inc.") == "Meta Platforms"
