"""X post file parsing, schema errors, and skip-when-no-token."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from infostation.collectors.x import (
    XInputError, buzz_by_ticker, cashtag, load_x_posts, parse_x_posts, search_recent,
)
from infostation.config import load_settings
from infostation.llm.handoff import HandoffInvalid, HandoffPending
from infostation.market_calendar import plan_session
from infostation.pipeline import Run

POST = {
    "id": "99",
    "url": "https://x.com/TestDesk/status/99",
    "author": {"handle": "@TestDesk", "name": "Test Desk", "followers": 1200},
    "created_at": "2026-10-21T11:00:00Z",
    "text": "$NVDA chatter, someone yelling 9999",
    "metrics": {"likes": 10, "reposts": 2, "replies": 1, "quotes": 0, "impressions": 80},
    "matched": {"ticker": "nvda", "cashtag": "$NVDA", "topic": "premarket"},
}


def test_parse_accepts_object_bare_list_and_coerces_author():
    doc = parse_x_posts({"posts": [POST], "note": "ignored"})
    assert doc["posts"][0]["author"]["handle"] == "TestDesk"
    assert doc["posts"][0]["matched"]["ticker"] == "NVDA"
    brk = dict(POST)
    brk["matched"] = {"ticker": "BRK.B"}
    assert parse_x_posts({"posts": [brk]})["posts"][0]["matched"]["ticker"] == "BRK-B"
    assert parse_x_posts({"posts": [brk]})["posts"][0]["matched"]["cashtag"] == "$BRK.B"
    bare = dict(POST)
    bare["id"] = 100
    bare["author"] = "OtherDesk"
    bare.pop("matched")
    parsed = parse_x_posts([bare])
    assert parsed["posts"][0]["id"] == "100"
    assert parsed["posts"][0]["author"]["handle"] == "OtherDesk"
    assert parsed["posts"][0]["matched"]["ticker"] == "NVDA"


def test_schema_errors_name_the_field():
    with pytest.raises(XInputError) as exc:
        parse_x_posts({"posts": [{"id": "1", "url": "https://x.com/a/status/1", "author": {}}]})
    text = str(exc.value)
    assert "text" in text
    assert "handle" in text
    assert "created_at" in text


def test_invalid_json_file(tmp_path):
    path = tmp_path / "x_posts.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(XInputError) as exc:
        load_x_posts(path)
    assert "not valid JSON" in str(exc.value)


def test_cashtag_skips_futures():
    assert cashtag("NVDA") == "$NVDA"
    assert cashtag("BRK-B") == "$BRK.B"
    assert cashtag("ES=F") is None
    assert cashtag("^GSPC") is None


def test_buzz_counts_posts():
    posts = parse_x_posts({"posts": [POST]})["posts"]
    buzz = buzz_by_ticker(posts)
    assert buzz["NVDA"]["posts"] == 1
    assert buzz["NVDA"]["engagement"] == 13


def test_search_recent_maps_api_payload():
    payload = {
        "data": [{
            "id": "55", "text": "$NVDA higher", "author_id": "u1",
            "created_at": "2026-10-21T12:00:00Z",
            "public_metrics": {"like_count": 3, "retweet_count": 1, "reply_count": 0,
                               "quote_count": 0, "impression_count": 9},
        }],
        "includes": {"users": [{"id": "u1", "username": "DeItaone", "name": "Delta",
                                "public_metrics": {"followers_count": 10}}]},
    }

    seen = []

    class FakeHttp:
        def json(self, url, **kwargs):
            assert url.endswith("/tweets/search/recent")
            assert kwargs["headers"]["Authorization"] == "Bearer tok"
            seen.append(kwargs["params"]["query"])
            return payload

    start = datetime(2026, 10, 20, 20, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)
    posts = search_recent(FakeHttp(), "tok", ["NVDA"], ["DeItaone"], start, end, 10)
    assert any("$NVDA" in query for query in seen)
    assert any("from:DeItaone" in query for query in seen)
    assert posts[0]["author"]["handle"] == "DeItaone"
    assert posts[0]["metrics"]["likes"] == 3
    assert posts[0]["metrics"]["reposts"] == 1
    assert posts[0]["matched"]["ticker"] == "NVDA"
    assert posts[0]["url"] == "https://x.com/DeItaone/status/55"


def _run(tmp_path, monkeypatch, provider: str) -> Run:
    monkeypatch.setattr("infostation.pipeline.RUNS_DIR", tmp_path)
    monkeypatch.delenv("INFOSTATION_LLM", raising=False)
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    settings = load_settings()
    settings.env.pop("INFOSTATION_LLM", None)
    settings.env.pop("X_BEARER_TOKEN", None)
    settings.raw["llm"]["provider"] = provider
    plan = plan_session("premarket", target=date(2026, 10, 21))
    return Run(settings, plan)


def test_no_token_skips_and_does_not_call_api(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("API should not be called without X_BEARER_TOKEN")

    monkeypatch.setattr("infostation.collectors.x.search_recent", boom)
    run = _run(tmp_path, monkeypatch, "agy")
    assert run.resolve_x(["NVDA", "ES=F"], topics=["premarket"]) == []
    assert run.state["health"]["x_api"]["status"] == "skipped"
    assert "X_BEARER_TOKEN" in run.state["health"]["x_api"]["detail"]
    assert run.state["health"]["x_posts"]["status"] == "skipped"
    assert not (run.dir / "handoff" / "x_request.json").exists()


def test_grokbot_x_request_waits_then_invalid_then_accepts(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, "grokbot")
    with pytest.raises(HandoffPending) as waiting:
        run.resolve_x(["NVDA", "AAPL", "ES=F"], topics=["premarket", "earnings"])
    assert waiting.value.kind == "x_request"
    request = json.loads((run.dir / "handoff" / "x_request.json").read_text(encoding="utf-8"))
    assert "$NVDA" in request["cashtags"]
    assert "$AAPL" in request["cashtags"]
    assert "$ES" not in request["cashtags"]
    assert any("DeItaone" in account for account in request["accounts"])
    assert request["time_window"]["start"]
    assert request["schema"]["required"] == ["posts"]
    assert request["output_file"].endswith("inputs/x_posts.json")

    bad = run.dir / "inputs" / "x_posts.json"
    bad.write_text(json.dumps({"posts": [{"id": "1"}]}), encoding="utf-8")
    with pytest.raises(HandoffInvalid) as invalid:
        run.resolve_x(["NVDA"], topics=["premarket"])
    assert "text" in str(invalid.value)

    bad.write_text(json.dumps({"posts": [POST]}), encoding="utf-8")
    posts = run.resolve_x(["NVDA"], topics=["premarket"])
    assert posts[0]["matched"]["ticker"] == "NVDA"
    assert json.loads((run.dir / "x_used.json").read_text(encoding="utf-8"))[0]["id"] == "99"


def test_inbox_file_is_used_when_the_run_file_is_absent(tmp_path, monkeypatch):
    run = _run(tmp_path / "runs", monkeypatch, "agy")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / f"{run.plan.run_id}.json").write_text(json.dumps({"posts": [POST]}), encoding="utf-8")
    run.s.raw["x"]["inbox"] = str(inbox)
    posts = run.resolve_x(["NVDA"], topics=["premarket"])
    assert posts[0]["author"]["handle"] == "TestDesk"
    assert run.state["health"]["x_posts"]["status"] == "ok"
    assert "x_api" in run.state["health"] and run.state["health"]["x_api"]["status"] == "skipped"


def test_token_success_does_not_wait_for_a_file(tmp_path, monkeypatch):
    sample = parse_x_posts({"posts": [POST]})["posts"]

    def fake_search(*args, **kwargs):
        return sample

    monkeypatch.setattr("infostation.collectors.x.search_recent", fake_search)
    run = _run(tmp_path, monkeypatch, "grokbot")
    run.s.env["X_BEARER_TOKEN"] = "tok"
    posts = run.resolve_x(["NVDA"], topics=["premarket"])
    assert posts[0]["id"] == "99"
    assert run.state["health"]["x_api"]["status"] == "ok"
    assert (run.dir / "handoff" / "x_request.json").exists()
