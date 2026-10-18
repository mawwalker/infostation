---
name: infostation-daily
description: Run the InfoStation market-video pipeline (US stocks + crypto → bilingual videos + X threads), check its output, and repair broken data sources. Use when asked to "跑今天的复盘/盘前", "生成今天的视频", "run the daily market video", or to fix a failed InfoStation run.
---

# InfoStation daily run

Project root: the directory containing `AGENTS.md` (read it first if you have not).

## 1. Run

```bash
uv run infostation run            # add --session recap|premarket, --date YYYY-MM-DD, --force as needed
```

A full run takes roughly 10–20 minutes (agy calls ≈ 3–5 min, TTS ≈ 1 min, Remotion render ≈ 5–10 min).
If it fails, read the last 40 lines of output, run `uv run infostation doctor`, fix the cause, then resume with
`uv run infostation run --from <failed step>`. Do not delete `runs/` or `data/`.

## 2. Check before reporting done

Read `runs/<id>/review.md` and verify:
- Fact check shows ✅ for each language. If ❌, read `runs/<id>/script_<lang>.json` `_factcheck` and decide:
  a wrong number → rerun `--from write`; a false positive (e.g. a date) → note it and improve `writing/factcheck.py`.
- No X post is over 280 weighted characters.
- Extract 3 frames from each video and look at them:
  `ffmpeg -ss 00:00:20 -i runs/<id>/upload/zh/video.mp4 -frames:v 1 /tmp/f1.png` (also ~40% and ~80% of the duration).
  Check text is not overflowing, Chinese renders (no tofu boxes), charts have data.
- Look at `upload/<lang>/thumbnail.png`.

## 3. Report

Tell the user: the run id, the three stories chosen, video durations, any ❌ in review.md, and the path
`runs/<id>/upload/`. Do not upload anything to YouTube or X.
