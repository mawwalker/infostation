"""Broadcast-style subtitle layout and timing.

Layout rules
- Lines are broken on natural boundaries: sentence end > clause punctuation > before a conjunction > between words.
  Chinese is segmented with jieba so words are never cut; numbers with their units ("8.43%", "45亿美元", "$13.1 million"),
  Latin words and names ("S&P 500", "10b5-1") are atomic.
- Line lengths are balanced with dynamic programming instead of greedy filling (no 20-char line followed by a 3-char orphan).
- A line never starts with closing punctuation and never ends with opening punctuation; trailing ，。、；：,.;: are removed,
  and in Chinese the clause punctuation inside a line becomes a space, as in TV subtitles. ？！ and quotes are kept.

Timing
- Each sentence is synthesized separately, so sentence boundaries are exact.
- Inside a sentence, line boundaries come from Whisper word timestamps matched against the script text; where the
  recognizer and the script disagree (numbers read aloud, names) times are interpolated by estimated spoken length.
"""
from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

# zh: one line per cue (Chinese TV convention). en: up to two lines per cue, ≤ 42 chars each (Netflix-style).
STYLE = {
    "zh": {"max": 18, "hard": 22, "min": 5},
    "en": {"max": 80, "hard": 86, "min": 18, "line_max": 42, "line_hard": 46, "line_min": 8, "clause_max": 42},
}
STRONG_END = set("。！？!?；;")
CLAUSE_END = set("，、：,:—")
NO_LINE_START = set("，。、；：？！,.;:?!）)」』”’》〉】%％·…")
NO_LINE_END = set("（(「『“‘《〈【$¥￥")
TRAILING_STRIP = "，。、；：,.;:… 　"
ZH_INNER_TO_SPACE = re.compile(r"[，、；]")
ZH_CONJ = {"但是", "但", "而", "而且", "并且", "并", "同时", "因为", "所以", "不过", "然而", "此外", "另外", "以及", "以及",
           "如果", "虽然", "尽管", "甚至", "也", "还", "则", "即", "导致", "使得", "随着", "其中", "或者", "从而"}
ZH_NO_BREAK_BEFORE = {"的", "了", "着", "过", "地", "得", "们", "吗", "呢", "吧", "啊", "等", "之", "中", "上", "下", "里"}
EN_CONJ = {"and", "but", "or", "so", "while", "as", "because", "which", "that", "who", "where", "when", "after",
           "before", "since", "although", "though", "despite", "with", "even", "if", "than", "until", "whereas"}
EN_PREP = {"to", "in", "on", "at", "for", "by", "from", "into", "over", "under", "after", "before", "amid", "against",
           "toward", "towards", "through", "during", "despite", "with", "without", "near", "below", "above"}
EN_NO_END = {"a", "an", "the", "of", "to", "in", "on", "at", "for", "by", "from", "its", "their", "his", "her", "our",
             "this", "that", "these", "those", "and", "or", "but", "is", "are", "was", "were", "be", "very", "more",
             "most", "per", "about", "than", "into", "over", "under", "mr.", "ms.", "dr.", "u.s.", "even", "just",
             "only", "not", "also", "still", "both", "such", "said", "says", "will", "would", "could", "has", "have", "had",
             "according", "ahead", "due", "compared", "relative", "thanks", "because", "rather", "instead"}

# Atomic spans inside Chinese text: numbers+units, dates, Latin names (optionally followed by a number: "S&P 500").
_ZH_ATOM = re.compile(
    r"[$¥€]?\d[\d,]*(?:\.\d+)?\s*(?:%|％|倍|x|X|bp|个百分点|万亿|亿|万|千)?(?:美元|美分|元|港元|股|手|张|倍|年|月|日|号|周|天|只|家|名|次|点)?"
    r"|[A-Za-z][A-Za-z0-9&.'’\-]*(?:\s(?:[A-Z][A-Za-z0-9&.'’\-]*|\d{2,4}\b))*"
)
_EN_NUM_UNIT = re.compile(r"^(million|billion|trillion|thousand|percent|points?|bps?|basis|x|times)[,.;:]?$", re.I)


@dataclass
class Atom:
    start: int      # char offsets into the sentence
    end: int

    def text(self, s: str) -> str:
        return s[self.start:self.end]


