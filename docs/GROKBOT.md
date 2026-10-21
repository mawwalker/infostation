# Operating InfoStation from Grok Bot

Grok Bot is an agent on its own Linux machine. It does not expose an HTTP LLM API. In `grokbot` mode each LLM step is a file handoff: the pipeline writes a request, exits, the agent writes the response, and the same command continues.

`agy` stays the default. Nothing in that path changes unless you opt in.

Premarket (X thread + cards) runs on a CPU-only box. Recap voice still needs a GPU (IndexTTS) or `tts.provider: edge`.

## One-time setup (Debian, no GPU)

```bash
sudo apt-get update && sudo apt-get install -y ffmpeg
# uv: https://docs.astral.sh/uv/  — Node.js 20+ as well (Remotion draws the cards; no GPU)
cd /path/to/auto_information_state
uv sync
(cd video && npm ci)          # first render also downloads a headless Chrome
cp .env.example .env
```

In `.env`:

```bash
SEC_USER_AGENT="Your Name you@example.com"   # required; SEC blocks requests without a contact email
INFOSTATION_LLM=grokbot                      # or pass --llm grokbot on every command
# X_BEARER_TOKEN=                            # leave unset; you will supply posts yourself
```

`uv run infostation doctor` must be green for ffmpeg, node, and the data sources you care about. These are warnings, not failures, on this box:

- `nvidia-smi`, IndexTTS, voice files — recap voice only
- ComfyUI — recap thumbnail background only
- `X API` — skipped until `X_BEARER_TOKEN` is set (`⏭️`, not `❌`)
- `agy` — not required when the provider is grokbot

Do not run the recap `voice` step here. Premarket never calls IndexTTS, Whisper, or ComfyUI.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | The run finished. Read `runs/<id>/review.md`. |
| 75 | Waiting. Read the request, write the response. |
| 76 | The response file is invalid. The message names the fields to fix. |
| other | A real failure (data source, render). See `runs/<id>/run.log`. |

75 and 76 are not failures. `runs/<id>/state.json` → `handoff.status` is `waiting` or `invalid`, and the step is not marked done.

## Premarket loop

Pick the trading day once and pass it every time. Before 09:30 ET, `--session premarket` with no date uses today; after the open it rolls to the next session, which would start a different run id mid-loop.

```bash
export INFOSTATION_LLM=grokbot
export SEC_USER_AGENT="Your Name you@example.com"
DATE=2026-10-22
RUN=${DATE}_premarket

uv run infostation run --session premarket --date "$DATE" --llm grokbot
# exit 75 — handoff/x_request.json lists cashtags, accounts, and the time window

uv run infostation handoff status --run "$RUN"
uv run infostation handoff path --run "$RUN"              # request to read
uv run infostation handoff path --run "$RUN" --response  # file to write

# search X for that request, then:
uv run infostation handoff submit --run "$RUN" --file /tmp/x_posts.json

# repeat until exit 0. The next wait is the thread (and, if fact-check or the
# length trim asks again, premarket_thread_rev1 / threads_shorten).
while true; do
  uv run infostation run --session premarket --date "$DATE" --llm grokbot && break
  code=$?
  if [ "$code" -eq 75 ] || [ "$code" -eq 76 ]; then
    uv run infostation handoff status --run "$RUN"
    # read the request, write JSON, then:
    uv run infostation handoff submit --run "$RUN" --file /tmp/response.json
  else
    exit "$code"
  fi
done
```

`handoff submit --file -` reads stdin. `handoff list` shows every recent run. `handoff status` with no `--run` prints the newest waiting run, or `status: idle`.

You can also write the response file yourself (the path from `handoff path --response`) and re-run; `submit` only validates and copies it into place. A schema error is printed and saved to `handoff/<name>.error.txt`.

After exit 0:

1. `runs/<date>_premarket/review.md` — fact-check, data-source health, and the X posts that were fed in.
2. `upload/zh/x_thread.md` and `upload/en/x_thread.md`, with `[image: cards/...]` pointing at `upload/<lang>/cards/`.
3. Post before 09:30 ET. Pre-market quotes go stale at the open.

A finished LLM answer is cached at `runs/<id>/llm/<name>/result.json`. Re-running the step reuses it. Delete that file (or `uv run infostation run --force`) to ask again. `--force` also drops `*.response.json` and refetches market data; it does not delete `inputs/x_posts.json`.

