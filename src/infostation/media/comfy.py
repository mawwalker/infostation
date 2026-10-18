"""Optional background art from the LAN ComfyUI adapter (OpenAI-compatible /v1/images/generations).

Text is never generated here: titles and numbers are overlaid by Remotion so they are always exact.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path

import requests

log = logging.getLogger(__name__)

MOODS = {
    "up": "rising glowing lines and upward light trails, optimistic dawn glow on the horizon",
    "down": "stormy atmosphere, falling light trails, dramatic rim light and deep shadows",
    "flat": "calm still water reflecting holographic data panels, balanced symmetrical composition",
}


def background(url: str, model: str, mood: str, out: Path, seed_text: str, timeout: int = 180) -> Path | None:
    prompt = (
        "Cinematic wide background plate for a financial news show. Abstract holographic stock charts and "
        "floating candlestick shapes over a dark navy city skyline at night, deep blue and violet palette, "
        f"soft bokeh, volumetric light, {MOODS.get(mood, MOODS['flat'])}. Left half darker and emptier for text overlay. "
        "No text, no letters, no numbers, no logos, no people."
    )
    try:
        r = requests.post(f"{url.rstrip('/')}/v1/images/generations",
                          json={"model": model, "prompt": prompt, "size": "1344x768", "n": 1,
                                "seed": int(hashlib.md5(seed_text.encode()).hexdigest()[:8], 16)},
                          timeout=timeout)
        r.raise_for_status()
        b64 = r.json()["data"][0]["b64_json"]
    except Exception as e:
        log.warning("ComfyUI background failed (%s); continuing without it", e)
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(b64))
    return out
