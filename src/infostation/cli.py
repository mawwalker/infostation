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

from .collectors.x import XInputError, parse_x_posts
from .config import RUNS_DIR, VIDEO_DIR, load_settings
from .llm import resolve_provider
from .llm.handoff import EXIT_INVALID, HandoffInvalid, HandoffPending, schema_errors

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
    llm: Optional[str] = typer.Option(None, "--llm", help="agy | grokbot (overrides config and INFOSTATION_LLM)"),
    verbose: bool = typer.Option(False, "-v"),
) -> None:
    """recap: collect → screen → edit → write → voice → visuals → render → package.
    premarket (X thread + cards only): collect → write → render → package."""
    from .market_calendar import plan_session
    from .pipeline import cleanup_old_runs
    from .premarket import run_class

    s = load_settings()
    if llm:
        if llm.strip().lower() not in ("agy", "grokbot"):
            raise typer.BadParameter("--llm must be agy or grokbot")
        s.raw.setdefault("llm", {})["provider_override"] = llm.strip().lower()
    if langs:
        s.raw["languages"] = [x.strip() for x in langs.split(",") if x.strip()]
    plan = plan_session(session or s.get("session", "auto"), target=date.fromisoformat(on) if on else None)
    cls = run_class(plan.session)
    for st in (start, only):
        if st and st not in cls.STEPS:
            raise typer.BadParameter(f"unknown step {st} for {plan.session}; choose from {cls.STEPS}")
    r = cls(s, plan)
    _setup_logging(r.dir, verbose)
    logging.getLogger("infostation").info(
        "run %s provider %s (now ET %s)", plan.run_id, resolve_provider(s), plan.now_et.strftime("%Y-%m-%d %H:%M"))
    try:
        out = r.execute(start=start, only=only, force=force)
    except HandoffPending as e:
        typer.echo(f"\n⏸ {e}")
        raise typer.Exit(e.exit_code)
    except HandoffInvalid as e:
        typer.echo(f"\n❌ {e}")
        raise typer.Exit(e.exit_code)
    cleanup_old_runs(int(s.get("retention_days", 30)))
    typer.echo(f"\n✅ done → {out}\n   review: {r.dir / 'review.md'}")


@app.command()
def doctor() -> None:
    """Check tools, the agy CLI, and every free data source."""
    from .http import Http, SourceError

    s = load_settings()
    ok = True
    provider = resolve_provider(s)

    def line(name: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= good
        typer.echo(f"{'✅' if good else '❌'} {name:<22} {detail}")

    def warn(name: str, good: bool, detail: str = "") -> None:
        """Shown, but does not fail the check. Used for GPU/TTS (recap only) and other optional pieces."""
        typer.echo(f"{'✅' if good else '⚠️ '} {name:<22} {detail}")

    for tool in ("ffmpeg", "ffprobe", "node", "npm"):
        line(tool, shutil.which(tool) is not None, shutil.which(tool) or "not found in PATH")
    if provider == "agy":
        cli_name = s.get("llm.cli", "agy")
        line(cli_name, shutil.which(cli_name) is not None, shutil.which(cli_name) or "not found in PATH")
    else:
        warn("agy", shutil.which(s.get("llm.cli", "agy")) is not None,
             "not required when llm.provider=grokbot")
    nm = (VIDEO_DIR / "node_modules").exists()
    line("video/node_modules", nm, "" if nm else "run: cd video && npm ci")
    smi = shutil.which("nvidia-smi")
    if not smi:
        warn("nvidia-smi", False, "no GPU — recap voice needs one; premarket does not")
    else:
        try:
            p = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=15)
            gpu = (p.stdout or p.stderr or "").strip().splitlines()
            warn("nvidia-smi", p.returncode == 0, gpu[0][:80] if gpu else "no devices")
        except Exception as e:
            warn("nvidia-smi", False, str(e)[:80])
    if s.get("tts.provider", "indextts") == "indextts":
        import os
        repo = Path(os.path.expanduser(s.get("tts.indextts.repo", "~/workspace/audio/index-tts")))
        ok_env = (repo / ".venv" / "bin" / "python").exists() and (repo / "checkpoints" / "gpt.pth").exists()
        warn("IndexTTS-2.5", ok_env, (str(repo) if ok_env else f"missing — recap only; premarket skips voice ({repo})"))
        ok_aux = (repo / "checkpoints" / "hf_cache" / "bigvgan" / "bigvgan_generator.pt").exists()
        warn("IndexTTS aux models", ok_aux, "" if ok_aux else "recap only — w2v-bert / campplus / bigvgan not downloaded")
        for lang in s.languages:
            vp = Path(str(s.get(f"tts.voices.{lang}")))
            vp = vp if vp.is_absolute() else Path(__file__).resolve().parents[2] / vp
            warn(f"voice ({lang})", vp.exists(), str(vp) if vp.exists() else "recap only")
    else:
        warn("tts", True, f"provider={s.get('tts.provider')} (no local GPU model)")
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
        warn("ComfyUI (optional)", r.ok, s.get("comfy.url"))
    except Exception as e:
        typer.echo(f"⚠️  ComfyUI (optional)     unreachable — thumbnails will use a gradient ({str(e)[:50]})")
    if provider == "agy":
        try:
            p = subprocess.run([s.get("llm.cli", "agy"), "models"], capture_output=True, text=True, timeout=60)
            models = [m.split("\t")[0] for m in p.stdout.splitlines() if "\t" in m]
            missing = [m for m in s.get("llm.models") if m not in models]
            line("agy models", not missing, "missing: " + ", ".join(missing) if missing else ", ".join(s.get("llm.models")))
        except Exception as e:
            line("agy models", False, str(e)[:80])
    else:
        warn("llm provider", True, "grokbot — LLM steps write handoff files (see docs/GROKBOT.md)")
    token = s.env.get("X_BEARER_TOKEN")
    if not token:
        typer.echo(f"⏭️  {'X API':<22} skipped — no X_BEARER_TOKEN (use runs/<id>/inputs/x_posts.json)")
    else:
        try:
            http.get("https://api.x.com/2/tweets/search/recent",
                     params={"query": "from:X", "max_results": 10},
                     headers={"Authorization": f"Bearer {token}"}, timeout=15)
            line("X API", True, "recent search")
        except SourceError as e:
            line("X API", False, str(e)[:80])
    raise typer.Exit(0 if ok else 1)


