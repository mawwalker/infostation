from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import typer

from .config import RUNS_DIR, VIDEO_DIR, load_settings

app = typer.Typer(add_completion=False, help="InfoStation — automated market intel → bilingual videos")


def _setup_logging(run_dir: Path | None = None, verbose: bool = False) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if run_dir:
        run_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(run_dir / "run.log", encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers, force=True,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    for noisy in ("yfinance", "urllib3", "peewee", "asyncio", "charset_normalizer", "faster_whisper", "jieba"):
        logging.getLogger(noisy).setLevel(logging.CRITICAL if noisy == "yfinance" else logging.WARNING)


@app.command()
def run(
    session: str = typer.Option(None, help="auto | recap | premarket (default from config)"),
    on: Optional[str] = typer.Option(None, "--date", help="trading day YYYY-MM-DD (default: decided by session)"),
    start: Optional[str] = typer.Option(None, "--from", help="re-run from this step onward"),
    only: Optional[str] = typer.Option(None, help="run a single step"),
    force: bool = typer.Option(False, help="redo all steps even if the run already completed"),
    langs: Optional[str] = typer.Option(None, help="comma-separated languages, e.g. zh or zh,en"),
    verbose: bool = typer.Option(False, "-v"),
) -> None:
    """Collect → screen → edit → write → voice → visuals → render → package."""
    from .market_calendar import plan_session
    from .pipeline import STEPS, Run, cleanup_old_runs

    s = load_settings()
    if langs:
        s.raw["languages"] = [x.strip() for x in langs.split(",") if x.strip()]
    for st in (start, only):
        if st and st not in STEPS:
            raise typer.BadParameter(f"unknown step {st}; choose from {STEPS}")
    plan = plan_session(session or s.get("session", "auto"), target=date.fromisoformat(on) if on else None)
    r = Run(s, plan)
    _setup_logging(r.dir, verbose)
    logging.getLogger("infostation").info("run %s (now ET %s)", plan.run_id, plan.now_et.strftime("%Y-%m-%d %H:%M"))
    out = r.execute(start=start, only=only, force=force)
    cleanup_old_runs(int(s.get("retention_days", 30)))
    typer.echo(f"\n✅ done → {out}\n   review: {r.dir / 'review.md'}")


@app.command()
def doctor() -> None:
    """Check tools, the agy CLI, and every free data source."""
    from .http import Http, SourceError

    s = load_settings()
    ok = True

    def line(name: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= good
        typer.echo(f"{'✅' if good else '❌'} {name:<22} {detail}")

    for tool in ("ffmpeg", "ffprobe", "node", "npm", s.get("llm.cli", "agy")):
        line(tool, shutil.which(tool) is not None, shutil.which(tool) or "not found in PATH")
    nm = (VIDEO_DIR / "node_modules").exists()
    line("video/node_modules", nm, "" if nm else "run: cd video && npm ci")
    if s.get("tts.provider", "indextts") == "indextts":
        import os
        repo = Path(os.path.expanduser(s.get("tts.indextts.repo", "~/workspace/audio/index-tts")))
        ok_env = (repo / ".venv" / "bin" / "python").exists() and (repo / "checkpoints" / "gpt.pth").exists()
        line("IndexTTS-2.5", ok_env, str(repo) if ok_env else f"missing venv or checkpoints in {repo} (see README)")
        ok_aux = (repo / "checkpoints" / "hf_cache" / "bigvgan" / "bigvgan_generator.pt").exists()
        line("IndexTTS aux models", ok_aux, "" if ok_aux else "w2v-bert / campplus / bigvgan not downloaded (see README)")
        for lang in s.languages:
            vp = Path(str(s.get(f"tts.voices.{lang}")))
            vp = vp if vp.is_absolute() else Path(__file__).resolve().parents[2] / vp
            line(f"voice ({lang})", vp.exists(), str(vp))
    line("SEC_USER_AGENT", "SEC_USER_AGENT" in s.env and "example.com" not in s.env.get("SEC_USER_AGENT", ""),
         s.env.get("SEC_USER_AGENT", "not set — copy .env.example to .env"))
    http = Http(s.sec_user_agent)
    probes = {
        "SEC EDGAR": "https://data.sec.gov/submissions/CIK0000320193.json",
        "ApeWisdom": "https://apewisdom.io/api/v1.0/filter/all-stocks/page/1",
        "Stocktwits": "https://api.stocktwits.com/api/2/streams/symbol/AAPL.json",
        "Nasdaq calendar": "https://api.nasdaq.com/api/calendar/earnings?date=" + date.today().isoformat(),
        "ForexFactory": "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        "Binance": "https://api.binance.com/api/v3/ping",
        "CoinGecko": "https://api.coingecko.com/api/v3/ping",
        "Fear&Greed": "https://api.alternative.me/fng/",
        "Google News": "https://news.google.com/rss/search?q=stocks&hl=en-US&gl=US&ceid=US:en",
    }
    for name, url in probes.items():
        try:
            http.get(url, timeout=15)
            line(name, True)
        except SourceError as e:
            line(name, False, str(e)[:80])
    try:
        import yfinance as yf
        h = yf.Ticker("SPY").history(period="5d")
        line("yfinance", not h.empty, f"{len(h)} bars")
    except Exception as e:
        line("yfinance", False, str(e)[:80])
    try:
        import requests
        r = requests.get(s.get("comfy.url") + "/health", timeout=5)
        line("ComfyUI (optional)", r.ok, s.get("comfy.url"))
    except Exception as e:
        typer.echo(f"⚠️  ComfyUI (optional)     unreachable — thumbnails will use a gradient ({str(e)[:50]})")
    try:
        p = subprocess.run([s.get("llm.cli", "agy"), "models"], capture_output=True, text=True, timeout=60)
        models = [m.split("\t")[0] for m in p.stdout.splitlines() if "\t" in m]
        missing = [m for m in s.get("llm.models") if m not in models]
        line("agy models", not missing, "missing: " + ", ".join(missing) if missing else ", ".join(s.get("llm.models")))
    except Exception as e:
        line("agy models", False, str(e)[:80])
    raise typer.Exit(0 if ok else 1)


@app.command("runs")
def list_runs() -> None:
    """List runs and their status."""
    for d in sorted(RUNS_DIR.glob("*_*"), reverse=True)[:20]:
        st = json.loads((d / "state.json").read_text()) if (d / "state.json").exists() else {}
        done = st.get("done", [])
        mark = "✅" if "package" in done else f"… {done[-1] if done else 'new'}"
        typer.echo(f"{d.name:<26} {mark}")


@app.command()
def studio(run_id: str, lang: str = "zh") -> None:
    """Open Remotion Studio on a run's props to tweak templates visually."""
    d = RUNS_DIR / run_id
    subprocess.run(["npx", "remotion", "studio", "src/index.ts", f"--props={d / f'props_{lang}.json'}",
                    f"--public-dir={d / 'public'}"], cwd=VIDEO_DIR)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
