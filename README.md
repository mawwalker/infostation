# InfoStation · 全自动美股/加密情报站

每个交易日自动完成：采集免费数据 → 量化筛选 → agy 选题并写中英文稿 → 数字核对 → 本地 IndexTTS 配音 → Remotion 渲染。
每期产出：

- 中文、英文 16:9 视频各一条
- 缩略图、字幕
- YouTube 标题、简介（含章节）、标签
- X 推文串和配图卡片

**上传由你手动完成。**

设计思路与风险分析见 [docs/PLAN.md](docs/PLAN.md)；给 Agent 看的说明见 [AGENTS.md](AGENTS.md)。

---

## 一、一次性准备（只做一次）

### 1. 前置条件

| 需要 | 检查方法 |
| --- | --- |
| uv、Node.js、ffmpeg | `uv --version && node --version && ffmpeg -version` |
| agy 已登录，能用 `gemini-4-argon-medium` | `agy models` 列表里有它 |
| NVIDIA 显卡，空闲显存 ≥ 8GB（配音用） | `nvidia-smi` |
| 磁盘空间约 20GB（模型） | |

### 2. 安装

```bash
cd ~/workspace/auto_information_state
uv sync                          # Python 依赖
(cd video && npm ci)             # Remotion 渲染依赖
scripts/setup_tts.sh             # 本地配音：IndexTTS-2.5 + 模型，约 10GB，走 ModelScope / hf-mirror
```

### 3. 配置

```bash
cp .env.example .env
```

- **必须**：在 `.env` 里填 `SEC_USER_AGENT="你的名字 你的邮箱"`。SEC 要求请求带联系方式，否则可能封 IP。
- **建议**：改 `config/config.yaml` 的 `brand`，填频道中英文名和 @账号。
- **建议**：往 `assets/music/` 放几首免版税背景音乐（YouTube 音频库里选“无需署名”的）。不放就是纯人声。
- **可选**：选一个喜欢的音色。试听 `voices/audition/`，方法见下文「换配音音色」。

### 4. 体检

```bash
uv run infostation doctor
```

全部 ✅ 就可以开始了（ComfyUI 是可选项，不可用时缩略图会用渐变背景）。

---

## 二、每天怎么运行（手动）

**什么时候跑**：美股收盘后，北京时间早上 6 点以后（夏令时 4 点后）跑“盘后复盘”。程序会自动判断复盘哪个交易日，周末和美股假日也不会出错。

**跑一次**，三种方式任选：

```bash
# A. 直接命令（最简单）
scripts/run_daily.sh

# B. 用 agy：它会跑流水线、检查结果，遇到数据源坏了会自己修
agy -p "跑今天的复盘视频，检查 review.md 和视频截帧后汇报" --dangerously-skip-permissions

# C. 用 Claude Code（权限白名单已在 .claude/settings.json 配好）
claude -p "跑今天的复盘视频，检查 review.md 和视频截帧后汇报"
```

一次大约 **35–40 分钟**：

| 步骤 | 耗时 |
| --- | --- |
| 采集 + 筛选 | 2 分钟 |
| agy 选题 + 写稿 | 6 分钟 |
| 配音 + 字幕对齐 | 10 分钟 |
| 渲染两条视频 | 20 分钟 |

同一期重复执行会直接跳过已完成的步骤。

**跑完之后发布**（每天约 10 分钟）：

1. 打开 `runs/<日期>_recap/review.md`，看三件事：
   - 今天的三条主线是什么；
   - 数字核对是否全是 ✅；
   - 有没有数据源 ❌。
2. 快速过一遍视频：开头 30 秒 + 任意一段主线。
3. 上传 YouTube：`runs/<日期>_recap/upload/zh/` 和 `upload/en/` 各一个频道（或播放列表）
   - `video.mp4` 上传；`thumbnail.png` 设为缩略图；
   - `youtube.md` 里的标题、简介、标签直接复制粘贴；
   - `captions.srt` 作为字幕上传；
   - `metadata.json` 提示是否需要勾选“AI 合成内容”，默认不需要。
