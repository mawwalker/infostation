"""File handoff for an external agent (Grok Bot).

Each LLM call writes `handoff/<name>.request.json` (prompt + JSON schema) and stops.
The agent writes `handoff/<name>.response.json`. The next run validates it and continues.
A valid result is cached at `llm/<name>/result.json` so a later call in the same step
(fact-check rewrite, thread shortening) does not ask for the same answer again.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import jsonschema

log = logging.getLogger(__name__)

EXIT_WAITING = 75   # request written; agent has not answered yet
EXIT_INVALID = 76   # response exists but is not valid JSON / does not match the schema


class HandoffPending(Exception):
    """The step cannot continue until the agent writes the response file."""

    exit_code = EXIT_WAITING

    def __init__(self, name: str, request: Path, response: Path, kind: str = "llm"):
        self.name = name
        self.request = Path(request)
        self.response = Path(response)
        self.kind = kind
        super().__init__("\n".join([
            f"waiting for agent ({kind}:{name})",
            f"request:  {self.request}",
            f"response: {self.response}",
            "Write the JSON response, then re-run the same `infostation run` command",
            "(or `infostation handoff submit --file <json>`).",
        ]))


class HandoffInvalid(Exception):
    """The agent responded, but the file is not usable. The step is not done."""

    exit_code = EXIT_INVALID

    def __init__(self, name: str, request: Path, response: Path, detail: str, kind: str = "llm"):
        self.name = name
        self.request = Path(request)
        self.response = Path(response)
        self.kind = kind
        self.detail = detail
        super().__init__("\n".join([
            f"invalid handoff response for {kind}:{name}",
            detail.rstrip(),
            f"request:  {self.request}",
            f"response: {self.response}",
            "Fix the response file and retry.",
        ]))


def schema_errors(instance: object, schema: dict, limit: int = 20) -> list[str]:
    validator = jsonschema.Draft202012Validator(schema)
    out = []
    for err in validator.iter_errors(instance):
        loc = "/".join(str(p) for p in err.absolute_path) or "(root)"
        out.append(f"{loc}: {err.message}")
        if len(out) >= limit:
            break
    return out


class GrokbotClient:
    def __init__(self, handoff_dir: Path, log_dir: Path | None = None, run_id: str = ""):
        self.handoff_dir = Path(handoff_dir)
        self.log_dir = Path(log_dir) if log_dir else None
        self.run_id = run_id

    def available(self) -> bool:
        return True

    def run(self, name: str, prompt: str, schema: dict) -> dict:
        self.handoff_dir.mkdir(parents=True, exist_ok=True)
        request = self.handoff_dir / f"{name}.request.json"
        response = self.handoff_dir / f"{name}.response.json"
        error_path = self.handoff_dir / f"{name}.error.txt"
        cached = self._cached(name, schema)
        if cached is not None:
            log.info("grokbot[%s] using cached result", name)
            return cached
        if response.exists():
            detail = _read_response(response, schema)
            if isinstance(detail, str):
                error_path.write_text(detail + "\n", encoding="utf-8")
                raise HandoffInvalid(name, request, response, detail)
            error_path.unlink(missing_ok=True)
            self._archive(name, prompt, detail)
            log.info("grokbot[%s] accepted %s", name, response.name)
            return detail
        payload = {
            "kind": "llm",
            "name": name,
            "run_id": self.run_id,
            "prompt": prompt,
            "schema": schema,
            "response_file": response.name,
            "instructions": (
                "You are the LLM step of InfoStation. Read `prompt` and answer it. "
                "Write a single JSON object that validates against `schema` to the response file "
                f"({response}). No markdown fences, no commentary. "
                "Every number in the answer must come from the DATA inside the prompt. "
                "Do not invent prices, percentages, or counts. "
                "If a sibling .error.txt exists, your previous file failed validation: fix it and overwrite the response."
            ),
        }
        request.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._save(name, "prompt.md", prompt)
        log.info("grokbot[%s] waiting — wrote %s", name, request)
        raise HandoffPending(name, request, response)

    def _cached(self, name: str, schema: dict) -> dict | None:
        if not self.log_dir:
            return None
        path = self.log_dir / name / "result.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if schema_errors(data, schema):
            return None
        return data

    def _archive(self, name: str, prompt: str, result: dict) -> None:
        self._save(name, "prompt.md", prompt)
        self._save(name, "result.json", json.dumps(result, ensure_ascii=False, indent=2))

    def _save(self, name: str, fname: str, content: str) -> None:
        if not self.log_dir:
            return
        d = self.log_dir / name
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_text(content, encoding="utf-8")


def _read_response(path: Path, schema: dict) -> dict | str:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return f"{path.name} is not valid JSON ({e}). The file must be one JSON object, not markdown."
    if not isinstance(data, dict):
        return f"{path.name} must be a JSON object, got {type(data).__name__}."
    errors = schema_errors(data, schema)
    if errors:
        return f"{path.name} does not match the schema:\n" + "\n".join(f"- {e}" for e in errors)
    return data