def atoms_zh(s: str) -> list[Atom]:
    import jieba
    jieba.setLogLevel(logging.WARNING)
    out: list[Atom] = []
    pos = 0
    for m in _ZH_ATOM.finditer(s):
        out.extend(_jieba_atoms(s, pos, m.start(), jieba))
        out.append(Atom(m.start(), m.end()))
        pos = m.end()
    out.extend(_jieba_atoms(s, pos, len(s), jieba))
    return _attach_punct(s, out)


def _jieba_atoms(s: str, a: int, b: int, jieba) -> list[Atom]:
    out, p = [], a
    for w in jieba.cut(s[a:b], HMM=True):
        out.append(Atom(p, p + len(w)))
        p += len(w)
    return out


def atoms_en(s: str) -> list[Atom]:
    words = [Atom(m.start(), m.end()) for m in re.finditer(r"\S+", s)]
    out: list[Atom] = []
    for w in words:
        t = w.text(s)
        prev = out[-1].text(s) if out else ""
        if out and _EN_NUM_UNIT.match(t) and re.search(r"\d[%x]?$", prev):
            out[-1] = Atom(out[-1].start, w.end)            # "$13.1 million"
        elif out and re.fullmatch(r"\d{2,4}[,.;:]?", t) and re.fullmatch(r"(S&P|Nasdaq|Dow|Russell|FTSE|Nikkei|DAX|Stoxx)", prev):
            out[-1] = Atom(out[-1].start, w.end)            # "S&P 500"
        else:
            out.append(w)
    return out


def _attach_punct(s: str, atoms: list[Atom]) -> list[Atom]:
    """Glue punctuation-only atoms to their neighbour so no line can start with ，or end with “."""
    out: list[Atom] = []
    pending_open: Atom | None = None
    for a in atoms:
        t = a.text(s)
        if not t.strip():
            if out:
                out[-1] = Atom(out[-1].start, a.end)
            continue
        if pending_open is not None:
            a = Atom(pending_open.start, a.end)
            pending_open = None
        if out and all(c in NO_LINE_START or c in STRONG_END or c in CLAUSE_END for c in t.strip()):
            out[-1] = Atom(out[-1].start, a.end)
        elif all(c in NO_LINE_END for c in t.strip()):
            pending_open = a
        else:
            out.append(a)
    if pending_open is not None and out:
        out[-1] = Atom(out[-1].start, pending_open.end)
    return out


def _display_len(t: str, lang: str) -> float:
    if lang == "en":
        return len(t.strip())
    # Latin letters/digits are about half the width of a CJK glyph.
    return sum(0.55 if ord(c) < 0x2E80 else 1.0 for c in t.strip())


