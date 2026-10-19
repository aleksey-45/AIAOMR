# aiaomr

把电脑导出的贝斯谱图片认成 Guitar Pro 5（`.gp5`）文件。命令行工具，Python 3.10+，不用 GPU；识别要联网调用视觉模型，按量付费。

> **当前状态（2026-10-18，代码基线 `ab01d32`）：P1 验收未通过，真实曲谱还没有产出过 `.gp5`。**
> P1 用 4 首第 3 类真谱验收，**0/4 通过**：四首全部停在写出闸门 `E_BUILD_VALIDATE`（小节时值合计对不上拍号），退出码 2。之后 P2 任务 1 调整了闸门边界，但用 P1 录制的模型响应在 HEAD 上离线重放（不联网、不花钱），打上花火仍停在写出闸门（`小节 18 拍 4: 既没有音符也没有标休止`）。
> 已经能跑通的是：定位、骨架、读小节、验算、GP5 写出与往返核对、成本口径，以及"该停下来时干净地停下"。复读与终裁、A6–A12、读五线谱层、语料门尚未实现；P2 正在进行。
> 证据：[`docs/p1-report.md`](docs/p1-report.md)、[`docs/p0-results.md`](docs/p0-results.md)。

## 它要解决什么问题

你手上有几页贝斯谱图片（例如 4 页、79 小节），想把它变成能在 Guitar Pro 里打开、能弹、能改的 `.gp5`。

- **手工打谱**：在 Guitar Pro 里一个音一个音敲，几个小时，还要逐小节核对时值。
- **这个工具想做的事**：一条命令，一首不到两毛钱（P1 实测 ¥0.08–0.13），目标是几十秒跑完。它不替人猜：模型说看不清的地方记一条报警，程序**不补音符、不补休止、不猜时值**。宁可停下来告诉你哪一小节有问题，也不给一份看着完整、其实是编出来的谱。

当前只做第 3 类输入（电脑导出的清晰谱图：五线谱 + 4/5 线 TAB）。手机照片、视频截图、图形界面都不在现在的范围里。

## 核心思路

> 几何定坐标，VLM 定符号，TAB 定音，记谱定时，程序验算，模型终裁。
> —— [`docs/plan-v3.md`](docs/plan-v3.md)

六个短句对应六个角色：

- **几何定坐标**：纯 OpenCV/numpy 找系统、小节网格、TAB 弦线、谱线间距。定位层只输出坐标与几何量，不下任何音乐结论。
- **VLM 定符号**：把一个系统（≤8 小节）裁成 1.6 百万像素的横条送给视觉模型，只读这一条里的弦号、品数、时值。**不把整页图发模型。**
- **TAB 定音**：音高 = 调弦 + 品数，由程序算；模型给的音高只用于比对，不进权威字段。
- **记谱定时**：P2 起用几何判据读符头、符干、横梁、附点与休止，模型只做复核（规范见 [`docs/spec-staff.md`](docs/spec-staff.md)；符干/横梁/符尾/附点/多小节休止已实现，符头类别、休止三组与归属建图待补）。
- **程序验算**：不变量逐小节检查（当前 A1–A5），只报警、不阻断、不补写。
- **模型终裁**：报警项盲读复读，两次独立读数一致才采纳，不一致送终裁（尚未实现）。

## 流水线

一条命令按固定顺序跑 9 个阶段：

| 阶段 | 做什么 | 产物（`out/<song>/` 下） |
|---|---|---|
| `input` | 登记输入、算 sha256、记录 class | `input.json` |
| `locate` | 页 → 系统 → 小节网格 → 裁片坐标 | `pageset.json`、`crops/` |
| `skeleton` | 读拍号、调弦、调号、速度、曲名，缺项兜底 | `skeleton.json`、`crops/header.png` |
| `staff` | 读五线谱符号（符干/横梁/符尾/附点/休止），给出逐拍时值与 abstain 理由；不联网 | `staff/rhythm.json` |
| `read` | 裁片 → 调模型 → 四道闸 → 逐小节事实 | `pageNN/crops/*.png`、`measures/*.json`、`calls/*.json` |
| `verify` | 跑不变量，产出报警清单 | `judgements.json` |
| `assemble` | 排小节号、展开多小节休止、组装 IR | （内存；完整跑完才落 `ir.json`） |
| `write` | `validate → build → 原子写 → 往返核对` | `<song>.gp5`（唯一交付物） |
| `audit` | 用 alphaTab 做独立第二意见 | 事件 `audit.result` |

