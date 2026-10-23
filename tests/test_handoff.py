"""Grokbot handoff: request file, schema validation, and a premarket run that continues."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from infostation.cli import app
from infostation.config import load_settings
from infostation.llm.handoff import EXIT_INVALID, EXIT_WAITING, GrokbotClient, HandoffInvalid, HandoffPending
from infostation.writing.writer import Writer

runner = CliRunner()

SCHEMA = {
    "type": "object",
    "required": ["zh", "en"],
    "properties": {
        "zh": {"type": "string"},
        "en": {"type": "string"},
    },
}


def test_client_writes_request_then_validates(tmp_path: Path):
    client = GrokbotClient(tmp_path / "handoff", log_dir=tmp_path / "llm", run_id="demo")
    with pytest.raises(HandoffPending) as waiting:
        client.run("editor", "PROMPT pick 3 stories", SCHEMA)
    assert waiting.value.exit_code == EXIT_WAITING
    request = json.loads((tmp_path / "handoff" / "editor.request.json").read_text(encoding="utf-8"))
    assert request["prompt"] == "PROMPT pick 3 stories"
    assert request["schema"]["required"] == ["zh", "en"]
    assert request["kind"] == "llm"
    assert (tmp_path / "llm" / "editor" / "prompt.md").read_text(encoding="utf-8") == "PROMPT pick 3 stories"

    (tmp_path / "handoff" / "editor.response.json").write_text("{", encoding="utf-8")
    with pytest.raises(HandoffInvalid) as bad_json:
        client.run("editor", "PROMPT pick 3 stories", SCHEMA)
    assert bad_json.value.exit_code == EXIT_INVALID
    assert "not valid JSON" in str(bad_json.value)
    assert (tmp_path / "handoff" / "editor.error.txt").exists()

    (tmp_path / "handoff" / "editor.response.json").write_text(json.dumps({"zh": "好"}), encoding="utf-8")
    with pytest.raises(HandoffInvalid) as bad_schema:
        client.run("editor", "PROMPT pick 3 stories", SCHEMA)
    assert "en" in str(bad_schema.value)
    assert "schema" in str(bad_schema.value)

    good = {"zh": "好", "en": "ok"}
    (tmp_path / "handoff" / "editor.response.json").write_text(json.dumps(good), encoding="utf-8")
    assert client.run("editor", "PROMPT pick 3 stories", SCHEMA) == good
    # Cached: a later call in the same step does not ask again, even if the response file is gone.
    (tmp_path / "handoff" / "editor.response.json").unlink()
    assert client.run("editor", "PROMPT pick 3 stories", SCHEMA) == good


def test_grokbot_factcheck_rejects_a_number_that_exists_only_in_a_tweet(tmp_path: Path):
    settings = load_settings()
    settings.env.pop("INFOSTATION_LLM", None)
    settings.raw["llm"]["provider"] = "grokbot"
    settings.raw["factcheck"]["max_rewrites"] = 0
    settings.raw["languages"] = ["zh", "en"]
    view = {
        "date": "2026-10-21",
        "board": [{"symbol": "ES=F", "name_zh": "标普期货", "name_en": "S&P Futures",
                   "last": 5100.25, "change_pct": 0.35, "unit": "price"}],
        "x_posts": [{"text": "target 9999", "metrics": {"likes": 50}, "author": {"handle": "TestDesk"}}],
    }
    client = GrokbotClient(tmp_path / "handoff", log_dir=tmp_path / "llm", run_id="t")
    (tmp_path / "handoff").mkdir(parents=True)
    # Seed the answer the agent would have written, including a figure that is only in the tweet.
    answer = {
        "zh": [{"text": "有人喊到9999。不构成投资建议。", "card": None}],
        "en": [{"text": "A post says 9999. Not financial advice.", "card": None}],
    }
    (tmp_path / "handoff" / "premarket_thread.response.json").write_text(
        json.dumps(answer), encoding="utf-8")
    out = Writer(settings, client).premarket_threads(view, ["board"])
    assert out["_source"] == "llm"
    assert any("9999" in item for item in out["_factcheck"]["zh"])
    assert any("9999" in item for item in out["_factcheck"]["en"])


THREADS = {
    "zh": [{"text": "盘前：标普期货上涨0.35%。不构成投资建议。", "card": "board"}],
    "en": [{"text": "Pre-market: S&P futures up 0.35%. Not financial advice.", "card": "board"}],
}
POSTS = {"posts": [{
    "id": "99",
    "url": "https://x.com/TestDesk/status/99",
    "author": {"handle": "TestDesk", "name": "Test Desk", "followers": 1200},
    "created_at": "2026-10-21T11:00:00Z",
    "text": "NVDA discussion into the open, one account shouting 9999",
    "metrics": {"likes": 4, "reposts": 1, "replies": 0},
    "matched": {"ticker": "NVDA", "cashtag": "$NVDA", "topic": "premarket"},
}]}


def _install_stubs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("infostation.pipeline.RUNS_DIR", tmp_path)
    monkeypatch.setattr("infostation.cli.RUNS_DIR", tmp_path)
    monkeypatch.setattr("infostation.store.record_run", lambda *args, **kwargs: None)
    monkeypatch.setattr("infostation.store.query", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("INFOSTATION_LLM", raising=False)

    def live_quotes(symbols):
        return {sym: {"last": 5100.25, "change_pct": 0.35} for sym in symbols}

    def fetch_daily(symbols, http, period="3mo"):
        return pd.DataFrame({"symbol": pd.Series(dtype=str), "date": pd.Series(dtype="object"),
                             "close": pd.Series(dtype=float)})

    monkeypatch.setattr("infostation.premarket.prices.live_quotes", live_quotes)
    monkeypatch.setattr("infostation.premarket.prices.fetch_daily", fetch_daily)
    monkeypatch.setattr("infostation.premarket.prices.extended_quotes", lambda symbols: {})
    monkeypatch.setattr("infostation.premarket.events.reports", lambda *args, **kwargs: [])
    monkeypatch.setattr("infostation.premarket.events.macro", lambda *args, **kwargs: [])
    monkeypatch.setattr("infostation.premarket.news.ticker_news", lambda *args, **kwargs: [])
    monkeypatch.setattr("infostation.premarket.news.market_news",
                        lambda *args, **kwargs: [{"title": "Futures hold gains", "source": "Reuters"}])
    monkeypatch.setattr("infostation.premarket.crypto.collect", lambda *args, **kwargs: {
        "assets": [{"symbol": "BTC", "price": 60000.0, "change_pct": 1.2}],
        "fear_greed": {"value": 55, "label": "Greed"}, "global": {}, "funding": {}, "btc_history": [],
    })

    def fake_render(jobs, public, concurrency, jobfile):
        for job in jobs:
            path = Path(job["out"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"png")

    monkeypatch.setattr("infostation.premarket.render.run_remotion", fake_render)


def _run(*args: str):
    return runner.invoke(app, ["run", "--session", "premarket", "--date", "2026-10-21", "--llm", "grokbot", *args])


def test_grokbot_premarket_dry_run(tmp_path: Path, monkeypatch):
    """File handoff from collect through package, with network collectors stubbed."""
    _install_stubs(monkeypatch, tmp_path)
    run_id = "2026-10-21_premarket"

    first = _run()
    assert first.exit_code == EXIT_WAITING, first.stdout
    assert "x_request" in first.stdout
    assert (tmp_path / run_id / "handoff" / "x_request.json").exists()
    assert (tmp_path / run_id / "brief.json").exists()   # market snapshot kept for the resume

    status = runner.invoke(app, ["handoff", "status", "--run", run_id])
    assert status.exit_code == 0
    assert "status: waiting" in status.stdout
    assert "kind: x_request" in status.stdout
    request_path = runner.invoke(app, ["handoff", "path", "--run", run_id])
    assert request_path.stdout.strip().endswith("x_request.json")
    response_path = runner.invoke(app, ["handoff", "path", "--run", run_id, "--response"])
    assert response_path.stdout.strip().endswith("inputs/x_posts.json")

    bad = tmp_path / "bad_posts.json"
    bad.write_text(json.dumps({"posts": [{"id": "1"}]}), encoding="utf-8")
    rejected = runner.invoke(app, ["handoff", "submit", "--run", run_id, "--file", str(bad)])
    assert rejected.exit_code == EXIT_INVALID, rejected.stdout
    assert "text" in rejected.stdout

    good_posts = tmp_path / "x_posts.json"
    good_posts.write_text(json.dumps(POSTS), encoding="utf-8")
    accepted = runner.invoke(app, ["handoff", "submit", "--run", run_id, "--file", str(good_posts)])
    assert accepted.exit_code == 0, accepted.stdout

    second = _run()
    assert second.exit_code == EXIT_WAITING, second.stdout
    assert "premarket_thread" in second.stdout
    thread_req = json.loads((tmp_path / run_id / "handoff" / "premarket_thread.request.json").read_text(encoding="utf-8"))
    assert "9999" in thread_req["prompt"]          # the tweet is in the prompt
    assert thread_req["schema"]["required"] == ["zh", "en"]
    brief = json.loads((tmp_path / run_id / "brief.json").read_text(encoding="utf-8"))
    assert brief["x_posts"][0]["author"]["handle"] == "TestDesk"

    bad_thread = tmp_path / "bad_thread.json"
    bad_thread.write_text("{}", encoding="utf-8")
    rejected_thread = runner.invoke(app, ["handoff", "submit", "--run", run_id, "--file", str(bad_thread)])
    assert rejected_thread.exit_code == EXIT_INVALID
    assert "zh" in rejected_thread.stdout

    good_thread = tmp_path / "thread.json"
    good_thread.write_text(json.dumps(THREADS), encoding="utf-8")
    assert runner.invoke(app, ["handoff", "submit", "--run", run_id, "--file", str(good_thread)]).exit_code == 0

    finished = _run()
    assert finished.exit_code == 0, finished.stdout
    review = (tmp_path / run_id / "review.md").read_text(encoding="utf-8")
    assert "TestDesk" in review
    assert "https://x.com/TestDesk/status/99" in review
    assert "all numbers traced" in review
    assert "X_BEARER_TOKEN not set" in review
    assert "⏭️" in review
    check = json.loads((tmp_path / run_id / "thread_check.json").read_text(encoding="utf-8"))
    assert check["zh"] == [] and check["en"] == []
    health = json.loads((tmp_path / run_id / "state.json").read_text(encoding="utf-8"))["health"]["llm_threads"]
    assert health["ok"] is True
    assert health["detail"] == "grokbot"
    assert (tmp_path / run_id / "upload" / "zh" / "x_thread.md").exists()
    assert (tmp_path / run_id / "upload" / "en" / "x_thread.md").exists()
    listed = runner.invoke(app, ["handoff", "list"])
    assert run_id in listed.stdout
    assert "done" in listed.stdout


def _seed_run(tmp_path: Path, done: list[str], posts: bool) -> Path:
    run_id = "2026-10-21_premarket"
    d = tmp_path / run_id
    (d / "handoff").mkdir(parents=True)
    brief = {
        "session": "premarket", "date": "2026-10-21", "prev_session": "2026-10-20",
        "as_of": {"zh": "美东 7:30", "en": "7:30 a.m. ET"},
        "board": [{"symbol": "ES=F", "name_zh": "标普期货", "name_en": "S&P Futures",
                   "last": 5100.25, "change_pct": 0.35, "unit": "price"}],
        "earnings_overnight": [], "premarket_movers": {"gainers": [], "losers": []},
        "earnings_tonight": [], "macro_today": [],
        "crypto": {"assets": [], "fear_greed": None, "global": {}},
        "market_headlines": [], "previous_recap_theme": None,
    }
    (d / "brief.json").write_text(json.dumps(brief), encoding="utf-8")
    (d / "state.json").write_text(json.dumps({
        "done": done, "health": {}, "started": "2026-10-21T07:00:00",
        "finished": "2026-10-21T07:10:00",
    }), encoding="utf-8")
    if posts:
        (d / "inputs").mkdir()
        (d / "inputs" / "x_posts.json").write_text(json.dumps(POSTS), encoding="utf-8")
    return d


def test_force_clears_done_so_a_resume_collects_again(tmp_path: Path, monkeypatch):
    _install_stubs(monkeypatch, tmp_path)
    d = _seed_run(tmp_path, ["collect", "render"], posts=False)
    forced = _run("--force")
    assert forced.exit_code == EXIT_WAITING, forced.stdout
    state = json.loads((d / "state.json").read_text(encoding="utf-8"))
    assert state["done"] == []
    assert "finished" not in state
    assert state["handoff"]["name"] == "x_request"

    good_posts = tmp_path / "x_posts.json"
    good_posts.write_text(json.dumps(POSTS), encoding="utf-8")
    assert runner.invoke(app, ["handoff", "submit", "--run", d.name, "--file", str(good_posts)]).exit_code == 0
    resumed = _run()
    assert resumed.exit_code == EXIT_WAITING, resumed.stdout
    thread_req = json.loads((d / "handoff" / "premarket_thread.request.json").read_text(encoding="utf-8"))
    assert "9999" in thread_req["prompt"]
    state = json.loads((d / "state.json").read_text(encoding="utf-8"))
    assert "collect" in state["done"]
    assert "render" not in state["done"]


def test_write_merges_x_posts_when_collect_is_already_done(tmp_path: Path, monkeypatch):
    _install_stubs(monkeypatch, tmp_path)
    d = _seed_run(tmp_path, ["collect", "write", "render", "package"], posts=True)
    resumed = _run("--from", "write", "--force")
    assert resumed.exit_code == EXIT_WAITING, resumed.stdout
    state = json.loads((d / "state.json").read_text(encoding="utf-8"))
    assert state["done"] == ["collect"]
    assert state["handoff"]["name"] == "premarket_thread"
    brief = json.loads((d / "brief.json").read_text(encoding="utf-8"))
    assert brief["x_posts"][0]["text"].startswith("NVDA discussion")
    prompt = json.loads((d / "handoff" / "premarket_thread.request.json").read_text(encoding="utf-8"))["prompt"]
    assert "9999" in prompt


def test_submit_x_posts_while_a_thread_handoff_is_active(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("infostation.cli.RUNS_DIR", tmp_path)
    run_id = "2026-10-21_premarket"
    d = tmp_path / run_id
    (d / "handoff").mkdir(parents=True)
    request = d / "handoff" / "premarket_thread.request.json"
    request.write_text(json.dumps({"schema": SCHEMA}), encoding="utf-8")
    response = d / "handoff" / "premarket_thread.response.json"
    (d / "state.json").write_text(json.dumps({
        "done": ["collect"], "health": {},
        "handoff": {
            "status": "waiting", "step": "write", "name": "premarket_thread", "kind": "llm",
            "request": str(request), "response": str(response),
        },
    }), encoding="utf-8")
    posts = tmp_path / "posts.json"
    posts.write_text(json.dumps(POSTS), encoding="utf-8")

    named = runner.invoke(app, ["handoff", "submit", "--run", run_id, "--name", "x_request", "--file", str(posts)])
    assert named.exit_code == 0, named.stdout
    assert json.loads((d / "inputs" / "x_posts.json").read_text(encoding="utf-8"))["posts"][0]["id"] == "99"
    state = json.loads((d / "state.json").read_text(encoding="utf-8"))
    assert state["handoff"]["name"] == "premarket_thread"
    assert state["handoff"]["status"] == "waiting"

    # A posts file with no --name is detected as x_request, not checked against the thread schema.
    (d / "inputs" / "x_posts.json").unlink()
    detected = runner.invoke(app, ["handoff", "submit", "--run", run_id, "--file", str(posts)])
    assert detected.exit_code == 0, detected.stdout
    assert (d / "inputs" / "x_posts.json").exists()
    assert json.loads((d / "state.json").read_text(encoding="utf-8"))["handoff"]["name"] == "premarket_thread"

    wrong = runner.invoke(app, ["handoff", "submit", "--run", run_id, "--name", "premarket_thread", "--file", str(posts)])
    assert wrong.exit_code == EXIT_INVALID
    assert "zh" in wrong.stdout
