# InfoStation — agent guide

Automated US-stock + crypto market intel → bilingual (zh/en) 16:9 videos + X threads. Uploading is manual.
Read `docs/PLAN.md` for the design rationale.

## Run it

```bash
uv run infostation doctor                 # check tools + every data source
uv run infostation run                    # full pipeline, session from config (auto)
uv run infostation run --session recap --date 2026-10-16 --force
uv run infostation run --from write       # re-run from a step (keeps earlier outputs)
uv run infostation run --only render      # one step
uv run infostation runs                   # list runs
uv run infostation studio <run_id> --lang zh   # Remotion Studio on a run's props
uv run pytest -q
```

Two sessions per trading day, chosen by New York time (`market_calendar.plan_session`, `session: auto`):
- `recap` (after 16:15 ET; timer 17:00 ET): `collect → screen → edit → write → voice → visuals → render → package`.
  Output `runs/<date>_recap/upload/{zh,en}/` (video.mp4, thumbnail.png, captions.srt, youtube.md, x_thread.md, cards/).
  Includes an "after-hours earnings" scene when companies reported after the close (`Run._after_hours`).
- `premarket` (before 09:30 ET; timer 07:30 ET): X thread + cards only, `src/infostation/premarket.py`:
  `collect → write → render → package` → `runs/<date>_premarket/upload/{zh,en}/` (x_thread.md, cards/).
Both write `runs/<id>/review.md`.

## Layout

- `src/infostation/collectors/` — one module per free source; each degrades gracefully and never raises on a single-source failure
- `src/infostation/analysis/` — metrics, funnel screener, data-pack views
- `src/infostation/llm/agy.py` — the only LLM entry point: `agy -p --json-schema`, model fallback list in `config/config.yaml`
- `src/infostation/prompts/` — editor / script / thread prompts (content quality lives here)
- `src/infostation/writing/factcheck.py` — every spoken number must trace to the data pack
- `src/infostation/media/tts.py` — local IndexTTS-2.5 per sentence (repo `~/workspace/audio/index-tts`, own venv, run via
  `tools/indextts_batch.py`), cached in `data/cache/tts/`; edge-tts fallback. Speaker prompts in `voices/`
- `src/infostation/media/captions.py` — subtitle layout (jieba, atomic numbers, clause rules, en two-line) + Whisper timing
- `tools/voicelab/` — Qwen3-TTS VoiceDesign env to invent new synthetic narrator voices (never clone real people)
- `src/infostation/media/` (rest) — ComfyUI background, Remotion props + render
- `video/` — Remotion templates (TypeScript). Python precomputes all numbers; templates only lay out/animate
- `src/infostation/timefmt.py` — every viewer-facing time: New York first, then Los Angeles / Beijing (`time_zones` in config)
- `data/market_memory.duckdb` — history store, grows every run (prices, mentions, sentiment, filings, insider trades)

## Rules when changing things

- Numbers shown or spoken must come from collected data. Never let the LLM produce figures that bypass `factcheck`.
- A data source failing must not stop the pipeline: catch `SourceError`, log, record health via `Run.health()`.
- Respect source limits: SEC needs `SEC_USER_AGENT` with an email and ≤10 req/s (throttled in `http.py`).
- Keep prompts' hard rules (no buy/sell advice, attribute news, digits not words).
- Times: schedule and reason in New York time. Never let the LLM convert time zones; give it preformatted
  `time_zh` / `time_en` / `spoken_*` strings from `timefmt`. After-hours / pre-market quotes must be labelled as such.
- Captions: never dump raw text; any change to line breaking must keep `tests/test_captions.py` passing.
- huggingface.co is DNS-poisoned on this network: download models via ModelScope / hf-mirror (`scripts/setup_tts.sh`).
- After editing `video/src`, run `cd video && npx tsc --noEmit`; after Python changes run `uv run pytest -q`.

## When a scheduled run fails

1. Open the newest `data/logs/*.log` and `runs/<id>/run.log`; `runs/<id>/state.json` shows completed steps and source health.
2. Run `uv run infostation doctor` to see which source broke.
3. Fix the collector (sites change their formats), add/adjust a test, then `uv run infostation run --from <failed step>`.
