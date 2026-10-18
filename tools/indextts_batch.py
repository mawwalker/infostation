"""Batch synthesis with IndexTTS-2.5. Runs inside the index-tts repo's own venv (torch + model deps).

    <index-tts>/.venv/bin/python tools/indextts_batch.py job.json      (cwd = index-tts repo)

job.json: {"model_dir": "checkpoints", "bf16": true,
           "items": [{"text": "...", "lang": "zhen", "spk": "/abs/voice.wav", "out": "/abs/out.wav",
                      "emo_alpha": 1.0, "emo_vector": null}]}
Items whose output already exists are skipped, so an interrupted job can simply be re-run.
Prints one JSON line per item for the caller to follow progress.
"""
import json
import os
import sys
import time


def main(job_path: str) -> int:
    job = json.load(open(job_path, encoding="utf-8"))
    todo = [it for it in job["items"] if not os.path.exists(it["out"])]
    print(json.dumps({"event": "start", "total": len(job["items"]), "todo": len(todo)}), flush=True)
    if not todo:
        return 0
    from indextts.infer_v2_5 import IndexTTS2

    model_dir = job.get("model_dir", "checkpoints")
    t0 = time.time()
    tts = IndexTTS2(cfg_path=os.path.join(model_dir, "config.yaml"), model_dir=model_dir,
                    use_bf16=job.get("bf16", True), use_cuda_kernel=False)
    print(json.dumps({"event": "loaded", "seconds": round(time.time() - t0, 1)}), flush=True)
    failed = 0
    for n, it in enumerate(todo, 1):
        t1 = time.time()
        tmp = it["out"] + ".part.wav"
        try:
            os.makedirs(os.path.dirname(it["out"]), exist_ok=True)
            tts.infer(spk_audio_prompt=it["spk"], text=it["text"], output_path=tmp, lang=it.get("lang", "zhen"),
                      emo_alpha=it.get("emo_alpha", 1.0), emo_vector=it.get("emo_vector"),
                      interval_silence=150, verbose=False)
            os.replace(tmp, it["out"])
            print(json.dumps({"event": "item", "n": n, "of": len(todo), "seconds": round(time.time() - t1, 2)}), flush=True)
        except Exception as e:  # keep going; the caller reports missing items
            failed += 1
            print(json.dumps({"event": "error", "n": n, "text": it["text"][:60], "error": str(e)[:300]}), flush=True)
    print(json.dumps({"event": "done", "failed": failed, "seconds": round(time.time() - t0, 1)}), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
