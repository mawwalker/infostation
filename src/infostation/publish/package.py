"""Upload package: everything needed to publish by hand, plus a review checklist."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..media.render import DISCLAIMER

AI_NOTE = {
    "zh": "制作说明：数据由程序从公开来源（SEC EDGAR、交易所行情、ApeWisdom、Stocktwits、新闻 RSS 等）采集，"
          "脚本由 AI 辅助撰写并经程序化数字核对，配音为合成语音。",
    "en": "How this is made: data is collected from public sources (SEC EDGAR, market data, ApeWisdom, Stocktwits, news RSS); "
          "the script is AI-assisted and number-checked by code; the voice is synthetic.",
}


def _ts(sec: float, srt: bool = False) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if srt:
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"
    return f"{int(h)}:{int(m):02d}:{int(s):02d}" if h else f"{int(m):02d}:{int(s):02d}"


def chapters(props: dict) -> list[tuple[float, str]]:
    out, t = [], 0.0
    for sc in props["scenes"]:
        out.append((t, sc["chapter"]))
        t += sc["durationInFrames"] / props["fps"]
    return out


def srt(props: dict) -> str:
    lines, n, offset = [], 1, 0.0
    for sc in props["scenes"]:
        for c in sc["captions"]:
            lines += [str(n), f"{_ts(offset + c['start'], True)} --> {_ts(offset + c['end'], True)}", c["text"], ""]
            n += 1
        offset += sc["durationInFrames"] / props["fps"]
    return "\n".join(lines)


def youtube_md(lang: str, script: dict, props: dict, view: dict) -> str:
    zh = lang == "zh"
    chap = "\n".join(f"{_ts(t)} {name}" for t, name in chapters(props))
    sources = sorted({h["source"] for st in view.get("stories", []) for h in st.get("headlines", [])[:3] if h.get("source")})
    tickers = " ".join(f"#{st['symbol']}" for st in view.get("stories", []))
    desc = "\n\n".join([
        script["description"],
        ("章节\n" if zh else "Chapters\n") + chap,
        ("新闻来源：" if zh else "News sources: ") + ", ".join(sources) if sources else "",
        AI_NOTE[lang],
        DISCLAIMER[lang],
        tickers,
    ]).strip()
    return (f"# {'标题' if zh else 'Title'}\n\n{script['video_title']}\n\n"
            f"# {'简介' if zh else 'Description'}\n\n{desc}\n\n"
            f"# {'标签' if zh else 'Tags'}\n\n{', '.join(script.get('tags', []))}\n")


def thread_md(lang: str, posts: list[dict]) -> str:
    out = []
    for i, p in enumerate(posts, 1):
        warn = f"  ⚠️ {p.get('weighted_len')} > 280" if p.get("over_limit") else ""
        card = f"\n\n[image: cards/{p['card']}.png]" if p.get("card") else ""
        out.append(f"## {i}/{len(posts)}{warn}\n\n{p['text']}{card}")
    return "\n\n---\n\n".join(out) + "\n"


def build(run_dir: Path, lang: str, script: dict, props: dict, view: dict, posts: list[dict],
          video: Path, thumb: Path, cards: dict[str, Path]) -> Path:
    up = run_dir / "upload" / lang
    (up / "cards").mkdir(parents=True, exist_ok=True)
    shutil.copy2(video, up / "video.mp4")
    shutil.copy2(thumb, up / "thumbnail.png")
    (up / "captions.srt").write_text(srt(props), encoding="utf-8")
    (up / "youtube.md").write_text(youtube_md(lang, script, props, view), encoding="utf-8")
    used = {p["card"] for p in posts if p.get("card")}
    for cid, path in cards.items():
        if cid in used and path.exists():
            shutil.copy2(path, up / "cards" / f"{cid}.png")
    (up / "x_thread.md").write_text(thread_md(lang, posts), encoding="utf-8")
    (up / "metadata.json").write_text(json.dumps({
        "title": script["video_title"], "description_file": "youtube.md", "tags": script.get("tags", []),
        "language": lang, "made_for_kids": False, "altered_or_synthetic_content": False,
        "notes": "Synthetic voice reading data does not require the 'altered content' label; set it to true if you add realistic AI-generated people or scenes.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return up


def review_md(run_dir: Path, scripts: dict[str, dict], threads: dict[str, list[dict]], health: dict,
              editor: dict, durations: dict[str, float]) -> Path:
    lines = [f"# Review — {run_dir.name}", ""]
    lines.append("## Stories")
    for s in editor["stories"]:
        lines.append(f"- **{s['symbol']}** — {s['angle']}")
    lines += ["", f"Editor source: `{editor.get('source', 'llm')}`", "", "## Fact check"]
    for lang, sc in scripts.items():
        issues = sc.get("_factcheck", [])
        status = "✅ all numbers traced to data" if not issues else f"❌ {len(issues)} unverified numbers"
        lines.append(f"- **{lang}** ({sc.get('_source')}): {status}")
        lines += [f"  - {i}" for i in issues]
    lines += ["", "## X threads"]
    for lang, posts in threads.items():
        over = [i + 1 for i, p in enumerate(posts) if p.get("over_limit")]
        lines.append(f"- **{lang}**: {len(posts)} posts" + (f", ⚠️ over 280: {over}" if over else ""))
    lines += ["", "## Durations"] + [f"- {k}: {v / 60:.1f} min" for k, v in durations.items()]
    lines += ["", "## Data sources"]
    for k, v in health.items():
        lines.append(f"- {'✅' if v.get('ok') else '❌'} {k}: {v.get('detail', '')}")
    lines += ["", "## Before publishing", "- [ ] Watch the first 30 seconds and one story segment of each video",
              "- [ ] Check the thumbnail text reads correctly", "- [ ] Paste title / description / tags from `youtube.md`",
              "- [ ] Upload `captions.srt` as subtitles", "- [ ] Post `x_thread.md` with the attached cards", ""]
    p = run_dir / "review.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def thread_only(run_dir: Path, lang: str, posts: list[dict], cards: dict[str, Path]) -> Path:
    """Upload package for a thread-only run (pre-market brief): x_thread.md + the cards it uses."""
    up = run_dir / "upload" / lang
    if (up / "cards").exists():
        shutil.rmtree(up / "cards")
    (up / "cards").mkdir(parents=True)
    used = {p["card"] for p in posts if p.get("card")}
    for cid, path in cards.items():
        if cid in used and path.exists():
            shutil.copy2(path, up / "cards" / f"{cid}.png")
    (up / "x_thread.md").write_text(thread_md(lang, posts), encoding="utf-8")
    return up


def premarket_review(run_dir: Path, brief: dict, threads: dict[str, list[dict]], check: dict[str, list[str]],
                     health: dict) -> Path:
    lines = [f"# Review — {run_dir.name}", "", f"Data as of {brief['as_of']['en']}", "", "## Covered"]
    mv = brief["premarket_movers"]
    lines.append("- Overnight earnings: " + (", ".join(e["symbol"] for e in brief["earnings_overnight"]) or "none"))
    lines.append("- Pre-market movers: " + (", ".join(f"{m['symbol']} {m['change_pct']:+.2f}%" for m in mv["gainers"] + mv["losers"]) or "none"))
    lines.append("- Macro today: " + (", ".join(f"{e['event']} ({e['time_en']})" for e in brief["macro_today"]) or "none"))
    lines += ["", "## Fact check"]
    for lang, posts in threads.items():
        issues = check.get(lang, [])
        over = [i + 1 for i, p in enumerate(posts) if p.get("over_limit")]
        lines.append(f"- **{lang}**: {len(posts)} posts, " + ("✅ all numbers traced to data" if not issues else f"❌ {len(issues)} unverified")
                     + (f", ⚠️ over 280: {over}" if over else ""))
        lines += [f"  - {i}" for i in issues]
    lines += ["", "## Data sources"]
    for k, v in health.items():
        lines.append(f"- {'✅' if v.get('ok') else '❌'} {k}: {v.get('detail', '')}")
    lines += ["", "## Before posting", "- [ ] Read both threads once (pre-market quotes move fast — post before 9:30 ET)",
              "- [ ] Post `x_thread.md` with the attached cards", ""]
    p = run_dir / "review.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p
