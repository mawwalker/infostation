from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RUNS_DIR = ROOT / "runs"
CACHE_DIR = DATA_DIR / "cache"
VIDEO_DIR = ROOT / "video"
ASSETS_DIR = ROOT / "assets"
PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass
class Settings:
    raw: dict[str, Any]
    env: dict[str, str] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def languages(self) -> list[str]:
        return list(self.raw.get("languages", ["zh", "en"]))

    @property
    def sec_user_agent(self) -> str:
        return self.env.get("SEC_USER_AGENT") or "InfoStation research admin@example.com"


def load_settings(config_path: Path | None = None) -> Settings:
    load_dotenv(ROOT / ".env")
    path = config_path or Path(os.environ.get("INFOSTATION_CONFIG", ROOT / "config" / "config.yaml"))
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    env = {k: v for k, v in os.environ.items() if v}
    for d in (DATA_DIR, RUNS_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    return Settings(raw=raw, env=env)
