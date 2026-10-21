"""LLM backends. `agy` calls the Antigravity CLI; `grokbot` writes a file the agent fills in."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..config import Settings
from .agy import AgyClient, LLMError
from .handoff import EXIT_INVALID, EXIT_WAITING, GrokbotClient, HandoffInvalid, HandoffPending

__all__ = [
    "AgyClient", "EXIT_INVALID", "EXIT_WAITING", "GrokbotClient", "HandoffInvalid", "HandoffPending",
    "LLMClient", "LLMError", "make_client", "resolve_provider",
]

PROVIDERS = ("agy", "grokbot")


class LLMClient(Protocol):
    def run(self, name: str, prompt: str, schema: dict) -> dict: ...


def resolve_provider(settings: Settings) -> str:
    """CLI override, then INFOSTATION_LLM, then config `llm.provider`. Default is agy."""
    override = settings.get("llm.provider_override")
    if override:
        choice = str(override)
    elif settings.env.get("INFOSTATION_LLM"):
        choice = settings.env["INFOSTATION_LLM"]
    else:
        choice = str(settings.get("llm.provider") or "agy")
    choice = choice.strip().lower()
    if choice not in PROVIDERS:
        raise ValueError(f"llm.provider must be one of {PROVIDERS}, got {choice!r}")
    return choice


def make_client(settings: Settings, run_dir: Path) -> LLMClient:
    log_dir = run_dir / "llm"
    if resolve_provider(settings) == "grokbot":
        return GrokbotClient(handoff_dir=run_dir / "handoff", log_dir=log_dir, run_id=run_dir.name)
    return AgyClient(models=settings.get("llm.models"), timeout_sec=int(settings.get("llm.timeout_sec", 300)),
                     retries=int(settings.get("llm.retries", 2)), cli=settings.get("llm.cli", "agy"),
                     log_dir=log_dir)