4. 发 X：按 `x_thread.md` 逐条发，`[image: cards/xxx.png]` 标注的位置附上 `cards/` 里对应的图片。

**其他常用命令**

```bash
uv run infostation run --session premarket          # 盘前早报（北京时间晚上，美股开盘前）
uv run infostation run --date 2026-10-16 --force    # 重做某一天
uv run infostation run --from write                 # 改了提示词后，从写稿开始重跑
uv run infostation run --only render                # 改了视频模板后，只重新渲染
uv run infostation run --langs zh                   # 只出中文版
uv run infostation runs                             # 查看最近各期的状态
uv run infostation studio 2026-10-16_recap --lang zh   # 在 Remotion Studio 里预览/调模板
```

---

## 三、全自动运行（无人值守）

全自动 = 系统定时器每天自动执行 `scripts/run_daily.sh`。不需要开着 agy 或 Claude Code，你只需要收到通知后去上传。

### 1. 启用定时任务（systemd，推荐）

```bash
mkdir -p ~/.config/systemd/user
cp deploy/infostation.service deploy/infostation.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now infostation.timer
loginctl enable-linger $USER          # 未登录桌面时也能运行（本机已开启）
```

默认**北京时间周二到周六 06:30** 运行，对应美股周一到周五收盘后。

```bash
systemctl --user list-timers infostation.timer   # 下次运行时间
systemctl --user start infostation.service       # 立刻手动触发一次（测试用）
journalctl --user -u infostation.service -n 50   # systemd 日志
ls -t data/logs/ | head                          # 每次运行的完整日志
```

想同时做**盘前早报**（北京时间工作日 19:00），再启用一个定时器：

```bash
cp deploy/infostation-premarket.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now infostation-premarket.timer
```

不用 systemd 也可以用 cron（cron 时间是本机时区，本机是美西时间，北京 06:30 = 美西前一天 15:30，夏令时）：

```
30 15 * * 1-5 /home/dsm/workspace/auto_information_state/scripts/run_daily.sh
```

### 2. 全自动的前提条件

- **电脑在那个时间开着**。如果休眠了，`Persistent=true` 会在下次唤醒时补跑；想定时唤醒，可以在 timer 的 `[Timer]` 里加 `WakeSystem=true`（需要主板支持 RTC 唤醒）。
- **显卡空闲**：配音要 8GB 左右显存，那个时间别开游戏或其他 GPU 任务。
- **agy 登录有效**：登录过期时 agy 调用会失败，流水线会退回模板稿（内容平淡但数字准确），并在 review.md 里标出来。
- **网络正常**：单个数据源失败不会中断，会在 review.md 的数据源健康表里标红。

### 3. 可选：失败后自动修复

在 `.env` 里加：

```bash
AUTO_FIX=1
```

运行失败时，脚本会调用 agy，按项目技能 `infostation-daily` 排查：读日志、跑体检，如果是代码或采集器的问题就修复并跑测试，然后自动续跑一次。

注意：这时 agy 以“跳过权限确认”的方式运行，会直接改项目代码。改动都在 git 里，可以用 `git diff` 查看、`git checkout .` 撤销。如果不放心，就保持关闭，失败时手动运行 B 方式。

### 4. 可选：通知

- 默认在完成或失败时弹桌面通知（`notify-send`）。
- 想推送到手机，就写一个脚本，参数是 `<ok|failed> <消息>`（比如调用 Telegram Bot），然后在 `.env` 里设 `NOTIFY_SCRIPT=/path/to/notify.sh`。

### 5. 全自动之后，你每天要做的

收到“InfoStation: ok”通知 → 打开 `review.md` 看一眼 → 按「二、跑完之后发布」上传。整个过程 10 分钟左右。

---

## 四、出问题怎么办

先看两个地方：最新的 `data/logs/*.log`，以及 `uv run infostation doctor` 的输出。

