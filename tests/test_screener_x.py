from infostation.analysis.screener import score_universe

METRICS = {"NVDA": {"move_z": 1.0, "change_pct": 1.0, "volume_ratio": 1.0, "pct_from_52w_high": -10}}
CAPS = {"NVDA": 3.0e12}


def test_x_buzz_raises_the_score_and_records_why():
    base = score_universe(METRICS, {}, set(), CAPS, 2e9, set(), set(), {"NVDA"})
    buzzed = score_universe(METRICS, {}, set(), CAPS, 2e9, set(), set(), {"NVDA"},
                            x_buzz={"NVDA": {"posts": 8, "engagement": 100}})
    assert buzzed[0]["score"] > base[0]["score"]
    assert any(reason.startswith("X posts") for reason in buzzed[0]["reasons"])
