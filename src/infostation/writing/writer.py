"""Editorial + script + thread generation on top of the agy client, with fact-check and fallbacks."""
from __future__ import annotations

import json
import logging
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from ..config import PROMPTS_DIR, Settings
from ..llm.agy import AgyClient, LLMError
from . import factcheck, templates

log = logging.getLogger(__name__)

# (id, type, seconds). Story scenes are expanded to story1..storyN.
SCENE_PLAN = [
    ("intro", "intro", 16), ("market", "market", 38), ("sectors", "sectors", 24), ("movers", "movers", 32),
    ("story", "story", 68), ("crypto", "crypto", 36), ("calendar", "calendar", 26), ("outro", "outro", 12),
]
CHARS_PER_SEC = {"zh": 4.2, "en": 2.0}   # zh: characters, en: words (edge-tts pace incl. pauses)

STYLE = {
    "zh": (
        "- 像一位懂行、说话利落的财经主播在跟朋友复盘，口语化，短句为主，每句不超过 30 个字。\n"
        "- 结论先行：每个场景第一句就说清「发生了什么 + 为什么重要」，再给证据。\n"
        "- 多讲「背离」和「冲突」：散户情绪 vs 内部人行为、股价 vs 基本面消息、期权定价 vs 实际波动。\n"
        "- 场景之间要有自然过渡句，不要每段都用「接下来」。\n"
        "- 不要使用「家人们」「炸裂」「史诗级」等夸张用语，不要用感叹号堆情绪。\n"
        "- 结尾一句话总结今天的主线，并提醒「以上内容不构成投资建议」。\n"
        "- 数字要方便听：百分比最多保留2位小数；上万的价格可以说成「8.14万美元」这类口语化写法（数值必须来自数据）。"
    ),
    "en": (
        "- Sound like a sharp, conversational market host — short sentences, plain words, no hype.\n"
        "- Lead with the point: each scene's first sentence says what happened and why it matters, then the evidence.\n"
        "- Highlight divergences: retail sentiment vs insider activity, price vs news, options pricing vs realized moves.\n"
        "- Vary transitions between scenes; never start consecutive scenes with 'Next'.\n"
        "- No clickbait words ('insane', 'massive', 'explodes'); no exclamation marks.\n"
        "- Close with a one-line takeaway and 'This is not financial advice.'\n"
        "- Format numbers for listening: thousands separators (81,427), at most 2 decimals for percentages."
    ),
}
NAME_RULE = {
    "zh": "中文稿用公司的常用中文名（如英伟达、特斯拉、微软）；没有通行中文名的用英文名。指数和加密货币用中文（标普500、比特币）。",
    "en": "Use common company names (Nvidia, Tesla). Say 'the S&P 500', 'Bitcoin'.",
}
SESSION_LABEL = {"recap": {"zh": "盘后复盘", "en": "after-the-bell recap"},
                 "premarket": {"zh": "盘前早报", "en": "pre-market briefing"}}


def scene_plan(n_stories: int) -> list[dict]:
    out = []
    for sid, typ, sec in SCENE_PLAN:
        if typ == "story":
            out += [{"id": f"story{i}", "type": "story", "seconds": sec} for i in range(1, n_stories + 1)]
        else:
            out.append({"id": sid, "type": typ, "seconds": sec})
    return out


def editor_schema(n: int) -> dict:
    point = {"type": "object", "properties": {"zh": {"type": "string"}, "en": {"type": "string"}}, "required": ["zh", "en"]}
    return {
        "type": "object",
        "properties": {
            "market_theme": point,
            "sentiment": {"type": "array", "items": {"type": "object", "properties": {
                "symbol": {"type": "string"},
                "score": {"type": "integer", "minimum": 0, "maximum": 100},
                "bull_point": point, "bear_point": point,
            }, "required": ["symbol", "score", "bull_point", "bear_point"]}},
            "stories": {"type": "array", "minItems": n, "maxItems": n, "items": {"type": "object", "properties": {
                "symbol": {"type": "string"},
                "angle": {"type": "string", "description": "what the segment argues, English"},
                "evidence": {"type": "array", "items": {"type": "string"}},
                "hook": point,
            }, "required": ["symbol", "angle", "evidence", "hook"]}},
        },
        "required": ["market_theme", "sentiment", "stories"],
    }