| 现象 | 处理 |
| --- | --- |
| 某个数据源 ❌ | 通常是对方临时限流，第二天会恢复；连续多天失败，让 agy/Claude Code 按 AGENTS.md 修采集器 |
| `no price bars for <日期>` | 行情还没更新（跑得太早），过半小时再跑 |
| 写稿退回了模板（review.md 显示 `template`） | agy 不可用或登录过期：运行 `agy models` 检查，然后 `uv run infostation run --from edit --force` |
| 数字核对 ❌ | 打开 `runs/<id>/script_<语言>.json` 看 `_factcheck` 列出的数字；确实是错的就 `--from write` 重写 |
| IndexTTS 报错 / 显存不足 | 关掉占用显卡的程序，然后 `uv run infostation run --from voice`；临时应急可在 config 里设 `tts.provider: edge` |
| 渲染失败 | `cd video && npx tsc --noEmit` 检查模板，修好后 `--from render` |
| 想重做整期 | `uv run infostation run --date <日期> --force` |

---

## 五、日常调整

### 换配音音色

- 默认音色 `voices/zh_narrator.wav`、`voices/en_narrator.wav` 是用 Qwen3-TTS VoiceDesign 按文字描述生成的虚构声音，不属于任何真人。
- 换音色有三种做法：
  1. **用你自己的声音（最推荐）**：在安静的环境里自然地朗读 10–20 秒，存成 WAV，替换上面的文件。
  2. **从候选里选**：试听 `voices/audition/`（同一段财经稿、不同音色），把喜欢的 `voices/candidates/<名字>.wav` 复制过去覆盖。
  3. **设计新音色**：改 `tools/voicelab/design.py` 里的文字描述，然后运行 `scripts/setup_tts.sh --voicelab && cd tools/voicelab && .venv/bin/python design.py`。
- **不要**克隆网红、主播或名人的声音：涉及人格权，也违反平台“冒充他人”的政策。
- 换音色后，按内容缓存的旧音频自动失效，下次运行会重新合成。

### 字幕规则（`src/infostation/media/captions.py`）

按电视字幕规范排版，规则由 `tests/test_captions.py` 保证：

- **长度**：中文单行 ≤18 字；英文每屏最多两行、每行 ≤42 字符。
- **不拆开**：词语、数字+单位（8.43%、45亿美元）、英文名都不拆。能放进一行的分句不在中间断开。
- **标点**：去掉行尾标点，行首不出现标点，中文行内的逗号改为空格。
- **时间轴**：用 Whisper 对齐到实际发音。

### 常改的配置（`config/config.yaml`）

| 配置项 | 作用 |
| --- | --- |
| `universe.watchlist` | 每天必扫的股票池 |
| `screening.stories` | 每期主线数量（默认 3） |
| `llm.models` | agy 使用的模型（默认 `gemini-4-argon-medium`） |
| `tts.voices` | 配音参考音频 |
| `tts.tempo` | 语速（英文默认 1.07 倍） |
| `video.fps` | 30 或 60（60 的渲染时间约翻倍） |
| `video.up_down` | 涨跌配色（中文红涨绿跌，英文绿涨红跌） |
| `factcheck.block_on_fail` | 数字核对不过时是否停止渲染 |

---

## 六、目录速览

```
config/config.yaml        主配置          .env                密钥与开关（不进 git）
scripts/run_daily.sh      每日入口        scripts/setup_tts.sh  本地配音一键安装
deploy/                   systemd 定时器  voices/             配音音色
src/infostation/          流水线代码      video/              Remotion 视频模板
runs/<日期>_<时段>/       每期产物（upload/ 是上传包，review.md 是检查单）
data/                     历史数据库、缓存、日志
```

**许可提示**：IndexTTS-2.5 使用 bilibili Model Use License，月活 1 亿或年收入 10 亿人民币以下可免费商用；Qwen3-TTS 为 Apache-2.0。
