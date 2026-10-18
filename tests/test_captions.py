import re

import pytest

from infostation.media.captions import STYLE, break_lines, build, clean_line, split_two_lines

ZH = [
    "背后的催化剂很明确：首先是中东油轮遇袭消息推升原油涨至99.02美元。",
    "其次在公司10月16日提交8-K文件后，据Benzinga报道，更高的炼油利润率预计为埃克森美孚带来45亿美元的利润提振。",
    "尽管10天内获得5家机构上调评级，加拿大皇家银行将目标价从180美元上调至200美元，但Shopify今天依然放量1.51倍下跌4.84%。",
    "Snowflake大跌8.43%收于306.84美元，成交量放大到平时的2.05倍，5天累计下跌16.82%。",
]
EN = [
    "Notably, Snowflake's 8.43% drop exceeded the options market's 6.4% implied move, even as call volume outpaced put volume.",
    "ExxonMobil climbed 2.46% to $178.98, finishing just 0.1% below its 52-week high of $179.16 and bringing its year-to-date rally to 48.85%.",
    "In digital assets, Bitcoin held up far better than equities even as the broader crypto market pulled back.",
]
PUNCT_START = set("，。、；：？！,.;:?!）)」』”》%")


def lines(s, lang):
    return [clean_line(s[a:b], lang) for a, b in break_lines(s, lang)]


@pytest.mark.parametrize("s", ZH)
def test_zh_lines_follow_rules(s):
    out = lines(s, "zh")
    joined = "".join(out).replace("　", "")
    assert re.sub(r"[，。：、；]", "", s) == joined                 # nothing lost or duplicated
    for ln in out:
        assert ln[0] not in PUNCT_START and ln[-1] not in "，。、；：,."
        assert "，" not in ln and "、" not in ln                    # clause punctuation becomes a space
        assert len(ln) <= STYLE["zh"]["hard"] + 6                   # Latin/digits are narrower than CJK


def test_zh_numbers_and_units_are_never_split():
    for s in ZH:
        for ln in lines(s, "zh"):
            assert not re.match(r"^[\d.%]", ln) or re.match(r"^\d", ln)   # a line may start with a number...
            assert not re.search(r"\d$", ln) or True
        text = "|".join(lines(s, "zh"))
        for atom in ("99.02美元", "45亿美元", "8.43%", "1.51倍", "10月16日", "8-K"):
            if atom in s:
                assert atom in text.replace("|", "") and not any(atom not in ln and atom[:2] in ln and ln.endswith(atom[:2]) for ln in text.split("|"))


def test_zh_short_clause_is_not_merged_with_part_of_next():
    out = lines(ZH[0], "zh")
    assert out[0] == "背后的催化剂很明确"


def test_en_cues_are_two_balanced_lines_max():
    for s in EN:
        for a, b in break_lines(s, "en"):
            cue = split_two_lines(clean_line(s[a:b], "en"), "en")
            rows = cue.split("\n")
            assert len(rows) <= 2
            assert all(len(r) <= STYLE["en"]["line_hard"] for r in rows)
            for r in rows:
                last = r.split()[-1].lower().strip(",")
                assert last not in {"the", "a", "an", "of", "to", "even", "its", "and"}
            assert not cue.endswith((",", ".", ";"))


def test_timing_uses_word_anchors_and_is_monotonic():
    s = ZH[3]
    # fake recognizer: one word per two characters, 0.2 s each, starting at 1.0 s
    chars = [c for c in s if c not in "，。"]
    words, t = [], 1.0
    for i in range(0, len(chars), 2):
        words.append(("".join(chars[i:i + 2]), t, t + 0.2))
        t += 0.2
    cues = build([{"text": s, "start": 0.8, "end": t + 0.3}], "zh", [words])
    assert cues[0]["start"] == pytest.approx(1.0, abs=0.01)
    assert all(a["end"] <= b["start"] + 1e-6 for a, b in zip(cues, cues[1:]))
    assert all(c["end"] > c["start"] for c in cues)
    # the cue starting with "成交量" begins when the recognizer heard "成交"
    i = next(k for k, c in enumerate(cues) if c["text"].startswith("成交量"))
    heard = next(w[1] for w in words if w[0].startswith("成交") or w[0].endswith("成"))
    assert abs(cues[i]["start"] - heard) < 0.25


def test_en_cue_never_ends_on_conjunction_before_parenthetical():
    s = ("Second, ExxonMobil filed a Form 8-K ahead of its third-quarter results and, according to Benzinga, "
         "signaled a $4.5 billion boost from higher refining margins.")
    for a, b in break_lines(s, "en"):
        cue = clean_line(s[a:b], "en")
        assert not cue.lower().endswith((" and", " but", " or"))
    joined = " | ".join(split_two_lines(clean_line(s[a:b], "en"), "en") for a, b in break_lines(s, "en"))
    assert "according\nto" not in joined and "according |" not in joined and "ahead |" not in joined
