#!/usr/bin/env bash
# One-time setup for local voice: IndexTTS-2.5 (synthesis) + Qwen3-TTS VoiceDesign (optional, to design new voices).
# Downloads go through ModelScope / hf-mirror because huggingface.co is DNS-poisoned on some networks.
#   scripts/setup_tts.sh            # IndexTTS only (~10 GB)
#   scripts/setup_tts.sh --voicelab # also the voice-design model (~4 GB)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${INDEXTTS_REPO:-$HOME/workspace/audio/index-tts}"

if [ ! -d "$REPO" ]; then
  git clone --depth 1 https://github.com/index-tts/index-tts.git "$REPO"
fi
cd "$REPO"
uv sync --extra webui

ck="$REPO/checkpoints"
[ -f "$ck/gpt.pth" ] || uvx modelscope download --model IndexTeam/IndexTTS-2.5 --local_dir "$ck"
mkdir -p "$ck/hf_cache/bigvgan"
[ -f "$ck/hf_cache/w2v-bert-2.0/model.safetensors" ] || uvx modelscope download --model AI-ModelScope/w2v-bert-2.0 --local_dir "$ck/hf_cache/w2v-bert-2.0"
[ -f "$ck/hf_cache/campplus_cn_common.bin" ] || uvx modelscope download --model iic/speech_campplus_sv_zh-cn_16k-common campplus_cn_common.bin --local_dir "$ck/hf_cache"
for f in config.json bigvgan_generator.pt; do
  [ -f "$ck/hf_cache/bigvgan/$f" ] || curl -sL --fail -o "$ck/hf_cache/bigvgan/$f" "https://hf-mirror.com/nvidia/bigvgan_v2_22khz_80band_256x/resolve/main/$f"
done
echo "IndexTTS ready at $REPO"

if [ "${1:-}" = "--voicelab" ]; then
  (cd "$ROOT/tools/voicelab" && uv sync)
  [ -f "$ROOT/data/models/Qwen3-TTS-VoiceDesign/model.safetensors" ] || \
    uvx modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign --local_dir "$ROOT/data/models/Qwen3-TTS-VoiceDesign"
  echo "Voice lab ready: cd tools/voicelab && .venv/bin/python design.py"
fi
