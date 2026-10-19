from datetime import date, datetime

from infostation import timefmt
from infostation.market_calendar import ET, plan_session
from infostation.writing.writer import scene_plan


def test_three_zones_in_summer_and_winter():
    summer = datetime(2026, 10, 22, 8, 30, tzinfo=ET)            # EDT: Beijing +12h
    winter = datetime(2026, 12, 10, 8, 30, tzinfo=ET)            # EST: Beijing +13h
    assert timefmt.multi(summer, "zh", with_day=True) == "美东周四 8:30（洛杉矶 5:30 / 北京 20:30）"
    assert timefmt.multi(winter, "zh") == "美东 8:30（洛杉矶 5:30 / 北京 21:30）"
    assert timefmt.multi(summer, "en") == "8:30 a.m. ET (5:30 a.m. PT)"


def test_next_day_in_beijing_is_marked():
    after_close = datetime(2026, 10, 21, 16, 5, tzinfo=ET)
    assert timefmt.multi(after_close, "zh") == "美东 16:05（洛杉矶 13:05 / 北京次日 4:05）"
    assert timefmt.pair(after_close, "zh") == ("美东 16:05", "洛杉矶 13:05 · 北京次日 04:05")
    assert timefmt.spoken(after_close, "zh") == "美东时间周三下午4点05分，也就是北京时间周四凌晨4点05分"
    assert timefmt.spoken(after_close, "en") == "4:05 p.m. Eastern on Wednesday"


def test_zones_from_config_always_start_with_new_york():
    class S:
        def get(self, key, default=None):
            return {"time_zones.en": ["PT", "BJ"]}.get(key, default)
    assert timefmt.zones_for(S(), "en") == ["ET", "PT", "BJ"]
    assert timefmt.zones_for(None, "zh") == ["ET", "PT", "BJ"]


def test_after_hours_scene_only_when_companies_reported():
    assert "afterhours" not in [s["id"] for s in scene_plan(3, 0)]
    ids = [s["id"] for s in scene_plan(3, 2)]
    assert ids.index("story3") < ids.index("afterhours") < ids.index("crypto")


def test_scheduled_times_pick_the_right_session():
    pre = plan_session("auto", now=datetime(2026, 10, 20, 7, 30, tzinfo=ET))       # premarket timer
    rec = plan_session("auto", now=datetime(2026, 10, 20, 17, 0, tzinfo=ET))       # recap timer
    assert (pre.session, pre.target_date) == ("premarket", date(2026, 10, 20))
    assert (rec.session, rec.target_date) == ("recap", date(2026, 10, 20))
    # Thanksgiving: the 07:30 timer must not produce a brief for a closed market
    hol = plan_session("auto", now=datetime(2026, 11, 26, 7, 30, tzinfo=ET))
    assert (hol.session, hol.target_date) == ("recap", date(2026, 11, 25))