@app.command("runs")
def list_runs() -> None:
    """List runs and their status."""
    for d in sorted(RUNS_DIR.glob("*_*"), reverse=True)[:20]:
        st = json.loads((d / "state.json").read_text()) if (d / "state.json").exists() else {}
        done = st.get("done", [])
        hof = st.get("handoff") or {}
        if hof.get("status") in {"waiting", "invalid"} and "package" not in done:
            mark = f"⏸ {hof.get('status')} {hof.get('name')}"
        else:
            mark = "✅" if "package" in done else f"… {done[-1] if done else 'new'}"
        typer.echo(f"{d.name:<26} {mark}")


def _read_state(run_dir: Path) -> dict:
    path = run_dir / "state.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _waiting_runs() -> list[Path]:
    if not RUNS_DIR.exists():
        return []
    found = []
    for d in sorted((p for p in RUNS_DIR.glob("*_*") if p.is_dir()), reverse=True):
        if (_read_state(d).get("handoff") or {}).get("status") in {"waiting", "invalid"}:
            found.append(d)
    return found


def _pick_run(run_id: str | None, required: bool) -> Path | None:
    if run_id:
        d = RUNS_DIR / run_id
        if not d.is_dir():
            raise typer.BadParameter(f"no run directory {d}")
        return d
    waiting = _waiting_runs()
    if waiting:
        return waiting[0]
    if required:
        raise typer.BadParameter("no run is waiting on a handoff; pass --run RUN_ID")
    return None


handoff_app = typer.Typer(add_completion=False, help="Grokbot file handoff: status, list, path, submit")
app.add_typer(handoff_app, name="handoff")


@handoff_app.command("status")
def handoff_status(run: Optional[str] = typer.Option(None, "--run", help="run id (default: newest waiting run)")) -> None:
    """Show the handoff the agent must answer, or `status: idle`."""
    d = _pick_run(run, required=False)
    if d is None:
        typer.echo("status: idle")
        return
    hof = _read_state(d).get("handoff") or {}
    if not hof:
        typer.echo(f"status: idle\nrun_id: {d.name}")
        return
    typer.echo(f"status: {hof.get('status', 'idle')}")
    typer.echo(f"kind: {hof.get('kind', '')}")
    typer.echo(f"name: {hof.get('name', '')}")
    typer.echo(f"step: {hof.get('step', '')}")
    typer.echo(f"run_id: {d.name}")
    typer.echo(f"request: {hof.get('request', '')}")
    typer.echo(f"response: {hof.get('response', '')}")
    if hof.get("detail"):
        typer.echo(f"detail:\n{hof['detail']}")
    err = d / "handoff" / f"{hof.get('name', '')}.error.txt"
    if err.exists():
        typer.echo(f"error_file: {err}")


