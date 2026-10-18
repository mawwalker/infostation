# InfoStation · 全自动美股/加密情报站

每个交易日自动：采集免费数据 → 量化漏斗筛选 → agy 选题与写稿（中/英） → 数字核对 → 合成配音 → Remotion 渲染
→ 产出 **两条 16:9 视频 + 两套 X 推文串（含数据卡片）+ 缩略图 + 字幕 + YouTube 标题/简介/章节**。上传由你手动完成。

设计说明与风险分析见 [docs/PLAN.md](docs/PLAN.md)；给 Agent 的说明见 [AGENTS.md](AGENTS.md)。

## 快速开始

```bash
cp .env.example .env            # 至少填 SEC_USER_AGENT
uv sync                         # Python 依赖
(cd video && npm ci)            # Remotion 依赖（首次渲染会自动下载 Chrome Headless Shell）
scripts/setup_tts.sh            # 本地配音：IndexTTS-2.5 + 模型（约 10GB，一次性）
uv run infostation doctor       # 体检：工具、agy、配音、各数据源
uv run infostation run          # 跑一期（自动判断盘后/盘前、交易日）
```

产物在 `runs/<日期>_<时段>/upload/{zh,en}/`：

| 文件 | 用途 |
| --- | --- |
| `video.mp4` | 1080p 视频，响度已标准化到 -14 LUFS |
| `thumbnail.png` | 1280×720 缩略图 |
| `captions.srt` | 字幕，上传到 YouTube |
| `youtube.md` | 标题、简介（含章节时间戳、来源、免责声明）、标签 |
| `x_thread.md` + `cards/` | 推文串与配图 |
| `metadata.json` | 上传参数提示（是否需要勾选 AI 合成内容等） |

`runs/<id>/review.md` 是发布前的检查单：选题、数字核对结果、推文字数、数据源健康状况。

## 在 agy / Claude Code 里全自动运行

项目自带技能 `infostation-daily`（`.agents/skills/`，Claude Code 通过 `.claude/skills/` 软链读取）。在项目目录里：

```bash
# Antigravity CLI
agy -p "跑今天的复盘视频，检查 review.md 和视频截帧后汇报" --dangerously-skip-permissions
# Claude Code
claude -p "跑今天的复盘视频，检查 review.md 和视频截帧后汇报"   # 权限白名单见 .claude/settings.json
```

Agent 会运行流水线、检查数字核对和画面、遇到数据源坏掉时修采集器再续跑。

## 定时运行（无人值守）

纯脚本即可，不需要 Agent 常驻：

```bash
mkdir -p ~/.config/systemd/user
cp deploy/infostation.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now infostation.timer
loginctl enable-linger $USER    # 未登录时也运行
```

默认北京时间周二至周六 06:30 运行（美东收盘后）。或用 cron：
`30 6 * * 2-6 /path/to/auto_information_state/scripts/run_daily.sh`

## 常用命令

```bash
uv run infostation run --session premarket          # 盘前早报
uv run infostation run --date 2026-10-16 --force    # 重做某天
uv run infostation run --from write                 # 改了提示词后从写稿开始重跑
uv run infostation run --only render                # 改了模板后只重新渲染
uv run infostation run --langs zh                   # 只出中文版
uv run infostation studio 2026-10-16_recap --lang zh  # 在 Remotion Studio 里调模板
uv run pytest -q
```

## 准备清单

**必须**
1. `.env` 里的 `SEC_USER_AGENT="你的名字 你的邮箱"`：SEC 要求 User-Agent 带联系方式，否则可能被封 IP。
2. agy 已登录且能用 `config.yaml` 里的模型（`agy models` 查看）。

**强烈建议**
3. **背景音乐**：在 `assets/music/` 放几首免版税音乐（YouTube 音频库里选“无需署名”的）。不放就是纯人声。
4. **品牌**：改 `config/config.yaml` 的 `brand`（频道名、@账号）。
5. **频道资料**：YouTube 中英文各开一个频道（或一个频道两个播放列表），X 账号。用同一个视觉风格建立辨识度。

**可选**
6. `FINNHUB_API_KEY`（免费注册）：补充公司新闻。
7. Reddit script App（`REDDIT_CLIENT_ID/SECRET`）：补充 r/wallstreetbets 热帖；没有也有 ApeWisdom + Stocktwits。
8. 局域网 ComfyUI（`config.yaml → comfy`）：生成缩略图/片头背景，不可用时自动降级为渐变背景。
9. 想换配音音色：见下方「配音与音色」。

## 配音与音色

- 合成引擎：本地 **IndexTTS-2.5**（零样本音色克隆，RTX 5080 上约 0.5 倍实时；整期中英文约 8 分钟）。
  逐句合成并按内容缓存，改稿后只重合成改动的句子。`tts.provider: edge` 可切回微软在线 TTS 兜底。
- 音色：`voices/zh_narrator.wav`、`voices/en_narrator.wav`。默认是用 **Qwen3-TTS VoiceDesign**（Apache-2.0）
  按文字描述生成的虚构音色，不属于任何真人，没有肖像权/人格权问题。
- 换音色：
  1. 试听 `voices/audition/*.wav`（同一段财经稿，不同音色），把喜欢的 `voices/candidates/<名字>.wav` 复制成 `voices/zh_narrator.wav`；
  2. 或者设计新音色：编辑 `tools/voicelab/design.py` 里的描述，`scripts/setup_tts.sh --voicelab` 后运行 `cd tools/voicelab && .venv/bin/python design.py`；
  3. 或者用你自己的声音：录 10–20 秒安静环境下的自然朗读（WAV），替换即可，这是辨识度最高也最安全的做法。
- **不要**克隆网红、主播或名人的声音：涉及人格权，也违反平台“冒充他人”的政策，被认出来比 AI 味更伤频道。
- IndexTTS 许可（bilibili Model Use License）：月活 1 亿或年收入 10 亿人民币以下可免费商用。

## 字幕

字幕不是把原文切段塞进去，而是按电视字幕规范排版（`media/captions.py`）：
- 中文单行 ≤18 字，英文每屏最多两行、每行 ≤42 字符；
- 用 jieba 分词，词、数字+单位（8.43%、45亿美元）、英文名（S&P 500、10b5-1）不会被拆开；
- 能放进一行的分句绝不在中间断开；一行只拼接完整分句；英文优先在标点、连词、介词前断，行尾不留 the/of/to 等虚词；
- 去掉行尾标点，行首不出现标点，中文行内逗号改为空格；
- 每句单独合成，句子边界精确；句内断点用 Whisper 词级时间戳对齐到实际发音。

## 可调参数（`config/config.yaml`）

- `universe.watchlist`：每天必扫的股票池
- `screening.stories`：每期主线数量（默认 3）
- `video.fps`：30 或 60（60 渲染时间约翻倍）
- `video.up_down`：涨跌配色（中文版默认红涨绿跌，英文版绿涨红跌）
- `tts.voices` / `tts.rate`：配音音色与语速（`uv run edge-tts --list-voices` 查看全部）
- `factcheck.block_on_fail`：数字核对不过时是否停止渲染