全程还会写：`events.ndjson`（事件流，永远落盘）与 `metrics.json`（阶段耗时、调用数、报警数、审计结果）；阻断时另写 `run.log`。

## 快速开始

需要 Python 3.10+；不需要 GPU。跑真实识别要联网，并准备 `DEEPSEEK_API_KEY`（只在环境变量里，不写进文件）。

Windows（Git bash）下先让 Python 用 UTF-8 输出，否则中文帮助会乱码：

```bash
export PYTHONUTF8=1     # PowerShell: $env:PYTHONUTF8=1
```

安装（仓库已有 `.venv/` 可以直接用；若报 `invalid command 'bdist_wheel'`，先 `.venv/Scripts/python.exe -m pip install wheel`）：

```bash
.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

确认装好了 —— 能看到 `usage` 就说明入口可用：

```bash
.venv/Scripts/python.exe -m aiaomr --help
```

跑测试（默认全离线，不出网、不花钱）：

```bash
.venv/Scripts/python.exe -m pytest -q
# 2026-10-18：143 passed, 2 skipped（跳过的是 alphaTab 审计，需要 Node + alphaTab）
```

非 Windows 把 `.venv/Scripts/python.exe` 换成 `.venv/bin/python`。不想安装也可以临时用源码跑：`PYTHONPATH=src .venv/Scripts/python.exe -m aiaomr --help`。

## 使用

```bash
.venv/Scripts/python.exe -m aiaomr run --input "打上花火/" --class 3 --song 打上花火
# 成功时（当前真实曲谱还到不了这一步）：out/打上花火/打上花火.gp5
# 失败时：产物保留在 out/打上花火/，退出码非 0，可 --resume
```

`run` 的参数（以 `run --help` 为准）：

| 参数 | 作用 |
|---|---|
| `--input` | 图片或图片目录（必填），支持 `png/jpg/jpeg/webp` |
| `--class` | 输入档 `1/3/5/6`，默认 3；当前只对 3 做验收 |
| `--song` | 曲名，默认取文件名；决定 `out/<song>/` 目录名 |
| `--out` | 输出目录，默认 `out/<song>` |
| `--provider` | `deepseek_flash`（默认）或 `stub`（离线回放） |
| `--format` | `auto`（默认，TTY 用 human、管道用 ndjson）/ `human` / `ndjson` |
| `--until` | 跑到指定阶段停：`input/locate/skeleton/staff/read/verify/assemble/write/audit` |
| `--resume` | 复用已有中间产物；已付过钱的调用不重复付 |
| `--force` | 强制重跑 `skeleton` 与 `read` |

### 现在跑一次会看到什么

2026-10-18 的 P1 验收中，四首歌都在写出阶段停下，退出码 2。下面这段是同期一次真实运行留下的**阻断事件**（取自 `out/p1/ab/events.ndjson`；`out/` 是运行产物，不入库。字段有删减）：

```json
{"v":1,"seq":28,"stage":"write","event":"block","data":{"code":"E_BUILD_VALIDATE","message":"写出前校验失败: 小节 2: 时值合计 3120 ticks，拍号需要 3840; …","resumable":true}}
{"v":1,"seq":29,"stage":"run","event":"run.finished","data":{"status":"blocked","stage":"write","exitCode":2,"code":"E_BUILD_VALIDATE"}}
```

在代码基线 `ab01d32` 上把 P1 录制的模型响应离线重放（`--provider stub`，不联网、不花钱），打上花火仍在同一道闸门停下，报警 322 条。所以这一节暂时没有"成功输出"可以展示 —— 等 P2 跑通再换。

## 命令行契约

这套输出是**给机器读的接口**（以后 GUI 只做 `spawn → 逐行解析 → 渲染`，不重写业务逻辑）。

| 流 | `--format ndjson` | `--format human` |
|---|---|---|
| stdout | **只有** NDJSON，一行一个 JSON；不打印自由文本和进度条 | 阶段摘要（人读） |
| stderr | 人读日志 | 同左 |
| 文件 | `out/<song>/events.ndjson`：永远只写 NDJSON，与 stdout 同格式 | 同左 |

`--format auto`（默认）：stdout 是 TTY 就用人读模式，否则用事件流。

事件通用字段：`v`（schema 版本）、`seq`（从 1 连续递增）、`ts`（UTC、毫秒、以 `Z` 结尾）、`level`、`stage`、`event`（点分命名）、`data`。`run.started` 与 `run.finished` 全局各恰好一次；中文按原样输出，不转义。

| 退出码 | 含义 |
|---|---|
| 0 | 成功：`.gp5` 已写出并通过往返核对（审计通过；缺 Node/alphaTab 时审计降级为跳过，不算失败） |
| 1 | 输入不可用 / 阶段级失败 |
| 2 | 工具故障（模型调用、写出、写出前校验、审计） |
| 3 | 成本超限 |
| 130 | 被 SIGINT 中断 |

所有 JSON 与 `.gp5` 都先写临时文件再改名：阻断时不会留下半个文件，已产生的中间产物全部保留，`--resume` 可以接着跑。完整事件清单见 [`docs/spec-v3.md`](docs/spec-v3.md) §10.4。

## 成本

钱的单位只有一个：**人民币 / 每 8 小节 / 闲时价 / 四位小数**。

| 项 | 数值 |
|---|---|
| 硬上限 | ¥0.0150 / 8 小节；单次调用或累计超限即 `E_BUDGET_EXCEEDED`，退出码 3 |
| P0 实测 | 13 次调用合计 ¥0.0324；1.6 MP、thinking 关时一次约 ¥0.0025–0.0035 |
| P1 实测 | 4 首共 124 次调用 ¥0.4240；每 8 小节 ¥0.0081–0.0144，全部低于上限 |
| 单首参考 | 79 小节约 ¥0.08–0.13 |
| 计价 | 输入（cache miss）¥1.00 / 百万 token，命中 ¥0.02，输出 ¥4.00；峰价是闲时价的两倍 |

预算闸不是账单：它用于预算与回归比较，不与 provider 对账。`--resume` 复用已有调用记录，已经付过钱的调用不会重复付。明细见 [`docs/p1-report.md`](docs/p1-report.md) 与 [`src/aiaomr/providers/deepseek_flash/README.md`](src/aiaomr/providers/deepseek_flash/README.md)。

## 架构与目录

代码按依赖方向分四层，依赖只能从上往下指：

```
providers (L1) → measure (L2) → score (L3) → writers (L4)
        └──────────── kernel（四层共用的纯数据）────────────┘