@handoff_app.command("list")
def handoff_list() -> None:
    """List recent runs and any handoff that is waiting or invalid."""
    if not RUNS_DIR.exists() or not any(RUNS_DIR.glob("*_*")):
        typer.echo("(no runs)")
        return
    for d in sorted((p for p in RUNS_DIR.glob("*_*") if p.is_dir()), reverse=True)[:30]:
        st = _read_state(d)
        hof = st.get("handoff") or {}
        if hof.get("status") in {"waiting", "invalid"}:
            typer.echo(f"{d.name:<26} {hof['status']:<8} {hof.get('kind', '')} {hof.get('name', '')}")
        else:
            done = st.get("done") or []
            label = "done" if "package" in done else (done[-1] if done else "new")
            typer.echo(f"{d.name:<26} {label}")


@handoff_app.command("path")
def handoff_path(
    run: Optional[str] = typer.Option(None, "--run"),
    response: bool = typer.Option(False, "--response", help="print the file to write, instead of the request to read"),
) -> None:
    """Print the absolute request path (or the response path with --response)."""
    d = _pick_run(run, required=True)
    assert d is not None
    hof = _read_state(d).get("handoff") or {}
    target = hof.get("response" if response else "request")
    if not target:
        raise typer.BadParameter(f"{d.name} has no pending handoff")
    typer.echo(target)


@handoff_app.command("submit")
def handoff_submit(
    run: Optional[str] = typer.Option(None, "--run"),
    file: Optional[str] = typer.Option(None, "--file", help="response JSON path; '-' reads stdin"),
) -> None:
    """Validate a response and place it where the pipeline will read it on the next run."""
    d = _pick_run(run, required=True)
    assert d is not None
    st = _read_state(d)
    hof = st.get("handoff") or {}
    if hof.get("status") not in {"waiting", "invalid"}:
        raise typer.BadParameter(f"{d.name} is not waiting on a handoff")
    request, response = Path(hof["request"]), Path(hof["response"])
    text = sys.stdin.read() if file in (None, "-") else Path(file).read_text(encoding="utf-8")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        typer.echo(f"invalid handoff response: not JSON ({e})")
        raise typer.Exit(EXIT_INVALID)
    kind = hof.get("kind") or "llm"
    if kind == "x_request":
        try:
            doc = parse_x_posts(raw)
        except XInputError as e:
            _note_error(d, hof, str(e))
            typer.echo(str(e))
            raise typer.Exit(EXIT_INVALID)
        response.parent.mkdir(parents=True, exist_ok=True)
        response.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        if not request.exists():
            typer.echo(f"request file is missing: {request}")
            raise typer.Exit(EXIT_INVALID)
        schema = json.loads(request.read_text(encoding="utf-8")).get("schema")
        errors = schema_errors(raw, schema or {})
        if not schema or errors:
            detail = "schema validation failed:\n" + "\n".join(f"- {e}" for e in (errors or ["request has no schema"]))
            _note_error(d, hof, detail)
            typer.echo(detail)
            raise typer.Exit(EXIT_INVALID)
        response.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        cached = d / "llm" / str(hof.get("name")) / "result.json"
        if cached.exists():
            cached.unlink()
    err = d / "handoff" / f"{hof.get('name', '')}.error.txt"
    err.unlink(missing_ok=True)
    hof["status"] = "waiting"
    hof.pop("detail", None)
    st["handoff"] = hof
    (d / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    typer.echo(f"accepted → {response}")
    typer.echo("Re-run the same `infostation run --llm grokbot` command to continue.")


def _note_error(run_dir: Path, hof: dict, detail: str) -> None:
    err = run_dir / "handoff" / f"{hof.get('name', 'handoff')}.error.txt"
    err.parent.mkdir(parents=True, exist_ok=True)
    err.write_text(detail + "\n", encoding="utf-8")


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