def script_schema(scenes: list[dict]) -> dict:
    return {
        "type": "object",
        "properties": {
            "video_title": {"type": "string", "description": "YouTube title. zh: ≤ 32 Chinese characters; en: ≤ 70 characters"},
            "thumbnail_text": {"type": "string", "description": "2-6 punchy words for the thumbnail (zh ≤ 10 characters)"},
            "thumbnail_subtext": {"type": "string", "description": "one short supporting line for the thumbnail"},
            "description": {"type": "string", "description": "YouTube description body, 2-4 sentences, no hashtags"},
            "tags": {"type": "array", "items": {"type": "string"}, "minItems": 5, "maxItems": 15},
            "scenes": {"type": "array", "minItems": len(scenes), "maxItems": len(scenes), "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "enum": [s["id"] for s in scenes]},
                    "type": {"type": "string"},
                    "title": {"type": "string", "description": "on-screen headline (zh ≤ 14 characters, en ≤ 45 characters)"},
                    "bullets": {"type": "array", "items": {"type": "string"}, "maxItems": 3,
                                "description": "on-screen key points (zh ≤ 18 characters each, en ≤ 55 characters)"},
                    "narration": {"type": "string"},
                },
                "required": ["id", "type", "title", "bullets", "narration"],
            }},
        },
        "required": ["video_title", "thumbnail_text", "thumbnail_subtext", "description", "tags", "scenes"],
    }


def thread_schema() -> dict:
    post = {"type": "object", "properties": {"text": {"type": "string"}, "card": {"type": ["string", "null"]}},
            "required": ["text", "card"]}
    return {"type": "object", "properties": {"zh": {"type": "array", "items": post}, "en": {"type": "array", "items": post}},
            "required": ["zh", "en"]}


def _fill(template: str, **kw: str) -> str:
    for k, v in kw.items():
        template = template.replace("{{" + k + "}}", v)
    return template


