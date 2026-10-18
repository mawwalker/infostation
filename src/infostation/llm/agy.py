"""LLM backend: Google Antigravity CLI (`agy -p --json-schema`).

Every call is one non-interactive turn: data is inlined in the prompt, structured output is enforced
by a JSON schema and validated again locally. Models are tried in order; each gets `retries` attempts.
Prompt, raw output and parsed result are saved under the run's llm/ directory for auditing.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import jsonschema

log = logging.getLogger(__name__)

# Linux caps a single argv string at 128 KiB; above this we hand the prompt over as a file.
INLINE_LIMIT = 100_000


class LLMError(RuntimeError):
    pass


class AgyClient:
    def __init__(self, models: list[str], timeout_sec: int = 300, retries: int = 2, cli: str = "agy",
                 log_dir: Path | None = None):
        self.models = models
        self.timeout = timeout_sec
        self.retries = retries
        self.cli = shutil.which(cli) or cli
        self.log_dir = log_dir

    def available(self) -> bool:
        return shutil.which(self.cli) is not None

    def run(self, name: str, prompt: str, schema: dict) -> dict:
        errors = []
        for model in self.models:
            for attempt in range(1, self.retries + 1):
                t0 = time.time()
                try:
                    result = self._call(name, prompt, schema, model)
                    jsonschema.validate(result, schema)
                    log.info("agy[%s] ok via %s in %.0fs", name, model, time.time() - t0)
                    self._save(name, "result.json", json.dumps(result, ensure_ascii=False, indent=2))
                    return result
                except (LLMError, jsonschema.ValidationError, subprocess.TimeoutExpired) as e:
                    msg = getattr(e, "message", None) or str(e)
                    errors.append(f"{model}#{attempt}: {msg[:300]}")
                    log.warning("agy[%s] %s attempt %d failed: %s", name, model, attempt, msg[:300])
        raise LLMError(f"all agy attempts failed for {name}: " + " | ".join(errors))

    def _call(self, name: str, prompt: str, schema: dict, model: str) -> dict:
        self._save(name, "prompt.md", prompt)
        with tempfile.TemporaryDirectory(prefix="agy_") as tmp:
            tmpdir = Path(tmp)
            schema_path = tmpdir / "schema.json"
            schema_path.write_text(json.dumps(schema, ensure_ascii=False))
            if len(prompt.encode()) > INLINE_LIMIT:
                (tmpdir / "task.md").write_text(prompt, encoding="utf-8")
                instruction = ("Read ./task.md in the current directory and complete the task it describes. "
                               "Do not modify any files. Your final structured output must be the task's answer.")
            else:
                instruction = prompt
            cmd = [self.cli, "-p", instruction, "--model", model, "--disable-slash-commands",
                   "--output-format", "json", "--json-schema", str(schema_path),
                   "--print-timeout", f"{self.timeout}s"]
            proc = subprocess.run(cmd, cwd=tmpdir, capture_output=True, text=True, timeout=self.timeout + 60)
        self._save(name, f"raw_{model}.json", proc.stdout or proc.stderr)
        if proc.returncode != 0:
            raise LLMError(f"exit {proc.returncode}: {(proc.stderr or proc.stdout)[-400:]}")
        try:
            env = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise LLMError(f"unparseable agy output: {proc.stdout[:200]}") from e
        if env.get("status") != "SUCCESS":
            raise LLMError(f"status={env.get('status')}: {str(env.get('response'))[:300]}")
        out = env.get("structured_output")
        if not isinstance(out, dict):
            out = _extract_json(env.get("response") or "")
        if not isinstance(out, dict):
            raise LLMError("no structured output in agy response")
        return out

    def _save(self, name: str, fname: str, content: str) -> None:
        if not self.log_dir:
            return
        d = self.log_dir / name
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_text(content, encoding="utf-8")


def _extract_json(text: str) -> dict | None:
    """Fallback: last top-level JSON object found in free text."""
    dec = json.JSONDecoder()
    found = None
    i = text.find("{")
    while i != -1:
        try:
            obj, end = dec.raw_decode(text, i)
            if isinstance(obj, dict):
                found = obj
            i = text.find("{", end)
        except json.JSONDecodeError:
            i = text.find("{", i + 1)
    return found