def break_lines(s: str, lang: str, lim: dict | None = None, offset: int = 0) -> list[tuple[int, int]]:
    """Return [(start, end)] char spans (one per cue) for one sentence. `offset` shifts spans for substrings."""
    st = lim or STYLE[lang]
    atoms = atoms_zh(s) if lang == "zh" else atoms_en(s)
    if not atoms:
        return []
    n = len(atoms)
    total = _display_len(s, lang)
    if total <= st["max"]:
        return [(offset + atoms[0].start, offset + atoms[-1].end)]
    k = max(1, round(total / st["max"] + 0.49))
    target = total / k

    def break_penalty(i: int) -> float:
        """Penalty for breaking after atom i (i.e. before atom i+1)."""
        t = atoms[i].text(s).rstrip()
        nxt = atoms[i + 1].text(s).strip() if i + 1 < n else ""
        last = t[-1] if t else ""
        if last in STRONG_END:
            return 0.0
        if lang == "en" and t.lower().rstrip(",;:") in {"and", "but", "or", "so", "yet"}:
            return 25.0                             # "results and, according to ..." → don't end on "and"
        if last in CLAUSE_END or (lang == "en" and last in ",;:"):
            return 0.5
        if lang == "zh":
            if nxt in ZH_CONJ:
                return 3.0
            if nxt[:1] in ZH_NO_BREAK_BEFORE and len(nxt) == 1:
                return 40.0
            if re.match(r"^(据|在|对|从|向|与|和|为|把|被|让|将|于|比|随|自)", nxt):
                return 5.0                          # before a prepositional phrase
            return 12.0
        word = t.lower().strip("\"“”'’()")
        if word in EN_NO_END:
            return 40.0
        nw = nxt.lower().strip("\"“”'’(").rstrip(",;:")
        if nw in EN_CONJ:
            return 2.5
        if nw == "of":
            return 12.0                             # "high | of $179.16" splits a noun phrase
        if nw in EN_PREP:
            return 4.0
        if re.search(r"\d", t) and not re.search(r"\d", nxt):
            return 7.0                              # after a number ("... 7.02% | as ...")
        return 14.0

    # Clause rule: a clause (text between punctuation) that fits on one line is never broken internally.
    def ends_clause(i: int) -> bool:
        t = atoms[i].text(s).rstrip()
        return bool(t) and (t[-1] in STRONG_END or t[-1] in CLAUSE_END or (lang == "en" and t[-1] in ",;:"))

    forbidden = [False] * n                         # forbidden[i]: no break after atom i
    c0 = 0
    for i in range(n):
        if ends_clause(i) or i == n - 1:
            if _display_len(s[atoms[c0].start:atoms[i].end], lang) <= st.get("clause_max", st["max"]):
                for k2 in range(c0, i):
                    forbidden[k2] = True
            c0 = i + 1

    INF = float("inf")
    best = [INF] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0.0
    for j in range(1, n + 1):                      # line covers atoms[i:j]
        width = 0.0
        for i in range(j - 1, -1, -1):
            width = _display_len(s[atoms[i].start:atoms[j - 1].end], lang)
            if width > st["hard"]:
                break
            if best[i] == INF:
                continue
            # A line may join several clauses only if it holds them whole.
            if lang == "zh" and any(ends_clause(k2) for k2 in range(i, j - 1)):
                if not ((i == 0 or ends_clause(i - 1)) and (j == n or ends_clause(j - 1))):
                    continue
            cost = ((width - target) / target) ** 2 * 5
            if width > st["max"]:
                cost += (width - st["max"]) * 3
            if width < st["min"] and not (i == 0 and j == n):
                cost += 30
            if j < n:
                if forbidden[j - 1]:
                    continue
                cost += break_penalty(j - 1)
            cost += 1.5                             # per-line cost: prefer fewer lines
            if best[i] + cost < best[j]:
                best[j] = best[i] + cost
                back[j] = i
        if best[j] == INF and j >= 1:              # a single atom longer than the hard limit
            best[j] = best[j - 1] + 100
            back[j] = j - 1
    spans, j = [], n
    while j > 0:
        i = back[j]
        spans.append((offset + atoms[i].start, offset + atoms[j - 1].end))
        j = i
    return spans[::-1]


def _en_break_cost(left: str, right: str) -> float:
    last = left.rstrip()[-1:]
    lw = left.split()[-1].lower().strip("\"“”'’()")
    rw = right.split()[0].lower().strip("\"“”'’(").rstrip(",;:")
    if lw.rstrip(",;:") in {"and", "but", "or", "so", "yet"}:
        return 25.0
    if last in ".!?;":
        return 0.0
    if last in ",:—":
        return 0.5
    if lw in EN_NO_END:
        return 40.0
    if rw in EN_CONJ:
        return 2.5
    if rw == "of":
        return 12.0
    if rw in EN_PREP:
        return 4.0
    if re.search(r"\d", lw) and not re.search(r"\d", rw):
        return 7.0
    return 14.0


def split_two_lines(text: str, lang: str) -> str:
    """English cue → at most two lines: best split among all word boundaries (balance + break quality)."""
    st = STYLE[lang]
    if lang != "en" or len(text) <= st["line_max"]:
        return text
    atoms = atoms_en(text)
    best, best_cost = None, float("inf")
    for k in range(1, len(atoms)):
        left, right = text[:atoms[k - 1].end], text[atoms[k].start:]
        lw, rw = len(left), len(right)
        if max(lw, rw) > st["line_hard"]:
            continue
        cost = abs(lw - rw) / 6 + _en_break_cost(left, right) + max(0, max(lw, rw) - st["line_max"]) * 3
        if rw > lw:
            cost += 0.5                              # a slightly longer top line reads better (pyramid shape)
        if cost < best_cost:
            best, best_cost = (left, right), cost
    if best is None:
        return text
    return clean_line(best[0], lang, keep_end=True) + "\n" + best[1].strip()


def clean_line(t: str, lang: str, keep_end: bool = False) -> str:
    t = t.strip()
    while t and not keep_end and t[-1] in TRAILING_STRIP:
        t = t[:-1].rstrip()
    while t and t[0] in NO_LINE_START:
        t = t[1:].lstrip()
    if lang == "zh":
        t = ZH_INNER_TO_SPACE.sub("　", t)
        t = re.sub(r"　+", "　", t)
        t = re.sub(r"\s*　\s*", "　", t)
        if t.count("“") != t.count("”"):
            t = t.replace("“", "").replace("”", "")
    return t