```

```
src/aiaomr/
├── cli.py                    唯一入口：参数解析、9 阶段编排、阻断与退出码
├── events.py                 事件对象、NDJSON 写出、human 渲染；无业务判断
├── kernel/                   四层共用的纯数据，只依赖标准库与 pydantic
│   ├── ir.py                 IR v3.0，唯一 schema 来源
│   ├── contracts.py          PageSet / Crop / MeasureTask / MeasureResult / Skeleton / MeasureRhythm
│   ├── errors.py             错误码、严重级别、退出码
│   └── config.py             configs/*.toml 三层合并与校验
├── providers/                L1 模型接入；唯一允许发 HTTP 的目录
│   ├── base.py               VisionProvider 协议与能力声明
│   ├── registry.py           按名字取 provider（stub / deepseek_flash）
│   └── deepseek_flash/       当前唯一实现：请求、重试、记账、离线回放
├── measure/                  L2 裁片规划、调模型、严格校验、逐小节事实
│   ├── crop_plan.py          系统 → 1..k 张裁片（统一 1.6 MP，拆分带谱号条）
│   ├── read.py               一次模型调用 → MeasureResult[]；弦号翻转在这里
│   ├── schema.py             G2 严格 json.loads + G3 pydantic 校验
│   └── prompts/system.md     读小节的稳定前缀提示词
├── score/                    L3 定位、骨架、几何判据、验算、装配
│   ├── locate/               页 → 系统 → 小节网格 → 裁片
│   ├── skeleton/             拍号/调弦/调号/速度/曲名，缺项兜底并记来源
│   ├── staff/                读五线谱符号：判据、归属、时值、abstain（规范 docs/spec-staff.md）
│   ├── verify/               不变量 A1–A5，只报警不阻断
│   ├── assemble/             多小节休止展开、印刷号优先、IR 组装
│   └── prompts/              骨架与调号提示词
├── writers/                  L4 只吃 IR 写出
│   ├── base.py               Writer 协议与 Report
│   └── gp5/writer.py         validate → build → 原子写 → 往返核对；弦号翻转在这里
└── eval/                     带分母打分与尺子自测（尚未接 CLI）
```

其他顶层目录：

| 路径 | 职责 |
|---|---|
| `configs/` | `default.toml`（与 provider 无关的参数）、`providers/<name>.toml`（provider 专属）、`thresholds.toml`（验收阈值） |
| `tests/` | 190 个测试，默认离线；`test_layers.py` 用 AST 扫描 import，强制四层依赖（含 LAY-09） |
| `tools/` | `audit.mjs`（alphaTab 审计）、`dump.mjs`（真值导出与评测）、`truth_to_gp5.py`（真值 → gp5 副本） |
| `scripts/` | `p0_probe.py`：P0 一次性探针，不属于产品路径 |
| `docs/` | 规范、方案、实施计划、P0/P1 报告 |
| `corpus/truth/` | 四首歌真值的 `.gp5` 副本，评测与人工比对都读它 |
| `out/` | 运行产物，已 gitignore |

几条"只允许在一处"的规矩：

- 弦号翻转只允许出现两次，各一处：模型（GP 习惯）→ IR 在 `measure/read.py`，IR → GP5 在 `writers/gp5/writer.py`。
- 厂商字面量（模型名、endpoint、`detail` 取值）只允许出现在 `providers/` 与 `configs/providers/`。
- 业务层不许自己发请求，要用模型只能走 `providers/`。
- `writers/` 只吃 IR，禁止读 `out/` 里的中间产物。
- 依赖方向由 [`tests/test_layers.py`](tests/test_layers.py) 强制检查，不是靠自觉。

三条数据接缝只传数据、不传对象：`MeasureTask / MeasureResult`（L3 → L2）、`IR`（L3 → L4）、`ProviderCapabilities`（L1 → L2）。模型输出进入程序前必须过四道闸：请求约束 → 严格 `json.loads` → Pydantic 结构校验 → 业务不变量。

## 文档地图

| 文档 | 什么时候读 |
|---|---|
| [`docs/spec-v3.md`](docs/spec-v3.md) | **规范，唯一权威。** 字段名、错误码、参数值、事件名、不变量都在这里；与其它文档冲突时以它为准 |
| [`docs/plan-v3.md`](docs/plan-v3.md) | 想知道"为什么要这么设计"、哪些方案被放弃了 |
| [`docs/spec-staff.md`](docs/spec-staff.md) | 读五线谱层的配套规范（判据、abstain 原因、目录归属）；已实现原型，判据在补 |
| [`docs/superpowers/plans/`](docs/superpowers/plans/) | 实施计划（每个任务先写会失败的测试）。注意：勾选框状态过期，进度以 `git log`、代码和阶段报告为准 |
| [`docs/p0-results.md`](docs/p0-results.md) | 两分钱实测：1.6 MP、thinking 关、单次读整系统这些参数是怎么定下来的 |
| [`docs/p1-report.md`](docs/p1-report.md) | P1 验收报告：为什么 0/4、卡在哪、哪些项已通过 |
| [`docs/plan-measure-score.md`](docs/plan-measure-score.md) | **设计稿**：小节从「通过/不通过」改成打分，按分数分「直接通过 / AI 复审 / 判错」三档（未实现） |
| [`docs/current-state.md`](docs/current-state.md) | **现状总览（人工审核用）**：能力/缺口、代码结构、真页面实测、已知问题分级、待决事项 |
| [`AGENTS.md`](AGENTS.md) | 开工前必读：红线、依赖方向、开发命令、多 agent 分工 |

规范与方案文档头部目前仍写"待审核"；它们已经按 v3 实施，但不要当成"已审核定稿"。

## 进度与路线图

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 花两分钱实测，标定裁片、清晰度、单次读几个小节 | 已完成 |
| P1 | class 3 端到端：4 首真谱 → `.gp5` | **未通过 0/4**：全部停在写出闸门 |
| P2 | 几何节奏、连音、多小节休止、复读终裁、A6–A12、并发、缓存、语料门 | 进行中：任务 1 完成；任务 2（几何符头）原型阶段，真页面对照 0/7 |
| staff | 读五线谱层（`score/staff/`） | 原型已接进 CLI（独立阶段、产物与事件落盘）；符头类别、休止三组、横梁归属建图待任务 2/3 |
| P3–P5 | class 5 视频截图、class 6 演奏视频长条、class 1 手机照片 | 未开始 |
| P6 | GUI 薄壳：只消费事件流，不重写业务 | 未开始 |

验收阈值：弦号 + 品数一致率 ≥ 0.90，小节时值自洽率 ≥ 0.95，报警解决率 1.00，alphaTab 审计 0/0。P1 没写出 `.gp5`，这些分数**一次都还没量过**。

## 约束与不做的事

现在只做第 3 类输入。**明确不做**：

- 手机拍摄的图片（透视、起拱、光照未处理）——最难，排最后
- 视频截图、滚动谱拼接
- 简谱、手写谱、无 TAB 的纯五线谱
- 音频扒谱、多轨/多乐器、和弦图
- GPU 推理，以及 `homr`、`oemer`、`Audiveris`、`litellm` 这类现成 OMR 或统一网关
- 图形界面（当前）；以后 GUI 只读事件流

几条会影响使用者的红线：

- **不把整页图发给模型**；不为看清一个数字单独发小图；裁片必须包含完整谱号区。
- **不补音符、不补休止、不猜时值**。模型说看不清就记一条报警，不往下编。
- **报警不阻断**。真正会停下来的只有：图片根本没法用、成本超预算、写出的文件通不过自检（审计不通过也会以退出码 2 结束）。
- 不读总小节数，`measureCount = len(measures)`。
- 复读必须盲读：只给报警规则与 claim/expected，不带上一遍读出的音符。
- 重试只回传截断到 500 字以内的错误摘要，不回传上一次完整回复。
- 中文标题必须能按 cp936 编出去，编不进去就报错退出，不许写出乱码。
- API key 只从环境变量进；日志、fixture、`calls/*.json` 里不许出现 `DEEPSEEK_API_KEY`。
- 阈值不许为了让验收变绿而改。

## 开发方式

改动之前先读 [`AGENTS.md`](AGENTS.md)，那是完整规矩。最低限度的几条：

1. **先写会失败的测试**，跑一遍确认它失败，再动实现。测试里直接写死规格里的数字。
2. 错误码只用 `kernel/errors.py` 里的；参数一律进 `configs/*.toml` 并登记到规格参数表，代码里不许出现表外魔数。
3. 不要碰 `docs/spec-v3.md`、`docs/plan-v3.md` 和计划文件；发现写错了，报告，不要自己改。
4. 提交用约定式前缀（`feat` / `fix` / `test` / `chore` / `docs` / `refactor`），一次提交只做一件事；禁止 `git add -A`。

测试默认离线：`--provider stub` 只读 `out/<song>/calls/` 里录制好的响应，不发网络请求。真实调用只发生在 P0 实测与阶段验收，且要先确认 `DEEPSEEK_API_KEY` 在环境里。

离线回放的做法：把录好的 `<callId>.resp.json` 放进 `out/<song>/calls/`，用 `--provider stub` 重跑同一条 `run` 命令即可；`callId` 形如 `01s01p01`（页、系统、分段），骨架是 `skeleton`。回放文件属于运行产物，不入库。

## 许可证

本仓库目前**没有**开源许可证文件。按默认版权法，作者保留所有权利：他人不得复制、分发或创作衍生作品；若要引用或合作，请先联系作者。

如果将来决定开源，会在这里换成 SPDX 标识符并补上 `LICENSE` 文件。
