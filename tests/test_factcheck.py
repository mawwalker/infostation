from infostation.writing.factcheck import check_script, check_text, collect_values
from infostation.writing.writer import x_weighted_length

DATA = {
    "metrics": {"close": 214.13, "change_pct": -3.21, "volume_ratio": 2.05, "market_cap_billion": 5170.6},
    "insider": {"open_market_sell_usd": 13168954},
    "headlines": [{"title": "Analysts raise target to $250"}, {"title": "Exxon signals $4.5B refining boost"}],
}
VALS = collect_values(DATA)


def flagged(text: str) -> list[str]:
    return [i.number for i in check_text(text, VALS)]


def test_exact_and_rounded_numbers_pass():
    assert flagged("英伟达收于214.13美元，下跌3.21%，量比2.05倍。") == []
    assert flagged("Nvidia fell 3.2% to about 214 dollars.") == []
    assert flagged("volume ran 2.1x normal") == []


def test_unit_scaling_passes():
    assert flagged("CEO sold about 13.2 million dollars of stock") == []
    assert flagged("CEO套现约1317万美元") == []
    assert flagged("市值约5.17万亿美元") == []
    assert flagged("headline target of 250 dollars") == []


def test_numbers_inside_x_posts_are_not_sources():
    pack = {"close": 10.0, "x_posts": [{"text": "NVDA to 9999", "metrics": {"likes": 4321}}],
            "x_buzz": {"NVDA": {"posts": 4, "engagement": 4321}}}
    values = collect_values(pack)
    assert 10.0 in values
    assert 9999.0 not in values
    assert 4321.0 not in values
    assert flagged_against("someone on X says 9999", values) == ["9999"]


def flagged_against(text: str, values: list[float]) -> list[str]:
    return [i.number for i in check_text(text, values)]


def test_urls_and_handles_are_not_numbers():
    text = "see https://x.com/TestDesk/status/123456789012345 and @user123 — closed at 220.50"
    assert flagged(text) == ["220.50"]
    assert flagged("链接 https://example.com/v1.2/item 下跌4.7%") == ["4.7"]


def test_invented_numbers_are_flagged():
    assert flagged("下跌4.7%") == ["4.7"]
    assert flagged("market cap of 6.2 trillion") == ["6.2trillion"]
    assert flagged("closed at 220.50") == ["220.50"]


def test_dates_counts_and_technicals_ignored():
    assert flagged("10月16日，3只股票跌破50日均线，2026年以来第2次") == []
    assert flagged("On Oct 16, the 200-day average held; top 3 movers") == []


def test_spelled_out_percent_flagged():
    assert "百分之" in flagged("下跌百分之三")


def test_check_script_covers_titles_and_bullets():
    script = {"scenes": [{"narration": "收于214.13", "title": "暴跌9%", "bullets": ["量比7.7倍"]}]}
    nums = [i.number for i in check_script(script, DATA)]
    assert nums == ["9", "7.7"]


def test_x_weighted_length():
    assert x_weighted_length("hello") == 5
    assert x_weighted_length("英伟达") == 6
    assert x_weighted_length("看 https://example.com/very/long/path") == 2 + 1 + 23


def test_regression_false_positives_from_first_run():
    assert flagged("CEO按10b5-1计划减持超1310万美元") == []           # plan name + hedged truncation
    assert flagged("sold over $13.1 million under a 10b5-1 plan") == []
    assert flagged("炼油利润预计带来45亿美元提振") == []               # "$4.5B" in a headline
    assert flagged("a $4.5 billion boost, per its 10-K") == []
    assert flagged("下跌3.2%") == []                                    # -3.21 truncated
    assert flagged("减持1310万美元") == ["1310万"]                    # 1316.9万 → 1310万 is neither rounding nor truncation


def test_trim_to_x_limit():
    from infostation.writing.writer import trim_to_x_limit
    en = "First sentence is fine. " * 20
    assert x_weighted_length(trim_to_x_limit(en)) <= 280
    zh = "英伟达收跌3.21%。" * 30
    out = trim_to_x_limit(zh)
    assert x_weighted_length(out) <= 280 and out.endswith("。")
    assert trim_to_x_limit("short") == "short"
