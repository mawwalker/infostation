"""Voice-over + caption timing.

Pipeline per language:
  narration → sentences → spoken text → TTS per sentence (cached by content hash)
  → trim silence, level-match → concatenate with natural pauses → scene WAV
  → Whisper word timestamps per sentence → caption cues (media/captions.py)

Providers
- indextts: IndexTTS-2.5 run locally from its own repo/venv (tools/indextts_batch.py), speaker = reference WAV.
- edge:     Microsoft edge-tts (online, free); kept as a fallback.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from ..config import CACHE_DIR, ROOT, Settings
from . import captions

log = logging.getLogger(__name__)

SR = 24000
_ABBR = r"(?<!\bU\.S)(?<!\bInc)(?<!\bCorp)(?<!\bMr)(?<!\bMs)(?<!\bDr)(?<!\bvs)(?<!\bSt)(?<!\bJr)(?<!\be\.g)(?<!\bi\.e)(?<!\bNo)"


def split_sentences(text: str, lang: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if lang == "zh":
        parts = re.split(r"(?<=[。！？!?；;])(?![”’」』）)])", text)
    else:
        parts = re.split(_ABBR + r"(?<=[.!?])[”\"’)]?\s+(?=[A-Z$“\"(0-9])", text)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if out and len(p) < (4 if lang == "zh" else 12):     # don't leave tiny fragments on their own
            out[-1] += ("" if lang == "zh" else " ") + p
        else:
            out.append(p)
    return out


def normalize_for_speech(text: str, lang: str) -> str:
    text = re.sub(r"\$([A-Z]{1,5})\b", r"\1", text)                      # $NVDA → NVDA
    if lang == "zh":
        text = re.sub(r"(\d(?:\.\d+)?)\s*[xX×](?![A-Za-z])", r"\1倍", text)
        text = text.replace("S&P", "标普").replace("　", "，")
    else:
        text = re.sub(r"(\d(?:\.\d+)?)\s*[xX×](?![A-Za-z])", r"\1 times", text)
        text = text.replace("S&P", "S and P").replace("&", " and ")
        text = re.sub(r"(\d),(\d{3})", r"\1\2", text)                      # 81,427 → 81427 for the normalizer
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- audio helpers

def _load(path: Path, tempo: float = 1.0) -> np.ndarray:
    if abs(tempo - 1.0) > 1e-3:                     # pitch-preserving speed change (WSOLA)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-af", f"atempo={tempo}", "-f", "f32le",
                              "-ac", "1", "-ar", str(SR), "-"], capture_output=True, check=True).stdout
        return np.frombuffer(raw, dtype=np.float32).copy()
    if path.suffix == ".wav":
        y, sr = sf.read(path, dtype="float32", always_2d=False)
    else:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                             capture_output=True, check=True).stdout
        return np.frombuffer(raw, dtype=np.float32).copy()
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != SR:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                             capture_output=True, check=True).stdout
        y = np.frombuffer(raw, dtype=np.float32).copy()
    return y


def trim_silence(y: np.ndarray, top_db: float = 42.0, pad: float = 0.04) -> np.ndarray:
    frame = int(0.02 * SR)
    if len(y) < frame * 3:
        return y
    n = len(y) // frame
    rms = np.sqrt(np.mean(y[: n * frame].reshape(n, frame) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms / (rms.max() + 1e-12))
    idx = np.where(db > -top_db)[0]
    if not len(idx):
        return y
    a = max(0, idx[0] * frame - int(pad * SR))
    b = min(len(y), (idx[-1] + 1) * frame + int(pad * SR))
    return y[a:b]


def level(y: np.ndarray, target_dbfs: float = -19.0) -> np.ndarray:
    """Match speech loudness across sentences (RMS over voiced frames), with a soft peak ceiling."""
    frame = int(0.02 * SR)
    n = len(y) // frame
    if n < 3:
        return y
    rms = np.sqrt(np.mean(y[: n * frame].reshape(n, frame) ** 2, axis=1))
    voiced = rms[rms > rms.max() * 0.1]
    cur = 20 * np.log10(np.sqrt(np.mean(voiced ** 2)) + 1e-9)
    y = y * (10 ** ((target_dbfs - cur) / 20))
    peak = np.abs(y).max()
    return y * (0.95 / peak) if peak > 0.95 else y


def to_16k(y: np.ndarray, sr: int = SR) -> np.ndarray:
    if sr == 16000:
        return y.astype(np.float32)
    n = int(round(len(y) * 16000 / sr))
    return np.interp(np.linspace(0, len(y) - 1, n), np.arange(len(y)), y).astype(np.float32)


def _fade(y: np.ndarray, ms: float = 12) -> np.ndarray:
    k = min(len(y) // 2, int(SR * ms / 1000))
    if k > 1:
        ramp = np.linspace(0, 1, k, dtype=np.float32)
        y[:k] *= ramp
        y[-k:] *= ramp[::-1]
    return y


# ---------------------------------------------------------------- providers

def _cache_key(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:20]


def _voice_path(s: Settings, lang: str) -> Path:
    p = Path(os.path.expanduser(str(s.get(f"tts.voices.{lang}"))))
    return p if p.is_absolute() else ROOT / p


def synth_indextts(s: Settings, items: list[dict], job_path: Path) -> None:
    repo = Path(os.path.expanduser(s.get("tts.indextts.repo", "~/workspace/audio/index-tts")))
    py = repo / ".venv" / "bin" / "python"
    if not py.exists():
        raise RuntimeError(f"IndexTTS venv not found at {py} (cd {repo} && uv sync)")
    job_path.write_text(json.dumps({"model_dir": "checkpoints", "bf16": bool(s.get("tts.indextts.bf16", True)),
                                    "items": items}, ensure_ascii=False), encoding="utf-8")
    env = dict(os.environ, HF_ENDPOINT=s.env.get("HF_ENDPOINT", "https://hf-mirror.com"), HF_HUB_DISABLE_XET="1",
               USE_MODELSCOPE=s.env.get("USE_MODELSCOPE", "1"),
               PYTHONUNBUFFERED="1")
    proc = subprocess.Popen([str(py), str(ROOT / "tools" / "indextts_batch.py"), str(job_path)], cwd=repo, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    last = 0
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        tail = (tail + [line.rstrip()])[-30:]
        if not line.startswith("{"):
            continue
        ev = json.loads(line)
        if ev["event"] in ("start", "loaded", "done"):
            log.info("indextts %s", {k: v for k, v in ev.items() if k != "event"} | {"event": ev["event"]})
        elif ev["event"] == "item" and ev["n"] - last >= 20:
            last = ev["n"]
            log.info("indextts %d/%d", ev["n"], ev["of"])
        elif ev["event"] == "error":
            log.warning("indextts error: %s", ev)
    if proc.wait() != 0:
        missing = [it for it in items if not Path(it["out"]).exists()]
        if missing:
            raise RuntimeError(f"IndexTTS failed for {len(missing)} sentences:\n" + "\n".join(tail))


def synth_edge(s: Settings, items: list[dict]) -> None:
    import edge_tts

    async def one(it: dict, sem: asyncio.Semaphore) -> None:
        async with sem:
            for attempt in range(4):
                try:
                    mp3 = Path(it["out"]).with_suffix(".mp3")
                    await edge_tts.Communicate(it["text"], it["edge_voice"], rate=it["edge_rate"]).save(str(mp3))
                    sf.write(it["out"], _load(mp3), SR)
                    mp3.unlink()
                    return
                except Exception as e:
                    log.warning("edge-tts attempt %d failed: %s", attempt + 1, e)
                    await asyncio.sleep(2 * (attempt + 1))
            raise RuntimeError(f"edge-tts failed: {it['text'][:40]}")

    async def main() -> None:
        sem = asyncio.Semaphore(4)
        await asyncio.gather(*(one(it, sem) for it in items))

    asyncio.run(main())


# ---------------------------------------------------------------- alignment

class Aligner:
    """Whisper word timestamps (CPU, int8) used only to place caption line breaks."""

    def __init__(self, model_name: str):
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        from faster_whisper import WhisperModel
        self.model = WhisperModel(model_name, device="cpu", compute_type="int8",
                                  cpu_threads=max(4, (os.cpu_count() or 8) // 2),
                                  download_root=str(CACHE_DIR / "whisper"))

    def words(self, y: np.ndarray, text: str, lang: str) -> list[tuple[str, float, float]]:
        y16 = to_16k(y)                             # faster-whisper expects 16 kHz mono float32
        segs, _ = self.model.transcribe(y16, language="zh" if lang == "zh" else "en", word_timestamps=True,
                                        initial_prompt=text, beam_size=1, vad_filter=False,
                                        condition_on_previous_text=False)
        out = []
        for seg in segs:
            for w in seg.words or []:
                out.append((w.word, float(w.start), float(w.end)))
        return out


# ---------------------------------------------------------------- main entry

def synthesize_all(s: Settings, scripts: dict[str, list[dict]], public_dir: Path, work_dir: Path) -> dict[str, list[dict]]:
    """scripts: {lang: scenes}. Returns {lang: [{id, audio, duration, captions}]} with audio relative to public/audio."""
    provider = s.get("tts.provider", "indextts")
    cache = CACHE_DIR / "tts"
    cache.mkdir(parents=True, exist_ok=True)
    plan: dict[str, list[dict]] = {}
    items: list[dict] = []
    for lang, scenes in scripts.items():
        voice = str(_voice_path(s, lang)) if provider == "indextts" else s.get(f"tts.edge_voices.{lang}")
        vtag = voice + (hashlib.sha1(Path(voice).read_bytes()).hexdigest()[:8] if provider == "indextts" else "")
        plan[lang] = []
        for sc in scenes:
            sens = []
            for sentence in split_sentences(sc.get("narration", ""), lang):
                spoken = normalize_for_speech(sentence, lang)
                out = cache / f"{provider}_{_cache_key(vtag, lang, spoken)}.wav"
                sens.append({"text": sentence, "spoken": spoken, "wav": out})
                if not out.exists() and not any(it["out"] == str(out) for it in items):
                    items.append({"text": spoken, "lang": "zhen" if lang == "zh" else "en", "spk": voice, "out": str(out),
                                  "emo_alpha": float(s.get("tts.indextts.emo_alpha", 1.0)),
                                  "edge_voice": s.get(f"tts.edge_voices.{lang}"),
                                  "edge_rate": s.get(f"tts.edge_rate.{lang}", "+0%")})
            plan[lang].append({"id": sc["id"], "sentences": sens})
    log.info("tts: %d sentences to synthesize (%s), %d cached", len(items), provider,
             sum(len(sc["sentences"]) for v in plan.values() for sc in v) - len(items))
    if items:
        if provider == "indextts":
            synth_indextts(s, items, work_dir / "indextts_job.json")
        else:
            synth_edge(s, items)

    aligner = Aligner(s.get("captions.whisper_model", "small")) if s.get("captions.align", "whisper") == "whisper" else None
    pause = float(s.get("tts.sentence_pause", 0.3))
    result: dict[str, list[dict]] = {}
    for lang, scenes in plan.items():
        out_dir = public_dir / "audio" / lang
        out_dir.mkdir(parents=True, exist_ok=True)
        result[lang] = []
        for sc in scenes:
            if not sc["sentences"]:
                continue
            chunks, sen_meta, words_all, t = [], [], [], 0.0
            tempo = float(s.get(f"tts.tempo.{lang}", 1.0))
            for k, sen in enumerate(sc["sentences"]):
                y = _fade(level(trim_silence(_load(sen["wav"], tempo))))
                dur = len(y) / SR
                sen_meta.append({"text": sen["text"], "start": t, "end": t + dur})
                if aligner:
                    try:
                        words_all.append([(w, a + t, b + t) for w, a, b in aligner.words(y, sen["spoken"], lang)] or None)
                    except Exception as e:
                        log.warning("alignment failed (%s); using estimated timing", e)
                        words_all.append(None)
                chunks.append(y)
                gap = pause + (0.12 if sen["text"].rstrip()[-1:] in "？！?!" else 0.0)
                if k < len(sc["sentences"]) - 1:
                    chunks.append(np.zeros(int(gap * SR), dtype=np.float32))
                    t += dur + gap
                else:
                    t += dur
            audio = np.concatenate(chunks)
            path = out_dir / f"{sc['id']}.wav"
            sf.write(path, audio, SR, subtype="PCM_16")
            cues = captions.build(sen_meta, lang, words_all if aligner else None)
            result[lang].append({"id": sc["id"], "audio": f"{lang}/{path.name}", "duration": len(audio) / SR,
                                 "captions": cues})
        log.info("voice %s: %.1f min", lang, sum(x["duration"] for x in result[lang]) / 60)
    return result