class Writer:
    def __init__(self, settings: Settings, client: AgyClient):
        self.s = settings
        self.client = client
        self.brand = {"zh": settings.get("brand.name_zh"), "en": settings.get("brand.name_en")}

    # ---------- editor ----------
    def editor(self, session: str, date: str, llm_view: dict, n: int) -> dict:
        prompt = _fill((PROMPTS_DIR / "editor.md").read_text(encoding="utf-8"),
                       SESSION=session, DATE=date, N_STORIES=str(n), DATA=factcheck.dumps_for_prompt(llm_view))
        try:
            out = self.client.run("editor", prompt, editor_schema(n))
        except LLMError as e:
            log.error("editor LLM failed, using quantitative fallback: %s", e)
            return templates.editor_fallback(llm_view, n)
        valid = {c["symbol"] for c in llm_view.get("candidates", [])}
        picked = [s for s in out["stories"] if s["symbol"] in valid]
        seen: set[str] = set()
        out["stories"] = [s for s in picked if not (s["symbol"] in seen or seen.add(s["symbol"]))]
        if len(out["stories"]) < n:
            fb = templates.editor_fallback(llm_view, n)
            for s in fb["stories"]:
                if len(out["stories"]) >= n:
                    break
                if s["symbol"] not in seen:
                    out["stories"].append(s)
                    seen.add(s["symbol"])
        out["source"] = "llm"
        return out

    # ---------- scripts ----------
    def scripts(self, session: str, writer_view: dict, editor: dict, scenes: list[dict],
                reference: object = None) -> dict[str, dict]:
        """`reference` = everything numbers may be traced to (defaults to writer_view)."""
        self._reference = reference if reference is not None else writer_view
        langs = self.s.languages
        if self.s.get("llm.parallel", True) and len(langs) > 1:
            with ThreadPoolExecutor(max_workers=len(langs)) as ex:
                futs = {lang: ex.submit(self._script_with_check, lang, session, writer_view, editor, scenes) for lang in langs}
                return {lang: f.result() for lang, f in futs.items()}
        return {lang: self._script_with_check(lang, session, writer_view, editor, scenes) for lang in langs}

    def _script_with_check(self, lang: str, session: str, view: dict, editor: dict, scenes: list[dict]) -> dict:
        revision = ""
        max_rewrites = int(self.s.get("factcheck.max_rewrites", 1))
        script: dict | None = None
        issues: list = []
        for attempt in range(max_rewrites + 1):
            try:
                script = self._script_once(lang, session, view, editor, scenes, revision, attempt)
            except LLMError as e:
                log.error("script[%s] LLM failed, using template fallback: %s", lang, e)
                script = templates.script_fallback(lang, session, view, editor, scenes, self.brand[lang])
                script["_source"] = "template"
                script["_factcheck"] = []
                return script
            script = _normalize_scenes(script, scenes)
            issues = factcheck.check_script(script, self._reference)
            if not issues:
                break
            log.warning("script[%s] factcheck flagged %d numbers: %s", lang, len(issues), "; ".join(map(str, issues[:5])))
            revision = ("## Revision required\nYour previous draft used numbers that are NOT in DATA. Rewrite the whole "
                        "script; remove or replace these (describe qualitatively if needed):\n" +
                        "\n".join(f"- {i}" for i in issues) +
                        "\n\nPrevious draft:\n```json\n" + json.dumps(script, ensure_ascii=False) + "\n```")
        assert script is not None
        script["_source"] = "llm"
        script["_factcheck"] = [str(i) for i in issues]
        return script

    def _script_once(self, lang: str, session: str, view: dict, editor: dict, scenes: list[dict],
                     revision: str, attempt: int) -> dict:
        unit = "Chinese characters" if lang == "zh" else "words"
        scene_lines = []
        stories = editor["stories"]
        for sc in scenes:
            target = int(sc["seconds"] * CHARS_PER_SEC[lang])
            extra = ""
            if sc["type"] == "story":
                st = stories[int(sc["id"][5:]) - 1]
                extra = f" — about {st['symbol']}: {st['angle']}"
            if sc["type"] == "intro":
                extra = " — bullets = one short factual hook per story, in story order"
            scene_lines.append(f"- id={sc['id']} type={sc['type']}: about {target} {unit}{extra}")
        prompt = _fill(
            (PROMPTS_DIR / "script.md").read_text(encoding="utf-8"),
            BRAND=self.brand[lang], SESSION_LABEL=SESSION_LABEL[session][lang],
            LANGUAGE="Simplified Chinese" if lang == "zh" else "English",
            NAME_RULE=NAME_RULE[lang], STYLE=STYLE[lang], SCENES="\n".join(scene_lines),
            EDITOR=factcheck.dumps_for_prompt({"market_theme": editor["market_theme"][lang],
                                               "stories": [{k: s[k] for k in ("symbol", "angle", "evidence")} | {"hook": s["hook"][lang]}
                                                           for s in stories]}),
            REVISION=revision, DATA=factcheck.dumps_for_prompt(view),
        )
        return self.client.run(f"script_{lang}" + (f"_rev{attempt}" if attempt else ""), prompt, script_schema(scenes))

    # ---------- X threads ----------
    def threads(self, view: dict, scripts: dict[str, dict], cards: list[str]) -> dict[str, list[dict]]:
        brief = {lang: [{"id": s["id"], "narration": s["narration"]} for s in sc["scenes"]] for lang, sc in scripts.items()}
        prompt = _fill((PROMPTS_DIR / "thread.md").read_text(encoding="utf-8"),
                       BRAND=f"{self.brand['zh']} / {self.brand['en']}", N_MIN="5", N_MAX="8",
                       CARDS=", ".join(f'"{c}"' for c in cards),
                       SCRIPTS=factcheck.dumps_for_prompt(brief), DATA=factcheck.dumps_for_prompt(view))
        try:
            out = self.client.run("threads", prompt, thread_schema())
        except LLMError as e:
            log.error("thread LLM failed, using template fallback: %s", e)
            return templates.thread_fallback(scripts, cards)
        for lang in ("zh", "en"):
            for p in out.get(lang, []):
                if p.get("card") not in cards:
                    p["card"] = None
        self._shorten_posts(out)
        for lang in ("zh", "en"):
            for p in out.get(lang, []):
                p["weighted_len"] = x_weighted_length(p["text"])
                p["over_limit"] = p["weighted_len"] > 280
        return {lang: out.get(lang, []) for lang in self.s.languages}

    def _shorten_posts(self, out: dict) -> None:
        """One agy pass to rewrite over-long posts, then a hard sentence-level trim as the last resort."""
        long_posts = [{"lang": lang, "index": i, "text": p["text"], "weighted_len": x_weighted_length(p["text"])}
                      for lang in ("zh", "en") for i, p in enumerate(out.get(lang, []))
                      if x_weighted_length(p["text"]) > X_TARGET]
        if long_posts:
            schema = {"type": "object", "properties": {"posts": {"type": "array", "items": {"type": "object", "properties": {
                "lang": {"type": "string"}, "index": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["lang", "index", "text"]}}}, "required": ["posts"]}
            prompt = ("Shorten each X post below so its weighted length is at most 240 (Chinese characters, Chinese "
                      "punctuation and emoji count 2; ASCII counts 1). Keep the key fact and any cashtag, keep at most 3 "
                      "numbers, do not add new facts or numbers. Return every post with the same lang and index.\n\n"
                      + json.dumps(long_posts, ensure_ascii=False, indent=1))
            try:
                fixed = self.client.run("threads_shorten", prompt, schema)
                for f in fixed["posts"]:
                    posts = out.get(f["lang"], [])
                    if 0 <= f["index"] < len(posts) and x_weighted_length(f["text"]) < x_weighted_length(posts[f["index"]]["text"]):
                        posts[f["index"]]["text"] = f["text"]
            except LLMError as e:
                log.warning("thread shortening failed, trimming instead: %s", e)
        for lang in ("zh", "en"):
            for p in out.get(lang, []):
                p["text"] = trim_to_x_limit(p["text"])


def _normalize_scenes(script: dict, scenes: list[dict]) -> dict:
    """Force scene order/ids to match the plan even if the model reorders or drops one."""
    by_id = {s.get("id"): s for s in script.get("scenes", [])}
    fixed = []
    for sc in scenes:
        s = by_id.get(sc["id"]) or {"id": sc["id"], "title": "", "bullets": [], "narration": ""}
        s["type"] = sc["type"]
        fixed.append(s)
    script["scenes"] = fixed
    return script


X_TARGET = 260


def trim_to_x_limit(text: str, limit: int = 280) -> str:
    """Drop trailing sentences until the post fits; hard-cut with an ellipsis if a single sentence is too long."""
    import re
    if x_weighted_length(text) <= limit:
        return text
    parts = re.split(r"(?<=[。！？.!?；;])\s*", text)
    while len(parts) > 1 and x_weighted_length("".join(parts)) > limit:
        parts.pop()
    text = " ".join(parts).strip() if all(ord(c) < 0x2E80 for c in text[:20]) else "".join(parts)
    while x_weighted_length(text + "…") > limit:
        text = text[:-1]
    return text if x_weighted_length(text) <= limit else text + "…"


def x_weighted_length(text: str) -> int:
    """X counts CJK, fullwidth punctuation and emoji as 2, URLs as 23, everything else as 1."""
    import re
    n = 0
    text = re.sub(r"https?://\S+", "x" * 23, text)
    for ch in text:
        cp = ord(ch)
        if cp <= 0x10FF or 0x2000 <= cp <= 0x200D or 0x2010 <= cp <= 0x201F or 0x2032 <= cp <= 0x2037:
            n += 1
        else:
            n += 2 if unicodedata.category(ch) != "Mn" else 0
    return n