There may be more than one LLM handoff per session: the draft, a fact-check rewrite (`*_rev1`), and a shortening pass if a post is over the X weighted limit. Keep answering until exit 0. Fact-check still runs on your JSON. A number that is not in the market data comes back as another handoff (or as `❌` in `review.md` when rewrites are exhausted).

## Recap loop

Same handoff commands, with `--session recap`. Steps: `collect → screen → edit → write → voice → visuals → render → package`.

- `screen` emits `x_request` (watchlist, movers, cashtags, accounts, window) and waits in grokbot mode before it scores stories.
- `edit` / `write` then hand off `editor`, `script_zh`, `script_en`, and `threads`. Scripts are checked one language at a time.
- `voice` needs IndexTTS on a GPU. On this CPU box, stop after `write` or set `tts.provider: edge` (network TTS, no GPU) if you accept that voice. Do not expect `doctor` to require the GPU.

## Handoff files

### LLM request — `runs/<id>/handoff/<name>.request.json`

```json
{
  "kind": "llm",
  "name": "premarket_thread",
  "run_id": "2026-10-22_premarket",
  "prompt": "full prompt, including DATA",
  "schema": { "type": "object" },
  "response_file": "premarket_thread.response.json",
  "instructions": "Write one JSON object matching schema. No markdown."
}
```

Response: `runs/<id>/handoff/<name>.response.json` — the JSON object itself, not wrapped. Names you will see: `editor`, `script_zh`, `script_en`, `script_zh_rev1`, `threads`, `threads_shorten`, `premarket_thread`.

### X search request — `runs/<id>/handoff/x_request.json`

Written in grokbot mode before story selection. It is not an LLM answer. Fields:

| Field | Meaning |
| --- | --- |
| `time_window.start` / `end` | ISO 8601. Keep posts inside this window (previous close → now). |
| `cashtags` | `$NVDA`, … for the watchlist, movers, and liquid crypto. Futures (`ES=F`) are omitted. |
| `tickers` | Same symbols, plus ones that have no cashtag. |
| `accounts` | `@handles` from `x.accounts` in `config/config.yaml`. |
| `topics` | `premarket` or `recap`, plus `earnings` / `macro` when the snapshot has them. |
| `output_file` | Where to write the posts. |
| `schema` | The post file schema, copied so this file is enough on its own. |

### X posts — `runs/<id>/inputs/x_posts.json`

A bare array is accepted. Handles may be `@name` or `name`. `id` may be a number (it is stored as a string).

```json
{
  "posts": [
    {
      "id": "123",
      "url": "https://x.com/DeItaone/status/123",
      "author": {"handle": "DeItaone", "name": "Walter Bloomberg", "followers": 800000},
      "created_at": "2026-10-22T11:05:00Z",
      "text": "NVDA guidance ahead of the open",
      "metrics": {"likes": 10, "reposts": 2, "replies": 1, "quotes": 0, "impressions": 1000},
      "matched": {"ticker": "NVDA", "cashtag": "$NVDA", "topic": "premarket"}
    }
  ]
}
```

Required: `id`, `url`, `author.handle`, `created_at`, `text`. `matched.ticker` drives the buzz score (upper case, no `$`). If you omit it, a `$TICKER` in the text is used. `{"posts": []}` is valid and lets the run continue.

Optional inbox (`x.inbox` in config, unset by default): `<inbox>/<run_id>.json`, then `<inbox>/x_posts.json`. The per-run `inputs/x_posts.json` wins when both exist.

Posts are merged into screening (recap: an `X posts N` term on the score) and into the editor / script / thread prompts as quotable context. `review.md` has an **X posts** section with handle, ticker, url, and a snippet. Prompts require attribution. Fact-check ignores `x_posts` and `x_buzz`, so a figure that appears only in a tweet, or a like/follower count, does not pass.

## Optional API collector

If `X_BEARER_TOKEN` is set, recent search runs for the same cashtags and accounts (`https://api.x.com/2/tweets/search/recent`) and is merged with the file (the file wins on the same id). No token → source `x_api` is `skipped`. A token that fails is `failed` and, in grokbot mode, the pipeline still waits for the file. A search that succeeds does not wait; put the file in place before that run if you also want agent posts.

The token is read from the environment only. Do not put it in `config.yaml`.
