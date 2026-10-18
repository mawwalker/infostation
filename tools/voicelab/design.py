"""Design synthetic narrator voices with Qwen3-TTS VoiceDesign (Apache-2.0).

The voices are invented from a text description, so they belong to no real person (no likeness / personality-rights
issue). Each output is a ~15 s clean reading used as the IndexTTS speaker prompt.

    cd tools/voicelab && .venv/bin/python design.py [--only zh_m_anchor] [--takes 2]
"""
import argparse
import json
from pathlib import Path

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "data" / "models" / "Qwen3-TTS-VoiceDesign"
OUT = ROOT / "voices" / "candidates"

ZH_TEXT = ("大家好，欢迎收看今天的节目。今晚美股的主线非常清楚：资金在撤离高估值的科技股，转而涌向能源和防御板块。"
           "接下来我们一条一条拆开来看，到底发生了什么，又意味着什么。")
EN_TEXT = ("Hi everyone, and welcome back. Tonight the story on Wall Street is pretty clear: money is rotating out of "
           "expensive tech and into energy and defensive names. Let's walk through what happened, and what it might mean.")

CANDIDATES = {
    "zh_m_anchor": ("Chinese", ZH_TEXT,
                    "35岁左右的男性财经节目主持人，普通话标准，声音低沉、有磁性、略带沙哑的质感，吐字清晰。"
                    "语气沉稳自信，像在和观众面对面聊天，自然口语化，有轻重缓急和自然的停顿，不是播音腔，不夸张。"),
    "zh_m_warm": ("Chinese", ZH_TEXT,
                  "40岁左右的男性资深财经评论员，声音浑厚温和、共鸣饱满，语速从容偏慢，娓娓道来，"
                  "像深夜财经节目里经验丰富的老朋友在分析市场，亲切可信，带一点点笑意。"),
    "zh_f_anchor": ("Chinese", ZH_TEXT,
                    "30岁左右的女性财经主持人，普通话标准，声音清亮温暖、干净利落，语速适中偏快，"
                    "专业但不刻板，语气自然亲切，像在给朋友讲今天的市场，有自然的节奏起伏。"),
    "zh_m_young": ("Chinese", ZH_TEXT,
                   "28岁左右的男性科技财经博主，声音明亮有活力、略带颗粒感，语速轻快，"
                   "表达自然随性、有感染力，像在录一期很受欢迎的播客，口语化，偶尔有轻微的强调。"),
    "en_m_host": ("English", EN_TEXT,
                  "A male American financial show host in his mid-30s. Warm, slightly husky baritone, clear diction. "
                  "Confident and conversational, relaxed but brisk pace, natural pauses and emphasis, "
                  "like a smart podcast host talking to a friend, not a formal announcer."),
    "en_f_reporter": ("English", EN_TEXT,
                      "A female American business reporter around 30. Bright, warm mid-range voice, crisp articulation, "
                      "friendly and composed, natural conversational rhythm with subtle emphasis, professional but not stiff."),
    "en_m_analyst": ("English", EN_TEXT,
                     "A male market analyst in his 40s with a gentle British accent. Calm, measured, rich low voice, "
                     "thoughtful pacing, authoritative yet approachable, like a seasoned commentator on a late-night markets show."),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--takes", type=int, default=2)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    model = Qwen3TTSModel.from_pretrained(str(MODEL), device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa")
    meta = {}
    for name, (language, text, instruct) in CANDIDATES.items():
        if args.only and name not in args.only:
            continue
        for take in range(1, args.takes + 1):
            torch.manual_seed(1000 * take + len(name))
            wavs, sr = model.generate_voice_design(text=text, language=language, instruct=instruct)
            path = OUT / f"{name}_t{take}.wav"
            sf.write(path, wavs[0], sr)
            meta[path.name] = {"language": language, "instruct": instruct, "text": text, "seconds": round(len(wavs[0]) / sr, 1)}
            print(f"{path.name}: {meta[path.name]['seconds']}s", flush=True)
    (OUT / "candidates.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