# ---------------------------------------------------------------- timing

def _spoken_weight(c: str, lang: str) -> float:
    if c.isspace() or c in STRONG_END or c in CLAUSE_END:
        return 0.15
    if c in "%％":
        return 2.5 if lang == "zh" else 2.0
    if c.isdigit():
        return 1.1 if lang == "zh" else 0.9
    if ord(c) >= 0x2E80:
        return 1.0
    return 0.32 if lang == "zh" else 0.3      # Latin letters


def _norm(c: str) -> str:
    c = c.lower()
    return c if (c.isalnum() or ord(c) >= 0x2E80) and not c.isspace() and c not in "，。、；：？！“”‘’《》（）" else ""


def time_lines(sentence: str, spans: list[tuple[int, int]], lang: str, start: float, end: float,
               words: list[tuple[str, float, float]] | None) -> list[tuple[float, float]]:
    """Times (absolute) for each line span. `words` are recognizer words with absolute times, or None."""
    weights = [_spoken_weight(c, lang) for c in sentence]
    cum = [0.0]
    for w in weights:
        cum.append(cum[-1] + w)

    speech_start, speech_end = start, end
    anchors: dict[int, float] = {}                 # sentence char index → absolute time
    if words:
        speech_start, speech_end = max(start, words[0][1]), min(end, words[-1][2] + 0.12)
        asr_chars: list[float] = []
        asr_norm = ""
        for text, ws, we in words:
            chars = [c for c in text if _norm(c)]
            for k, c in enumerate(chars):
                asr_norm += _norm(c)
                asr_chars.append(ws + (we - ws) * k / max(1, len(chars)))
        disp_idx = [i for i, c in enumerate(sentence) if _norm(c)]
        disp_norm = "".join(_norm(sentence[i]) for i in disp_idx)
        sm = difflib.SequenceMatcher(None, disp_norm, asr_norm, autojunk=False)
        for blk in sm.get_matching_blocks():
            if blk.size < 2:                       # single-char matches are too ambiguous
                continue
            for k in range(blk.size):
                anchors[disp_idx[blk.a + k]] = asr_chars[blk.b + k]

    def t_at(ci: int) -> float:
        """Time at which sentence char `ci` starts being spoken."""
        if ci in anchors:
            return anchors[ci]
        before = max((i for i in anchors if i < ci), default=None)
        after = min((i for i in anchors if i > ci), default=None)
        a_i, a_t = (before, anchors[before]) if before is not None else (0, speech_start)
        b_i, b_t = (after, anchors[after]) if after is not None else (len(sentence), speech_end)
        span = cum[b_i] - cum[a_i]
        frac = (cum[ci] - cum[a_i]) / span if span > 0 else 0.0
        return a_t + (b_t - a_t) * frac

    bounds = [speech_start] + [t_at(s0) for s0, _ in spans[1:]] + [speech_end]
    # Monotonic and inside the sentence.
    for i in range(1, len(bounds)):
        bounds[i] = min(max(bounds[i], bounds[i - 1] + 0.25), speech_end)
    return [(bounds[i], bounds[i + 1]) for i in range(len(spans))]


def build(sentences: list[dict], lang: str, words_by_sentence: list[list | None] | None = None) -> list[dict]:
    """sentences: [{text, start, end}] (absolute, scene-relative seconds) → caption cues."""
    cues: list[dict] = []
    for idx, sen in enumerate(sentences):
        spans = break_lines(sen["text"], lang)
        if not spans:
            continue
        words = words_by_sentence[idx] if words_by_sentence else None
        times = time_lines(sen["text"], spans, lang, sen["start"], sen["end"], words)
        for (a, b), (t0, t1) in zip(spans, times):
            text = split_two_lines(clean_line(sen["text"][a:b], lang), lang)
            if text:
                cues.append({"start": round(t0, 3), "end": round(t1, 3), "text": text})
    # Bridge short gaps so captions don't flicker between sentences.
    for i in range(len(cues) - 1):
        gap = cues[i + 1]["start"] - cues[i]["end"]
        if 0 < gap < 0.45:
            cues[i]["end"] = round(cues[i + 1]["start"] - 0.02, 3)
    return cues
