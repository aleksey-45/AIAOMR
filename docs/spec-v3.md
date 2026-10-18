# AIAOMR v3 设计规范（Spec）

- 版本：3.0
- 日期：2026-10-17
- 状态：**待审核**
- 上游文档：`docs/plan-v3.md`（方案与决策记录；本规范只写"必须怎么做"，不重复理由）
- 规范用词：**必须**（MUST）、**禁止**（MUST NOT）、**应当**（SHOULD）、**可以**（MAY）

---

## 0. 地位与术语

| 术语 | 定义 |
|---|---|
| **定位层** | 只输出坐标与几何量、不输出任何语义结论的纯 CV 部分 |
| **读取层** | 视觉模型调用，输出结构化符号事实 |
| **验算层** | 纯程序，检查不变量并产生报警，**不阻断交付** |
| **终裁** | 视觉模型对报警项的最终判定，可推翻定位层与读取层的任何结论 |
| **IR** | canonical 中间表示，唯一事实来源（§3.1） |
| **报警** | 不变量被违反的记录，进入 `judgements[]`，不阻止导出 |
| **class** | 输入档：1 拍照 / 3 理想图 / 5 谱视频截图 / 6 演奏视频底部条 |

本规范与 `docs/plan-v3.md` 冲突时，以本规范为准（更具体者优先）。

---

## 1. 系统边界

### 1.1 输入

- 单个目录或文件列表，扩展名 `png/jpg/jpeg/webp`。
- 必须声明 `--class`（1/3/5/6 之一）；不声明时按 3 处理并在报告里记录该默认。
- 接收的图片可为任意尺寸。**单图解码后 >64 000 000 像素者必须先切片**（见 §2.1 R-06）。

### 1.2 输出

| 产物 | 位置 | 是否交付 |
|---|---|---|
| `<song>.gp5` | `out/<song>/` | **是，唯一交付物** |
| `ir.json` | `out/<song>/` | 否（内部） |
| `judgements.json` | `out/<song>/` | 否（内部） |
| `calls/*.json` | `out/<song>/calls/` | 否（内部，用于回放与回归） |
| `build/report.json` | `out/<song>/build/` | 否（内部） |
| `events.ndjson` | `out/<song>/` | 否（内部；与 stdout 同格式，供 GUI 回放） |
| `run.log` | `out/<song>/` | 否（内部；stderr 全文） |

### 1.3 运行环境

| 项 | 约束 |
|---|---|
| Python | 3.10+ |
| GPU | **不使用**。禁止依赖 CUDA/onnxruntime-gpu |
| 网络 | 必需（DeepSeek API）；离线时仅 `--provider stub` 可运行 |
| Node.js | 仅用于 alphaTab 审计（`tools/audit.mjs`）；缺失时审计降级为 `skipped` 并在报告里标红 |

### 1.4 依赖（版本必须在 `pyproject.toml` 锁定）

`pillow`、`numpy`、`opencv-python-headless`、`requests`、`pydantic`（schema 以代码为准）、`PyGuitarPro`（LGPL，vendored）、`pytest`（dev）、`tomli`（仅 Python 3.10 读 TOML 用；3.11 起走标准库 `tomllib`）。

**禁止**引入：`homr`、`oemer`、`Audiveris`、任何 AGPL 依赖；**禁止**引入 `litellm` 之类"假装所有 provider 一样"的通用网关（见 §1.7 的教训）。

### 1.5 目录布局（按四层依赖组织）

```
AIAOMR/
├── pyproject.toml
├── src/aiaomr/
│   ├── cli.py                 # 唯一入口：参数解析 + 阶段编排，不含业务逻辑
│   ├── events.py              # 事件对象 / NDJSON 输出 / human 渲染（无业务逻辑）
│   ├── config.py              # 参数加载（defaults + providers/<name> + --config）
│   │
│   ├── kernel/                # 共享内核：纯数据 + 错误码 + 协议定义（无 IO、无逻辑）
│   │   ├── ir.py              # IR 数据类（唯一 schema 来源）
│   │   ├── contracts.py       # MeasureTask / MeasureResult / Crop / Judgement
│   │   ├── errors.py
│   │   └── config.py
│   │
│   ├── providers/             # 【L1 模型接入层】唯一允许发 HTTP 的目录
│   │   ├── base.py            # VisionProvider Protocol + ProviderCapabilities
│   │   ├── registry.py        # name -> factory；未注册启动即报错
│   │   └── deepseek_flash/    # 当前唯一实现（DeepSeek-V4.1-Flash-1017）
│   │       ├── client.py      # 请求构造、重试分类、错误映射、usage 归一化
│   │       ├── caps.py        # 能力声明（§2.3.2）
│   │       ├── prompts/       # 覆盖层内 prompt 的差异（只写差异）
│   │       └── README.md      # 接入说明、已知坑、计费口径（必须维护）
│   │
│   ├── measure/               # 【L2 读谱小节层】一次调用 → 若干小节的结构化事实
│   │   ├── crop_plan.py       # 裁切规划（读 caps 取上限）
│   │   ├── schema.py          # 小节输出 Pydantic（由 kernel 类型派生）
│   │   ├── read.py            # 编排：取裁片 → 调 L1 → L2/L3/L4 校验 → MeasureResult[]
│   │   └── prompts/           # 小节读取 prompt（与 provider 无关的公共部分）
│   │
│   ├── score/                 # 【L3 读谱框架层】页 → 系统 → 小节 → IR
│   │   ├── locate/            # 定位（原 geometer）：系统/小节网格/裁片/帧对齐
│   │   ├── skeleton/          # 骨架（分级：拍号/调弦 P0、调号 P1、速度/曲名 P2–P3）
│   │   ├── schedule.py        # 系统级并行、预算、重试编排
│   │   ├── verify/            # 不变量 A1–A10（原 fuse）
│   │   ├── adjudicate/        # 复读与终裁
│   │   ├── assemble/          # 反复展开、编号链、IR 组装
│   │   └── prompts/           # 骨架 / 复读 / 终裁 prompt
│   │
│   ├── writers/               # 【L4 输出格式层】IR → 字节，只依赖 kernel
│   │   ├── base.py            # Writer Protocol: write(ir, path) -> Report
│   │   ├── registry.py        # gp5 / musicxml / ascii_tab 可插拔
│   │   ├── gp5/               # PyGuitarPro 写出 + validate + roundtrip
│   │   ├── musicxml/          # 预留（class 1/5/6 以外的交换格式）
│   │   └── ascii_tab/         # 人眼复核用（内部）
│   │
│   └── eval/                  # 非层：评测、语料门、selftest
│
├── tools/audit.mjs            # alphaTab 独立审计（L4 的外部第二意见）
├── configs/
│   ├── default.toml           # 与 provider 无关的参数
│   ├── thresholds.toml        # 验收阈值（§9.2）
│   └── providers/
│       └── deepseek-flash.toml  # provider 专属参数
├── corpus/                    # 语料与真值（§9.3）
├── fixtures/                  # 录制的请求/响应（§9.4），可离线回放
├── scripts/                   # 一次性探针（P0 等），不属产品路径
├── tests/                     # 单元/契约/端到端 + test_layers.py（LAY-01..08）
├── out/                       # 运行产物（不入库）
└── docs/
```

### 1.6 目录说明（每个目录的职责边界）

| 目录 | 层 | 允许放什么 | **禁止**放什么 |
|---|---|---|---|
| `kernel/` | 内核 | 纯数据类、Protocol、错误码、常量、配置加载（只读 `configs/*.toml`，这是 kernel 唯一的文件 IO 例外） | HTTP、网络、图像处理、业务判定、任何厂商字面量 |
| `providers/base.py` + `registry.py` | L1 | Protocol、能力声明、注册表、异常类型 | 具体厂商代码、业务逻辑 |
| `providers/deepseek_flash/` | L1 | 请求构造、能力值、计费、prompt 差异、README | 裁切策略、验算、装配、导出 |
| `measure/` | L2 | 裁切规划、小节 schema、单次调用的编排 | 页/系统级结构、IR 组装、文件写出 |
| `score/locate/` | L3 | 纯 CV 几何测量（含谱线行 run、符干/横梁等笔画的位置与厚度） | 任何语义判定、任何 HTTP |
| `score/staff/` | L3 | 五线谱符号读取：符头/符干/横梁/符尾/附点/休止的判据、归属、时值（§2.11、`docs/spec-staff.md`） | 联网、调模型、重新定位系统、音高/弦号/品位 |
| `score/skeleton/` `score/verify/` `score/adjudicate/` `score/assemble/` | L3 | 骨架、不变量、复读终裁、装配 | 直接发 HTTP（必须经 L2） |
| `score/schedule.py` | L3 | 并行、预算、重试编排 | 厂商参数 |
| `writers/` | L4 | IR → gp5/musicxml/ascii，validate/roundtrip | 模型调用、裁切、验算 |
| `eval/` | 非层 | 打分、语料门、selftest | 混进产品路径 |
| `configs/default.toml` | — | 与 provider 无关的参数 | 厂商参数 |
| `configs/providers/<name>.toml` | — | 模型名、并发、预算、重试、thinking | 业务阈值 |
| 各层 `prompts/`（L2/L3） | L2/L3 | 与 provider 无关的公共约束 | 厂商特定口径 |
| `providers/<name>/prompts/` | L1 | 只写差异，覆盖 base 对应段落 | 复制整份 base |
| `fixtures/<provider>/` | — | 录制好的请求/响应 | 真值、密钥 |
| `corpus/` | — | 真图、真值 `.gp`、合成语料 | 运行产物 |
| `out/<song>/` | — | 运行产物（IR、calls、crops、gp5） | 应入库的东西 |

**落盘硬规则**：新增任何目录，必须在本表登记一行；未登记的目录在 code review 时视为违规。

### 1.7 从外部项目学到的七条（对应本规范的修改）

| 教训 | 来源 | 落到本规范的哪一条 |
|---|---|---|
| 先观测再优化：按阶段量延迟/token/重试，p95 不可解释就是没观测 | [MS Learn: AI App Architecture](https://learn.microsoft.com/en-us/startups/build/ai/ai-app-architecture) | §8.2 每阶段指标落盘 |
| 结构化输出不是"提示词说严点"，而是**四道闸**：请求约束→语法解析→结构校验→业务判定 | [阿里云：结构化结果的校验、重试与降级](https://developer.aliyun.com/article/1754367) | §2.3.1 |
| Schema 必须由代码模型生成，不能手工维护多份 | 同上 | §3.1 + `kernel/ir.py` |
| 重试要按错误类型分类，且**只回传截断的错误摘要**，不回传完整响应 | 同上 | V-06、V-05b |
| `temperature=0` 不保证可复现；要靠 fixture 与幂等，不靠采样参数 | 同上 | §9.4、§8.1 |
| 抽象层的价值在统一路由与预算，代价是掩盖厂商差异、增加调试难度 | [LiteLLM in Production, PyData Berlin 2025](https://berlin.pydata.org/conferences/2025/NUNXEV.html) | §2.3.2 能力显式声明，不做假统一 |
| 确定性预处理 + 专用组件 + **受控**使用生成式模型 + 证据保留 + 可观测 | [Beyond "Everything with a Vision LLM"](https://zenodo.org/records/22706024) | §2.1–§2.3 的分层与 §8 的 calls/crops 留证 |

---

## 2. 模块与接口

### 2.0 四层依赖模型（本规范的总纲）

代码按**依赖方向**分四层，每层只依赖下一层与 `kernel`。这是"低耦合"的可执行定义——不是口号，是 import 规则。

```
        cli / eval（编排与评测，可依赖全部）
                     │
                  ┌──▼──────────────┐
   L4 输出格式层   │ writers/        │  IR → gp5 / musicxml / ascii_tab
                  └──┬──────────────┘       只依赖 kernel
                     │
                  ┌──▼──────────────┐
   L3 读谱框架层   │ score/          │  页→系统→小节网格、骨架、调度、验算、终裁、装配
                  └──┬──────────────┘       依赖 L2 + kernel
                     │
                  ┌──▼──────────────┐
   L2 读谱小节层   │ measure/        │  裁切规划 + 一次调用 + 小节 schema
                  └──┬──────────────┘       依赖 L1 + kernel
                     │
                  ┌──▼──────────────┐
   L1 模型接入层   │ providers/      │  HTTP、能力声明、重试、计费
                  └──┬──────────────┘       依赖 kernel
                     │
                  ┌──▼──────────────┐
      kernel       │ kernel/         │  纯数据 + 错误码 + Protocol（无 IO/无逻辑）
                  └─────────────────┘
```

#### 三条数据接缝（只传数据，不传对象）

| 接缝 | 生产者 → 消费者 | 契约 |
|---|---|---|
| **S-IF1** `MeasureTask` / `MeasureResult` | L3 → L2 | L3 给"这些小节 + 这张裁片 + 几何提示"，L2 回"逐小节的结构化事实"。**L3 不知道模型是谁** |
| **S-IF2** `IR` | L3 → L4 | IR 是唯一交付契约；writer **禁止**读 `out/` 里的中间产物，只吃 IR |
| **S-IF3** `ProviderCapabilities` | L1 → L2 | L2 的裁切规划**必须**读 caps 取上限，禁止硬编码厂商值 |

#### 依赖规则（评审时逐条核对，CI 自动检查）

| ID | 规则 |
|---|---|
| LAY-01 | `kernel/` **禁止** import 任何其他包（除标准库、pydantic，以及 Python 3.10 上读 TOML 用的 `tomli`） |
| LAY-02 | `providers/` **禁止** import `measure/`、`score/`、`writers/` |
| LAY-03 | `measure/` **禁止** import `score/`、`writers/`；**禁止**直接 `import requests`（必须经 L1） |
| LAY-04 | `score/` **禁止** import `writers/`；**禁止**直接发 HTTP |
| LAY-05 | `writers/` **禁止** import `score/`、`measure/`、`providers/` |
| LAY-06 | 任何层**禁止** import `eval/` 与 `cli/`（依赖只能向下） |
| LAY-07 | 厂商字面量（`deepseek`、`8192`、`1024`、`0.30` 等）**只允许**出现在 `providers/<name>/`、`configs/providers/`，以及 `configs/default.toml` 的 `provider.name` 一处 |
| LAY-08 | 上述规则由 `tests/test_layers.py` 用 `ast` 静态扫描强制；违反即 CI 失败 |
| LAY-09 | `score/staff/` 只许标准库、`numpy`、`cv2` 与 `kernel/`、其它 L3 模块；**禁止** import `providers/`、`measure/`、`writers/`（读谱层不调模型，`docs/spec-staff.md` §12.5） |

#### 为什么把"读谱小节"独立成层

- 它是**唯一需要调用模型**的层，也是唯一会因换模型而重写的层。把它与"页/系统结构"分开，换模型时 L3 一行不改。
- 它的接口粒度是**小节**（`MeasureResult`），但**传输粒度是系统**（一次调用读整系统 4–8 小节，摊薄固定开销）。这两件事分开：*接口按小节，调用按系统*——是这一层的核心设计。
- 将来接第二个视觉模型时，只需新增 `providers/<name>/` + 在 `configs/providers/` 加一份；L2/L3/L4 不动（V-14 要求出对照表）。

### 2.1 `geometer` —— 定位（L3）

**职责**：把输入图片变成"系统 / 小节网格 / 裁片坐标 / 几何提示"。

**输入**：`list[Path]`，class，config
**输出**：`PageSet`（§3.2）

| ID | 规则 |
|---|---|
| R-01 | 所有读图入口**必须**先 `exif_transpose` |
| R-02 | 系统 = 5 线谱线组 + 下方 TAB 线组配对；配对条件：纵向间隔 60–400 px、TAB 线距 > 1.2×谱线距 |
| R-03 | 行/列投影阈值**必须**以 deg（谱线间距）为单位表达，禁止绝对像素常量 |
| R-04 | 谱号区宽度 < 0.45×中位小节宽时，该竖线**必须**判为系统边线而非小节线 |
| R-05 | `margin` 类裁剪**禁止**叠加：谱号区已排除时只允许 ≤20 px pad |
| R-06 | 单图 >64 MP **必须**按系统边界切成多块分别处理，再合并 `PageSet` |
| R-07 | TAB 线数 ∈ {4,5,6}；不属于该集合的系统**必须**报 `E_TAB_STAFF_MISSING` |
| R-08 | 短末行（宽度 < 50% 页宽）**必须**按局部宽度单独定位，不得因全页阈值被丢弃 |
| R-09 | class 5/6：帧对齐**必须**用谱线图案的互相关求位移，禁止用时间戳推 |
| R-10 | 谱线**必须**按"行 run"交出（起止行号 + 中心 + 厚度），不能只给中心行：读谱层要按整条线厚抹线（`docs/spec-staff.md` SR-11） |

**禁止**：输出任何音高、时值、谱号、调号等语义结论。符号读取（符头、符干、横梁、休止符……）属于
§2.11 的 `staff` 子系统，不在本层的职责范围内。

### 2.2 `skeleton` —— 骨架（分级，**不是"六项"**）

**职责**：读全局参数与**中途变化点**。**不读总小节数**（由小节网格推导）。

**输入**：首页裁片 + 每个系统的左侧头部裁片（用于发现中途变化），config
**输出**：`Skeleton`（§3.2）

#### 2.2.1 分级（按"读错的后果"排，而不是按"好不好读"排）

| 级 | 项 | 读不出时 | 为什么是这个级 |
|---|---|---|---|
| **P0** | **拍号**（含中途变化） | 用"小节时值众数"推断（≥3 小节），标 `inferred` | 直接决定 A1；错一个小节后面全错 |
| **P0** | **调弦 + 弦数** | 弦数由定位层数 TAB 线；调弦由 A5 反解（`音高−品位` 众数） | 决定所有 `string/fret → 音高` |
| **P1** | **调号**（含中途变化） | 默认 C（无升降），标 `defaulted` | **不影响最终音高**（音高由 TAB 反解），但错会让 A2 假警报连片，且 GP5 显示错 |
| **P2** | 初始速度、中途速度变化 | 默认 120，标 `defaulted` | 只影响播放，人改代价最小；**能读则读** |
| **P3** | 曲名 / 作者 | 文件名 stem / 空 | 人改代价最小 |
| **—** | ~~总小节数~~ | **不读**：`measureCount = len(measures)`，由定位层推导 | 没有验证机制（旧项目纯声明）、极易读错、且**没有任何用途**——A7 用印刷小节号链就够了 |

#### 2.2.2 规则

| ID | 规则 |
|---|---|
| S-01 | 骨架**必须**由视觉调用产出；P0–P3 缺项按上表兜底，**禁止**因缺项失败 |
| S-02 | 调弦**必须**再由验算层用 `音高 − 品位` 反解验证（A5） |
| S-03 | 调号**不参与**音高计算，只用于 A2 比对与导出显示 |
| S-04 | 拍号/调号是**事件列表**（`{measure, value}`），不是单值；续行系统不印时**继承**上一值 |
| S-05 | **续行系统不印拍号/调号**（旧项目实测：老人与海、打上花火的中段系统都不印）——"没印"**不等于**"变化"，禁止把缺印当变化 |
| S-06 | 总小节数**禁止**读取；一切"总小节数不符"的检查取消 |

#### 2.2.3 中途换拍号 / 换调号的检测（两道，先读后聚类）

**(a) 直接读**：每个系统左侧若出现拍号/调号记号（且该系统不是续行），VLM **必须**读出并生成 `{measure, value}` 事件。

**(b) 聚类检测**：把"读不准"变成"可发现"。

| 报警 | 触发条件 | 动作 |
|---|---|---|
| **A11** `ts_change_suspected` | 连续 ≥3 个非休止小节的时值都等于 X，且 X ≠ 当前有效拍号 | 把该系统的头部裁片送终裁确认；确认后在该小节插入 TS 事件 |
| **A12** `key_change_suspected` | 从某小节起 A2 连续 ≥3 小节失配，且失配的半音数恒定为 d | 送终裁确认；确认后在该小节插入 KS 事件，并重算该段 `pitchClaim` 期望 |

**为什么必须做**：`Don't Cry` 就有中途换拍（`2/4 → 4/4`），旧项目当时只有全局 `timeSignature`，直接读错（`Don't Cry/blind.report.md:182-191`）。而 A11 不需要"看见"那个记号——小节时值立刻对不上，聚类就能报警。

### 2.3 `providers` —— 模型接入层（L1）

**职责**：`src/aiaomr/providers/` 是**唯一允许发 HTTP 的目录**；其余模块只依赖 `providers.base`。

**当前实现**：`deepseek_flash`（模型 `deepseek-flash` = DeepSeek-V4.1-Flash-1017），**v3 只支持这一个 provider**；其余厂商的实现留空，但接口与能力声明先立好（§2.3.2）。

| ID | 规则 |
|---|---|
| V-01 | 业务代码**禁止**出现模型名、endpoint、`detail` 等厂商字面量；一律经 `provider.name` + `caps` 取 |
| V-02 | 图片**必须**以 base64 data URL 放在 **user** 消息中；禁止放 system/assistant（DeepSeek 会对 system 里的图返回 400） |
| V-03 | 每次请求**必须**使用 JSON 模式（DeepSeek：`response_format={"type":"json_object"}`），且 prompt 必须包含字面量 `json` 与一个示例 |
| V-04 | 单请求图片数 ≤ `caps.max_images_per_request`（DeepSeek 取 14；≥15 张时单边上限从 8192 降到 4096） |
| V-05 | 空内容 / JSON 解析失败 → 按 `caps.retry_empty` 重试（默认 2，退避 1s/3s）；仍失败 → 裁片按小节二分后重试 1 次；仍失败 → 该系统级 `E_VLM_SCHEMA` |
| V-05b | 重试的修复提示**必须**只带**截断到 ≤500 字符**的错误摘要；**禁止**回传上一次完整响应 |
| V-06 | 按错误类型分类重试：`429/5xx/超时` → 退避重试 ≤ `caps.retry_http`（默认 5，优先用 `Retry-After`）；`401/403` → **禁止重试**，立即 `E_VLM_HTTP`；其余 `4xx` → 不重试，`E_VLM_HTTP` |
| V-07 | 并发数 = `min(config.vlm.max_concurrency, caps.max_concurrency)`；默认 16 |
| V-08 | 每次调用**必须**落盘 `calls/<callId>.{req,resp}.json`，含 `callId`、`promptVersion`、`schemaVersion`、`model`、`usage`、`durationMs`、`retryCount`、`validation` |
| V-09 | 成本**按每 8 小节预算计**：任一次调用（≤8 小节）记账后，若"该次调用成本（**人民币·谷价口径**）> `config.budget.cny_per_8measures`"或"累计 > `ceil(measureCount/8) × cny_per_8measures`"则中止并 `E_BUDGET_EXCEEDED` |
| V-10 | `--provider stub` 时**必须**只读 `fixtures/` 或 `calls/`，**禁止**任何网络请求 |
| V-11 | prompt **必须**拆成"稳定前缀 + 可变后缀"：公共约束与示例在前且逐字节稳定，几何/裁片相关在后。目的：命中 provider 的 prompt cache（DeepSeek cache-hit 价格是 cache-miss 的 1/50） |
| V-12 | 能力上限**必须**在运行时取 `min(配置值, caps 值)`，禁止硬编码厂商限制 |
| V-13 | 每个 provider 的 `README.md` **必须**记录：接入日期、模型版本串、计费口径、已踩的坑、与 base prompt 的差异 |
| V-14 | 新增/更换 provider **必须**重跑语料门，并在报告里附新旧对照 |

#### 2.3.1 四道闸（模型输出进入程序之前；G1–G4，区别于依赖层 L1–L4）

模型调用被视为**不完全可靠的外部服务**，输出必须依次通过四道闸，任一闸失败都不得进入 IR：

| 闸 | 做什么 | 失败处理 |
|---|---|---|
| G1 请求约束 | schema 写进 prompt + JSON 模式 + 几何提示（TAB 弦线坐标等） | — |
| G2 语法解析 | 严格 `json.loads`；**禁止**用正则抠 JSON | 重试（V-05） |
| G3 结构校验 | Pydantic 模型校验（字段、枚举、范围、小节号一致） | 带截断错误摘要重试 → 拆小裁片 |
| G4 业务判定 | §6.1 的十条不变量 | 报警 → 复读 → 终裁（**不是**丢弃） |

**Schema 由代码生成**：`kernel/ir.py` 与 `kernel/contracts.py` 里的 Pydantic 模型是唯一来源；prompt 里的字段表与校验用的模型**必须**由同一份代码派生，禁止手写两份。

#### 2.3.2 能力声明（`ProviderCapabilities`）

新增 provider 时**必须**填满下表；缺项启动即失败。目的是**不做假统一**：差异显式暴露，让裁切规划去适配。

| 能力 | DeepSeek V4.1-Flash | 用途 |
|---|---|---|
| `name` / `model` | `deepseek_flash` / `deepseek-flash` | 记录与切换 |
| `supports_vision` | true | 准入检查 |
| `image_token_rule` | `1024 × clamp(P, 0.296MP, 1.69MP) / 1.69MP`，下限 180 | 成本预估、裁片规划 |
| `max_side_px` | 8192（请求内 ≥15 张图时 4096） | 裁片尺寸上限 |
| `max_images_per_request` | 14（保守取值；文档允许 600） | 批量策略 |
| `max_image_bytes` | 32 MiB（inline） | 裁片编码 |
| `supported_formats` | JPEG / PNG / GIF / WebP | 编码选择 |
| `supports_json_mode` | true（**偶发空返回**） | 输出契约 |
| `supports_detail_param` | true（`low` 会降到 512²，**禁止**使用） | 裁片策略 |
| `supports_thinking_toggle` | true（**当前生产默认关**：P0 实测思考在整系统读数上失控，见 `docs/p0-results.md`） | 成本/质量开关 |
| `max_concurrency` | 2500 | 并发上限 |
| `pricing` | **人民币/百万 tokens**：输入 miss 1 元（谷）/2 元（峰）、输入 hit 0.02 元（谷）/0.04 元（峰）、输出 4 元（谷）/8 元（峰） | 成本核算（**一律按谷价归一化**） |
| `peak_hours` | 峰时 = **北京时间**周一至周五 9:00–12:00、14:00–18:00（不含中国法定节假日）；其余全部为空闲（谷时），谷价 = 峰价 1/2 | 成本核算 |
| `retry_empty` / `retry_http` | 2 / 5 | 重试策略 |

**新增 provider 的 checklist**（写进 `docs/providers.md`）：

1. `providers/<name>/caps.py` 填满上表；
2. `registry.py` 注册（未注册即启动报错）；
3. 继承 `providers/base.py` 的 `VisionProvider`，实现 `read_system(crop, hints) -> dict`；
4. 若需厂商特殊口径，只在 `prompts/<name>/` 写**差异**，禁止复制 base；
5. 写 `README.md`（V-13）；
6. 用 `fixtures/<name>/` 录制 ≥20 个真实调用；
7. 跑 `eval --provider <name>`，与 deepseek-flash 出对照表（V-14）。

### 2.4 `measure` —— 读谱小节层（L2）

**职责**：按 §5 裁切规则生成裁片 → 调 `providers` → 校验 schema → 合并为 `MeasureResult[]`。

**接口粒度 = 小节；传输粒度 = 系统**。L3 只看见"逐小节的事实"，看不见"一次调用读了几小节"。

| ID | 规则 |
|---|---|
| RD-01 | 裁切单位**必须**是完整系统（五线谱带 + TAB 带） |
| RD-02 | 单系统像素 >1.6 MP 时**必须**按小节边界等分为 k 份，`k = ceil(P / 1.6MP)`，每份 ≤1.6 MP；单系统像素 <1.6 MP 时**必须**上采样到 1.6 MP（P0 实测：0.88 MP 直读只有 5/7 小节对，上采样后 7/7，见 `docs/p0-results.md`） |
| RD-03 | 拆分后第 2..k 份**必须**在左侧拼接同系统的谱号/调号条（宽 40–100 px），并在 prompt 中说明"左侧是引用条" |
| RD-04 | 任何裁片**必须**包含完整谱号区；不含者**禁止**送出 |
| RD-05 | 单次调用请求的小节数 ≤8 |
| RD-06 | 模型输出**必须**同时含 `string`、`fret` 与 `pitch`；缺任一字段即 `E_VLM_SCHEMA` |
| RD-06b | 模型输出的 `string` 用 **Guitar Pro 习惯**：`1` = 最上面那条 TAB 线（最高音弦），`stringCount` = 最下面那条。L2 收到后**必须**翻成 IR 约定（`ir_string = stringCount - model_string + 1`）。提示词按 GP 习惯描述并给一个上下不对称的例子；**禁止**假设模型会按 IR 编号输出——P0 实测它会稳定地按 GP 编号，提示词改不动（见 `docs/p0-results.md`） |
| RD-07 | 模型返回的小节号必须与请求一致，顺序不符即 `E_VLM_SCHEMA` |
| RD-08 | 对外**只**暴露 `read_systems(tasks: list[MeasureTask]) -> list[MeasureResult]`；**禁止**把 provider 客户端、裁片路径、原始响应泄漏给 L3 |
| RD-09 | 裁切上限**必须**取 `min(config, caps)`；`caps` 缺失即启动失败（V-12） |
| RD-10 | 本层**禁止**判断对错、**禁止**补写任何 beat；它只负责"把像素变成结构化事实并校验形状" |

### 2.5 `verify` —— 验算与报警（L3）

**职责**：把 `MeasureResult[]` + `PageSet` + `Skeleton` 合成 IR 草稿，并跑 §6 全部不变量。

| ID | 规则 |
|---|---|
| F-01 | 音高 `pitch` **必须**由 `tuning[string-1] + fret` 计算；模型给的 `pitchClaim` 只用于 A2 比对，**不得**直接进入 IR 的权威字段 |
| F-02 | **禁止**任何"差额补齐"式写入：不允许程序自己生成 beat 或休止 |
| F-03 | 每条报警**必须**记录 `{rule, measure, claimed, expected, evidence}` |
| F-04 | 报警**不得**阻止导出（与旧项目 `REFUSING TO BUILD` 的关键差异） |

### 2.6 `adjudicate` —— 终裁（L3）

**职责**：对 A1–A10 报警项发起复读与终裁。

| ID | 规则 |
|---|---|
| AD-01 | 每条报警**必须**按类型选择复读方式：A9（多小节休止条数）→ 用 contact sheet 一次读完；其余 → V2 复读（2–4 小节放大，含 header 条）。复读**必须**盲读：只带报警规则与 claim/expected，**禁止**携带上一次读出的音符列表或整段响应 |
| AD-02 | 两次**独立**读数一致 → 采纳；不一致 → 送终裁，输入为两次结果 + 报警原因 + 两张裁片 |
| AD-03 | 终裁**可以**推翻定位层与读取层的任何结论，但**必须**给出理由与引用坐标 |
| AD-04 | 终裁记录**必须**写入 `judgements[]`，含模型名、prompt 版本、时间 |
| AD-05 | `alarm_resolved` 必须为 1.00：任何报警不得停留在未记录状态 |

**为什么盲读**：复读提示里若带上第一次读出的音符，模型很容易顺着自己的答案点头，一致率会虚高，报警等于没查。报警规则本身（哪一小节、哪条规则、claim 与 expected 各是多少）已经足够让模型知道该看什么，不需要把上一次的完整读数再给它一遍。

### 2.7 `assemble` —— 装配（L3）

| ID | 规则 |
|---|---|
| AS-01 | 多小节休止**必须**展开为 N 个空小节，N 来自 A9 的读数；N ≤ 0 必须报警 |
| AS-02 | 反复/房子/D.S./Coda **必须**生成演奏顺序表；音符只写一次，禁止物理重复展开 |
| AS-03 | 小节编号以印刷号优先、累加兜底；冲突报警 A7 |
| AS-04 | 只支持单声部；多声部**必须**只保留主声部并在报告中记录丢弃 |

### 2.8 `writers` —— 输出格式层（L4）

| ID | 规则 |
|---|---|
| E-01 | 写出**必须**经 `validate → build → verify` 三步，任一步失败 → 对应错误码，不产出文件。`validate` 只判断结构上能否表达，不做音乐正确性判断（节奏对不对是报警的事） |
| E-02 | IR→GP 的弦号翻转**只允许**发生在 `writers/gp5/` 一处（IR 1=最低弦 → GP 1=最高弦）；模型输出(GP)→IR 的翻转**只允许**发生在 `measure/` 一处（RD-06b） |
| E-03 | `title/artist/album/tabber` **必须**逐字段 `encode(cp936)`，编不进 → `E_BUILD_VALIDATE` |
| E-04 | 中文标题**禁止**依赖 PyGuitarPro 自身往返验证（它测不出编码问题） |
| E-05 | 审计 `tools/audit.mjs` **必须**检查不变量 A（音高恒等式）与 B（小节时值），任一非零即报告失败 |
| E-06 | writer **必须**实现 `Writer` Protocol（`write(ir, path) -> Report`）并注册到 `writers/registry.py`；新增格式不得改 `score/` |
| E-07 | writer **禁止**读取 `out/` 里的中间产物（calls/、crops/、measures/），**只吃 IR** |

### 2.9 `eval` —— 评测（非层）

| ID | 规则 |
|---|---|
| EV-01 | 阈值**必须**在 `configs/thresholds.toml` 中先声明，代码不得内联 |
| EV-02 | 每个指标**必须**带分母 |
| EV-03 | `--selftest` **必须**先证明尺子能测出人为破坏，否则 `HARNESS UNVERIFIED` 并拒绝计分 |
| EV-04 | 参数只从 spec 取，**禁止**从真值取 |

### 2.10 `cli` —— 唯一入口

子命令：`ingest`、`locate`、`skeleton`、`staff`、`read`、`verify`、`adjudicate`、`assemble`、`build`、`eval`、`run`。

| 全局参数 | 作用 |
|---|---|
| `--format human\|ndjson\|auto` | 见 §10.2 |
| `--provider <name>` | 选择 provider（默认 `deepseek_flash`） |
| `--until <stage>` | 停在指定阶段之后 |
| `--resume` | 从 `out/<song>/` 缓存继续；等价于直接重跑（幂等键命中即跳过） |
| `--force <stage>` | 重跑该阶段及其下游 |
| `-v` / `-vv` / `--quiet` | stderr 日志级别 |

`run` 等价于按序执行上述全部。

**禁止**：`cli.py` 里出现任何业务判断（阈值、几何参数、厂商参数）；它只负责解析参数、按序调用各层、把结果转成 §10 的事件流。

### 2.11 `staff` —— 读五线谱（L3）

**职责**：把定位好的页面读数成"每个小节的符号类别与时值"，给出 `MeasureRhythm` 结论和 abstain 理由。
完整规则见配套规范 **`docs/spec-staff.md`**（编号 SR-xx、AR-xx），本节只定它在系统里的位置和硬边界。
目录、文件划分与产物归属见该文件 §12；本层是**独立阶段** `staff`（`skeleton` 之后、`read` 之前，不联网），
产物写 `out/<song>/staff/rhythm.json`，事件为 `staff.measure` / `staff.done`。

**输入**：`arr`、`System`（含谱线行 run）、`MeasureBox`、`deg`、`Skeleton.timeSignatures`
**输出**：`MeasureRhythm`（§3.2）

| ID | 规则 |
|---|---|
| ST-01 | 只读定位层交出的 `System`/`MeasureBox`/`deg`/谱线行；**禁止**在内部重新定位系统或小节 |
| ST-02 | 输出只有符号类别与时值；**禁止**输出音高、弦号、品位（那是 TAB 与模型的事，F-01） |
| ST-03 | 三条铁律（`docs/spec-staff.md` §2）：**横向间距禁止推时值与 onset**；**拍格是隐含条件、不是切图依据**；**判不准就 abstain，禁止用和校验反推时值** |
| ST-04 | 一条判据只做一件事（符头/符干/横梁/符尾/附点/休止各一条），阈值只进 §5 参数表，判据必须能单测 |
| ST-05 | 模板只能从**本页自举**（medoid，确定性），禁止依赖外部字体文件、禁止随机初始化 |
| ST-06 | abstain 必须带固定原因编号 AR-01..12，按编号计数写进 `metrics.json`（§8.2） |
| ST-07 | 本层不读的记谱（连音线、三连音、装饰音、双声部、反复）在检出/疑似检出时**整小节 abstain**，禁止"顺手支持" |
| ST-08 | 与模型读数的合并发生在装配层；本层**禁止**调用模型，也禁止知道模型存在 |
| ST-09 | 报警不阻断：几何结论缺失或与模型不一致，只是把该小节变成争议点（A8 候选），流程继续 |

**为什么单独立一层**：时值判对和"判不准时闭嘴"是两件事，混在定位层里会同时破坏 R-03 与 ST-01；
独立之后 `score/locate/` 保持纯 CV，`staff` 的每条判据都能拿真图样本单测，abstain 率也可以单独量。

---

## 3. 数据结构

### 3.1 IR（`ir.json`，`version: "3.0"`）

```jsonc
{
  "version": "3.0",
  "meta": {
    "provider": "deepseek_flash",
    "model": "deepseek-flash",
    "promptVersion": "p0",
    "schemaVersion": "3.0",
    "generatedAt": "2026-10-17T23:40:00Z"
  },
  "source": { "class": 3, "kind": "image", "files": ["…"], "inputSha256": "…" },
  "score": {
    "title": "", "artist": "", "tabber": "",
    "tuning": [28, 33, 38, 43],                    // MIDI，低→高，长度 = stringCount
    "stringCount": 4,
    "timeSignatures": [{ "measure": 1, "beats": 4, "beatType": 4 },
                       { "measure": 29, "beats": 2, "beatType": 4 }],   // 中途换拍是事件列表
    "keySignatures": [{ "measure": 1, "key": "BMajor" },
                      { "measure": 45, "key": "EMajor" }],             // 中途换调也是事件列表
    "tempos": [{ "measure": 1, "bpm": 96 }],                           // 能读则读；读不到就用默认 120
    "clefTranspose": -12,
    "fretCount": 24,
    "measureCount": 107                            // 计算字段：len(measures)，不读取
  },
  "skeletonProvenance": {                          // 每项的来源，便于排障
    "timeSignatures": "read|inferred|defaulted",
    "tuning": "read|derived",
    "keySignatures": "read|defaulted",
    "tempos": "read|defaulted",
    "title": "read|filename",
    "artist": "read|empty"
  },
  "measures": [{
    "index": 1,
    "printed": 1,                                  // 可为 null
    "rest": true,
    "multiRest": 2,                                // 展开前的条数；普通小节为 1
    "beats": [{
      "duration": "eighth",                        // whole|half|quarter|eighth|16th|32nd
      "dots": 0,                                   // 0|1|2（2 需要 emit 扩展，见 §4.3）
      "rest": false,
      "notes": [{
        "string": 1, "fret": 6, "tie": false,
        "tieFromPrevious": false,                  // 无印刷数字的音头必须为 true（A4b）
        "digit": { "value": "6", "glyphs": 1, "bound": true },  // 印刷数字绑定；无数字时省略
        "techniques": ["slide_in_from_below"],       // 枚举见 §3.4
        "pitch": 43,                               // 权威值：由 tuning[string-1]+fret 计算
        "pitchClaim": 43                           // 模型从五线谱读到的 MIDI，仅用于 A2 比对
      }],
      "prov": "read",                              // read | derived（derived 仅允许来自模型明示）
      "evidence": { "system": 1, "crop": [0, 0, 100, 100], "call": "c0007" }
    }]
  }],
  "structure": {
    "repeats": [{ "start": 1, "end": 8, "times": 2 }],
    "endings": [{ "measure": 8, "number": 1 }],
    "jumps": [{ "type": "dc", "measure": 12 }],
    "sections": [{ "measure": 17, "label": "Chorus" }]
  },
  "judgements": [{
    "id": "j001", "measure": 12, "rule": "bar_duration",
    "claimed": 4320, "expected": 3840, "final": 3840,
    "reason": "…", "model": "deepseek-flash", "promptVersion": "p0",
    "crops": ["…"], "ts": "…"
  }],
  "build": { "gp5": "…", "roundtrip": "OK", "audit": { "pitchMismatch": 0, "barErrors": 0 } }
}
```

**不变量**：

- `len(score.tuning) == score.stringCount`
- `tuning` 严格递增
- `measures[].index` 从 1 连续递增
- `measureCount == len(measures)`（**计算字段，不读取**）
- 每个非 rest 小节的 `beats` 时值之和 == **该小节生效的**拍号（取 `timeSignatures` 中 `measure ≤ index` 的最后一项）
- `timeSignatures` / `keySignatures` / `tempos` 的 `measure` 严格递增，且每条都是"从该小节起生效"
- `beats[].notes[].string ∈ 1..stringCount`，`fret ∈ 0..fretCount`

### 3.2 中间结构（`kernel/contracts.py`）

| 类型 | 字段 |
|---|---|
| `PageSet` | `pages: list[Page]`、`class`、`degGlobal` |
| `Page` | `path`、`width`、`height`、`deg`、`systems: list[System]` |
| `System` | `id`、`page`、`y0/y1`（五线谱带）、`tabY0/tabY1`、`tabLines: list[float]`、`measures: list[MeasureBox]`、`headerX0/x1`（谱号区） |
| `MeasureBox` | `index`、`printed`、`x0/x1`、`width` |
| `Crop` | `path`、`box=[l,t,r,b]`、`kind`（system / reread / sheet）、`px`、`deg`、**`has_clef: bool`**（不含谱号区的裁片禁止送出，RD-04） |
| `MeasureTask` | `system`、`measures: list[MeasureBox]`、`crop`、`hints`、`callId` |
| `MeasureRead` | `index`、`beats`、`unreadable` |
| `MeasureResult` | `callId`、`reads: list[MeasureRead]`、`usage`（可选，原始用量）、`errorCode`（可选，系统级失败时记录） |
| `Skeleton` | `timeSignatures`、`keySignatures`、`tempos`、`tuning`、`stringCount`、`title`、`artist`、`provenance`、`clefTranspose`（低音谱号固定 −12）、`fretCount`（默认 24） |
| `RhythmBeat` | `x`（只用于排序与证据）、`kind`（note/rest）、`duration`（whole…32nd，可空=abstain）、`dots`、`noteCount`、`head`（hollow/filled，休止为空）、`beams`（入射横梁条数或符尾条数）、`group`、`confidence`（只用于选争议点，禁止软判决）、`evidence` |
| `Abstain` | `reason`（AR-01..12）、`measure`、`beat`（可空）、`detail` |
| `MeasureRhythm` | `index`、`status`（ok/partial/unknown）、`beats: list[RhythmBeat]`、`abstains: list[Abstain]`、`ticks`（仅 ok 有意义）、`deg` |
| `Judgement` | 见 IR |

### 3.3 错误码

下表退出码仅用于**阶段级/全局级**失败；系统级失败（单个系统切不开、单次调用失败）按 §7 记录并继续，不设退出码。

| 码 | 含义 | 级别 | 退出码 |
|---|---|---|---|
| `E_INPUT_UNREADABLE` | 图片无法解码 / >64 MP 且无法切片 | 阶段 | 1 |
| `E_NO_SYSTEM` | 未找到任何合格系统 | 阶段 | 1 |
| `E_TAB_STAFF_MISSING` | 系统 TAB 线数 ∉ {4,5,6} | **系统** | — |
| `E_SKELETON_UNREAD` | 连骨架裁片都做不出来（无法定位页眉区）；**字段缺失不触发本错误** | 阶段 | 1 |
| `E_VLM_HTTP` | API 4xx/网络错误（持续失败） | 全局 | 2 |
| `E_VLM_EMPTY` | 重试后仍空返回 | **系统** | — |
| `E_VLM_SCHEMA` | JSON 结构不符（重试+拆分后仍不符） | **系统** | — |
| `E_BUDGET_EXCEEDED` | 单首成本超限 | 全局 | 3 |
| `E_BUILD_VALIDATE` | 写出前校验失败 | 阶段 | 2 |
| `E_BUILD_ROUNDTRIP` | 写出后重解析不一致 | 阶段 | 2 |
| `E_AUDIT` | alphaTab 审计不变量被违反 | 阶段 | 2 |

### 3.4 技巧枚举（按 GP5 能表达的能力分组）

GP5 的"技巧"分四类能力，**不是一堆平级标签**：音符效果（note effect）、拍效果（beat effect，每拍只能一个值）、音符类型（note type）、以及 GP5 根本表达不了的。枚举必须按这四类组织，否则导出时会静默丢信息。

#### A. 音符级（note effect）——每音符独立，可精确映射

| 枚举值 | 谱面常见写法（贝斯 TAB） | GP5 映射 |
|---|---|---|
| `slide_in_from_below` | `2/4`（斜杠在数字前） | slide，intoFromBelow |
| `slide_in_from_above` | `4\2` | slide，intoFromAbove |
| `slide_out_down` | `2\`（斜杠在后） | slide，shiftSlide 下 |
| `slide_out_up` | `2/` | slide，shiftSlide 上 |
| `hammer` | `2h4` | note effect hammer/pull（击） |
| `pull` | `4p2` | note effect hammer/pull（勾） |
| `bend` | `b`、`^`、`full` | note effect bend（需要高度，读不到则记 `bend_unknown`） |
| `vibrato` | `~` | note effect vibrato |
| `trill` | `tr` | note effect trill |
| `grace` | 小音符 | note effect grace |
| `staccato` | 数字上方/下方的小点 | note effect staccato |
| `palm_mute` | `P.M.` / `PM` | note effect palm mute |
| `let_ring` | `let ring` | note effect let ring |
| `harmonic_natural` | `<>` / `Harm.` | note effect harmonic（natural） |
| `harmonic_artificial` | `A.H.` | note effect harmonic（artificial，需记基音） |
| `harmonic_pinch` | `P.H.` / `S.H.` | note effect harmonic（pinch/tap） |
| `ghost` | `(5)` 括号 | note effect ghost |
| `accent` | `>` | note effect accent |
| `heavy_accent` | `^` 在数字上方 | note effect heavy accent |
| `tremolo_picking` | 数字上的斜线组 | note effect tremolo |

#### B. 拍级（beat effect）——**每拍只能一个值**

| 枚举值 | 谱面常见写法 | GP5 映射 | 约束 |
|---|---|---|---|
| `slap` | `S` / `T`（拇指） | beat string effect = slapping | 一拍内与 `pop` 互斥 |
| `pop` | `P`（勾弦） | beat string effect = popping | 与 `pull` 的 `p` 区分：大写且独立标注才是 pop |
| `tap` | `T` / `tapping` | beat string effect = tapping | 与 `slap` 的拇指标记易混 |

**冲突规则**：一拍内若同时出现 `slap` 与 `pop`，**必须**拆成两拍（时值允许时）；拆不开则保留优先级 `slap > pop > tap`，把另一个写入 `judgements[]` 的 `droppedTechniques` 字段。**禁止**静默丢弃。

#### C. 音符类型（不是 effect）

| 枚举值 | 谱面写法 | GP5 映射 |
|---|---|---|
| `dead_note` | 数字位写 `x`，或 `X` | note type 3（dead/muted），**不是** ghost |

#### D. 记录但不映射（GP5 表达不了，写进 IR 供将来 `.gp`/GPX 使用）

`wide_vibrato`、`fret_hand_mute`、`pickstroke`、`tremolo_bar`、`pick_scrape`、`thumbing`、`continuous_dynamics`、`microtone`。

#### E. 不在枚举内的一律

丢弃并计入 `unknown_techniques`，**同时**把该裁剪片写入 `judgements[]`（便于事后补枚举）。

**可读性提示**：A 组里 `bend` 的高度、`harmonic` 的人工/自然区分、`grace` 的时值，在低 deg 裁片上是首批读不出来的项——读不出时**必须**标 `unreadable`，不得猜。

---

## 4. 外部契约

### 4.1 Provider 调用（当前唯一实现：DeepSeek V4.1-Flash）

本节描述 **`deepseek_flash`** 的具体口径；其他 provider 的同类口径写在自己的 `providers/<name>/README.md`，业务层不得直接引用。

| 项 | 值 |
|---|---|
| Endpoint | `https://api.deepseek.com/chat/completions`（OpenAI 兼容） |
| 模型 | `deepseek-flash`（= DeepSeek-V4.1-Flash-1017；旧名 `deepseek-v4-flash` / `deepseek-v4-flash-vision-exp` 仍被接受） |
| 认证 | `Authorization: Bearer $DEEPSEEK_API_KEY`；**禁止**写入仓库、日志、fixture |
| 图片 | `{"type":"image_url","image_url":{"url":"data:image/png;base64,…","detail":"original"}}` |
| 文本 | `{"type":"text","text":"…"}`，**不得**出现 `data:` 之外的 URL |
| 参数白名单 | 只允许 `model / messages / response_format / max_tokens / thinking`；**禁止**传未在文档列出的字段 |
| 预算 | 从响应 `usage` 累计；离线估算用 `1024 × clamp(P, 0.296MP, 1.69MP)/1.69MP`，下限 180 |
| prompt cache | 稳定前缀逐字节不变可命中 cache-hit 价（**谷价 0.02 元/1M，是 miss 的 1/50**）；**这是 V-11 存在的原因** |
| 输出长度 | `max_tokens` 必须显式设置，按"小节数 × 预算 + 余量"估；禁止依赖默认值 |

### 4.2 Prompt 模板（归属各层的 `prompts/`）

**谁拥有 prompt**：任务属于哪一层，prompt 就放哪一层，避免"一个顶层 prompts/ 目录变成第二个业务逻辑库"。

| 模板 | 归属层 | 路径 |
|---|---|---|
| 小节读取 | L2 | `measure/prompts/system.md` |
| 骨架（分级） | L3 | `score/prompts/skeleton.md` |
| 复读 | L3 | `score/prompts/reread.md` |
| 终裁 | L3 | `score/prompts/adjudicate.md` |
| 厂商差异 | L1 | `providers/<name>/prompts/*.md`（**只写差异**，按同名文件覆盖对应段落） |

合并规则：`base（层内）` → `provider 覆盖` → 运行时变量注入。覆盖内容**必须**在 provider README 里列清楚（V-13）。

**所有模板必须包含**：

1. 字面量 `json` 与一个输出示例；
2. 输出 schema 的完整字段表；
3. 明确"看不清就写 `unreadable: true`，**禁止**猜测或补全"；
4. 明确"**不要**输出音高之外的推理过程，不要输出 IR，不要写文件"；
5. 版本号占位符 `{{promptVersion}}`，随请求落盘；
6. **稳定前缀**：第 1–5 项与示例必须放在最前且逐字节稳定，运行时变量只允许出现在其后（V-11）。

**`system.md` 必须额外注入**：

- 系统 id、小节 x 范围、印刷小节号；
- **TAB 弦线 y 坐标数组**（自上而下对应 string = stringCount..1）；
- `tuning`、`stringCount`、拍号、调号；
- 若为拆分裁片，注明"左侧 40–100 px 是引用条，不属于本系统内容"。

**`reread.md` 必须额外注入**：原报警规则、claim/expected。**禁止**携带上一次读出的音符列表或整段响应——复读必须是盲读，否则两次读数不独立，AD-02 的"两次一致就采纳"就没有意义。

**`adjudicate.md` 必须额外注入**：两次读数、两张裁片的来源说明、裁定要求（给出最终值 + 理由 + 引用坐标）。

**禁止**在 prompt 中出现：真值、`truth.gp` 内容、任何评测指标。

### 4.3 GP5 写出（`writers/gp5/`）

| IR | GP5 |
|---|---|
| `duration` | `_BASE_DURATIONS` 键；`dots=1` → `"dotted" + Cap(name)` |
| `dots=2` | **暂不支持** → `E_BUILD_VALIDATE` 并记录（P2 扩展） |
| `rest: true` 的 beat | `BeatStatus.rest` |
| `tie` | note type 2 |
| `string` | `n_strings - IR.string + 1`（唯一翻转点） |
| `techniques` | 映射到 note effect / beat effect；未支持项丢弃并计数 |
| 多小节休止 | 已由 `assemble` 展开为空小节 |

**必须**在写出前 `validate()`：调弦升序、string 范围、fret 范围、时值名已知、`dots ≤ 1`、非休止拍必须有音符、文本可 cp936 编码。**小节时值合计不属于写出校验**——它是 A1 报警（§6.1），报警不阻断（F-04）；没有生效拍号时按 4/4 写出并记 warning。
**必须**在写出后 `verify()`：重新 `parse` 并逐音符比对；不一致 → `E_BUILD_ROUNDTRIP`。

### 4.4 审计（`tools/audit.mjs`）

输入 `.gp5`，输出 JSON：`{ pitchMismatch, barErrors, details[] }`。
判定：`pitchMismatch == 0 && barErrors == 0` 才算通过；否则 `E_AUDIT`。

---

## 5. 参数表

**与 provider 无关的参数**放 `configs/default.toml`（下表）；**provider 专属参数**放 `configs/providers/<name>.toml`（模型名、并发、预算、重试、温度、thinking）。

| 参数 | 默认 | 说明 |
|---|---|---|
| `provider.name` | `deepseek_flash` | 当前唯一实现；其余名字启动即报错 |
| `crop.target_mp_min` | 1.6 | 裁片像素下限；低于此值**上采样**到 1.6 MP（P0 实测，见 `docs/p0-results.md`） |
| `crop.target_mp_max` | 1.6 | 裁片像素上限；高于此值按小节边界拆分 |
| `crop.max_side_px` | 4096 | 长边上限；运行时再与 `caps.max_side_px` 取 min |
| `crop.max_measures_per_call` | 8 | 单次调用小节数 |
| `crop.header_strip_px` | 40–100 | 拆分裁片的引用条宽度（按 deg 取 `4×deg`，clamp 到该区间） |
| `read.min_deg_eff` | 12 | 压缩后有效谱线间距下限；低于此值记录 WARN（不阻断） |
| `budget.cny_per_8measures` | 0.0150 | **成本预算的唯一单位：人民币元 / 每 8 小节，谷价（空闲时段）口径**；四位小数。P0 实测（thinking 关、1.6 MP 裁片）每 8 小节约 ¥0.004；单首派生上限 = `ceil(measureCount/8) × 该值` |
| `budget.precision` | 0.0001 | 记账精度（四位小数）。**它不是账单**：只用于预算闸与回归比较，不与 provider 对账 |
| `locate.line_frac_min` | 0.60 | 谱线行覆盖率下限（旧项目实测 0.72 会漏切） |
| `locate.max_line_thickness_px` | 25 | 超过即判为黑边/进度条 |
| `locate.tab_pair_gap_px` | 60–400 | 五线谱带与 TAB 带的纵向间隔 |
| `emit.encoding` | `cp936` | GP5 文本编码（本机 ANSI 代码页） |
| `adjudicate.max_rounds` | 2 | 复读+终裁的最大轮数，防止无限循环 |
| `retain.crops` | true | 是否保留裁片图（证据留存，占空间） |
| `skeleton.infer_ts_min_measures` | 3 | 拍号读不出时，推断"小节时值众数"所需的最少小节数 |
| `skeleton.default_tempo` | 120 | 速度读不出时的默认值 |
| `skeleton.default_key` | `CMajor` | 调号读不出时的默认值（不影响音高，只影响 A2 与显示） |
| `skeleton.title_from_filename` | true | 曲名读不出时用文件名 stem |
| `structure.change_min_run` | 3 | A11/A12 聚类检测所需的最小连续小节数 |
| `run.inflight_grace_ms` | 30000 | 阻断时等待在途请求返回的宽限（用于准确记账） |
| `staff.band_margin_deg` | 4.0 | 五线谱带上下余量（`spec-staff.md` SR-10/SR-12） |
| `staff.line_erase_pad_px` | 1 | 抹谱线时按整条线厚再加的抗锯齿余量（SR-11） |
| `staff.head_w_deg` | 0.7–1.9 | 符头宽度范围 |
| `staff.head_h_deg` | 0.3–1.2 | 符头高度范围 |
| `staff.head_fill_hollow_max` | 0.55 | 填充率低于此为空心（真图标定前为初值） |
| `staff.head_fill_filled_min` | 0.75 | 填充率高于此为实心；中间 abstain |
| `staff.template_ncc_min` | 0.75 | 模板匹配采纳下限 |
| `staff.stem_len_deg` | 2.0–5.5 | 符干长度范围 |
| `staff.beam_coverage` | 0.85 | 横梁段覆盖率下限 |
| `staff.beam_thickness_deg` | 0.3–0.9 | 横梁段厚度范围 |
| `staff.layer_gap_deg` | 0.8 | 横梁分层 y 差阈值 |
| `staff.dot_min_area_px` | 3 | 附点的绝对面积下限（平方像素；抗噪） |
| `staff.dot_max_area_deg2` | 0.45 | 附点面积上限 = 该值 × deg²（挡掉整行墨迹） |
| `staff.pair_max_deg` | 1.2 | 符头与符干配对的最大距离 |

**`configs/providers/deepseek-flash.toml`**：`model`、`max_concurrency`、`retry_empty`、`retry_http`、`thinking`（开/关，当前默认关）、`max_tokens_rule`、`temperature`。

**禁止**在代码中出现未列入本表的魔数；新增参数必须先进本表。

---

## 6. 不变量与禁止事项

### 6.1 不变量（验算层必须全部检查）

| ID | 不变量 | 失败即 |
|---|---|---|
| A1 | 非 rest 小节的时值之和 == **该小节生效的**拍号（`timeSignatures` 最近一项） | 报警 |
| A2 | `pitchClaim == tuning[string-1] + fret`（`pitchClaim` 缺失时跳过本项） | 报警 |
| A3 | `string ∈ 1..N`，`fret ∈ 0..fretCount` | 报警 |
| **A4** | **数字↔音头的不对称**：`数字数 D ≤ 音头数 H` 恒成立；`D > H` 即报警（有音头没被检出）。**这里比的是"数字"不是"字形"**：`12` 是 1 个数字、2 个字形 | 报警 |
| **A4b** | **每个数字必须绑定恰好一个音头**（保序单射）；`H > D` 时，每个未绑定的音头**必须**标 `tieFromPrevious=true`，否则报警（"数字没印"或"音头多检"） | 报警 |
| A5 | `音高 − 品位` 的众数 == 声明调弦 | 报警 |
| A6 | 连音两端音高相同 | 报警 |
| A7 | 印刷小节号严格递增且与累加一致 | 报警 |
| A8 | 字形模板标签 == 模型 `fret` | 报警 |
| A9 | 多小节休止条数 > 0 | 报警 |
| A10 | 模型未标 `unreadable` | 报警 |
| **A11** | 连续 ≥3 个非休止小节时值 = X 且 X ≠ 当前有效拍号 → 提出**换拍号**候选 | 报警 → 终裁（§2.2.3） |
| **A12** | 从某小节起 A2 连续 ≥3 小节失配且失配半音数恒定 → 提出**换调号**候选 | 报警 → 终裁（§2.2.3） |

**A4/A4b 的语义必须写进实现**（旧项目栽过两次）：

- **一个印刷数字 ⇒ 恰好一个音**；**一个音 ⇒ 可以没有数字**（连音后半、或字形未解码）。
- 所以 `D ≤ H` 正常、`D > H` 才是漏检；**反过来把 `H > D` 当异常会误杀正确谱**。
- 旧项目 `老人与海` m32 印 7 个数字 / 13 个字形 / 7 个音头——一开始拿**字形**比音头，报了一条假 EXC，让严格模式拒了一个完全正确的 spec。
- 休止**不在 TAB 上出现**（TAB 只印被弹响的音），所以休止只能来自记谱侧/模型，**不得**用"音头少了"去推。

### 6.2 禁止事项（评审时逐条核对）

1. 禁止把整页（>2 MP）喂给视觉模型。
2. 禁止单发单个数字/单个音符的裁片（必须拼 contact sheet）。
3. 禁止对裁片做内容放大（只在像素预算不足时允许 LANCZOS 升采样，且必须记录）。
4. 禁止程序补写任何 beat / 休止 / 时值。
5. 禁止在交付物中写入任何"存疑/待确认"字段。
6. 禁止在 prompt 中出现真值或指标。
7. 禁止依赖 `detail: low`（会压到 512×512）。
8. 禁止在 `writers/gp5/` 之外翻转 `string`。
9. 禁止在未跑 `--selftest` 的评测器上引用任何分数。
10. 禁止为了过验收门而调整阈值（改阈值必须单独提交并写明理由）。
11. 禁止用横向间距、横向位置或像素比例推断时值或 onset：刻谱间距只反映排版美观，与音乐时长无关（`spec-staff.md` SR-01）。横坐标只允许用于"谁在谁左边"和"谁和谁相连"。
12. 禁止按拍格切图或按拍位裁剪窗口：拍号与拍格只作为装配时的隐含条件，用来否决结论（SR-02）。
13. 禁止用"小节时值之和"反推某个音符的时值：和校验只能否决，不能生成（SR-03）。
14. 真值 JSON 必须由 `tools/dump.mjs` 现导，并在加载时校验每小节时值之和等于拍号；不通过即 `EvalError`（§9.2）。

---

## 7. 失败语义

错误分两级，**只有阶段级/全局级才带退出码**：

| 级别 | 例子 | 行为 |
|---|---|---|
| **系统级** | 单个系统 `E_TAB_STAFF_MISSING`、单次调用重试后仍 `E_VLM_EMPTY` | **记录到 `judgements[]` 并继续处理其余系统**；不设退出码；该系统的报警照常进入复读/终裁 |
| **阶段级** | 整张图 `E_NO_SYSTEM`、`E_INPUT_UNREADABLE`、`E_SKELETON_UNREAD`（骨架裁片做不出来）、`E_BUILD_VALIDATE`、`E_BUILD_ROUNDTRIP` | 立即停止该阶段，按 §3.3 退出码返回 |
| **全局级** | `E_VLM_HTTP`（认证/网络持续失败）、`E_BUDGET_EXCEEDED` | 立即停止整首，保留已产生的产物 |

| 情况 | 行为 |
|---|---|
| 某系统读取失败 | **继续**其余系统；该系统相关报警全部记录，导出照常进行 |
| 骨架某字段缺失 | 用 `config.skeleton.defaults` 兜底，报告标 `defaulted` |
| 审计失败 | `.gp5` 已产出但标记 `build.audit.failed=true`，退出码 2 |

**唯一硬停止条件**：输入不可用、成本超限、写出校验失败。其余一律"记录 + 继续"。

### 7.1 阻断之后会发生什么

**阻断 = 停止推进，不是丢弃产物。**四种阻断，行为不同：

| 类型 | 触发 | 停止范围 | 已留产物 | 退出码 |
|---|---|---|---|---|
| **输入级** | `E_INPUT_UNREADABLE`、`E_NO_SYSTEM` | 整首不开始 | `input.json`（若已登记）、`events.ndjson`、`run.log` | 1 |
| **阶段级** | `E_SKELETON_UNREAD`（骨架裁片做不出）、`E_BUILD_VALIDATE`、`E_BUILD_ROUNDTRIP` | 停在该阶段 | 该阶段之前的**全部**产物（含 `calls/`、`crops/`、`measures/`）；**无 `.gp5`** | 2 |
| **全局级** | `E_VLM_HTTP`（持续失败）、`E_BUDGET_EXCEEDED` | 停在任意阶段 | 之前所有产物 + 已完成的 `measures/` | 2 / 3 |
| **中断** | SIGINT / SIGTERM | 当前阶段停止 | 之前所有产物；未完成的 `.tmp` **不会被读到** | 130 |

#### 7.1.1 阻断时必须输出的四样东西

1. **`run.finished` 事件**（`status` = `failed` / `aborted`）：

```jsonc
{"v":1,"seq":498,"ts":"…","level":"error","stage":"build","event":"run.finished",
 "data":{
   "status":"failed","exitCode":2,
   "block":{
     "stage":"build","error":"E_BUILD_VALIDATE",
     "reason":"m57 ticks 4020 ≠ 3840",
     "location":{"system":9,"measure":57,"crop":[…]},
     "suggestions":["重读 m56-58（A1 报警未消）","检查 m57 是否漏读休止"]
   },
   "spentCny":0.0721, "spentCnyPer8":0.0062,
   "artifacts":["out/x/pageset.json","out/x/calls/…","out/x/measures/…"],
   "resumable":true
 }}
```

2. **stderr 一行人读结论**（human 模式同样会显示）：
   `✗ 阻断于 build：E_BUILD_VALIDATE（m57 ticks 4020 ≠ 3840）· 已花费 ¥0.0721 · 可 --resume`
3. **`run.log` 全文** + **`events.ndjson`**：完整时间线，不截断。
4. **`metrics.json`**：已花费的成本与调用数**必须记账**（已发生的调用不能退钱，所以要能算清"白花多少"）。

#### 7.1.2 状态一致性（不会出现"半个文件"）

| 规则 | 说明 |
|---|---|
| 原子写 | 所有 JSON/GP5 **先写 `.tmp` 再 `rename`**；进程被杀不会留下半个文件 |
| `ir.json` | 只在 `assemble` **成功后**写入；之前不存在 |
| `measures/` | 每小节一个文件，原子写；已写入的即视为有效缓存 |
| `.gp5` | 只在 `validate → build → verify` **全部通过后**出现；失败时删除临时文件 |
| **审计失败例外** | `.gp5` **保留**（已生成），但 `build.audit.failed=true`、`status=failed`、退出码 2——GUI 应提示"文件已生成但审计未过" |

#### 7.1.3 在途请求怎么处理

阻断时可能还有并发调用在飞（默认 18 路）：

1. **停止派发新任务**；
2. **在途请求允许完成并记账**（已经发出、必然计费；丢弃响应但保留 `calls/`）；
3. 最多等 `run.inflight_grace_ms`（默认 30 s），超时则放弃等待但**仍按上限估算记账**；
4. 记账完成后再发 `run.finished`——**禁止**在记账前退出，否则成本统计不准。

#### 7.1.4 恢复

| 命令 | 行为 |
|---|---|
| `--resume` | 从 `out/<song>/` 的缓存继续；已完成阶段按幂等键（§8.1）直接复用，**不重复计费** |
| `--force <stage>` | 重跑该阶段及其下游（用于改参数后重试） |
| 直接重跑同名命令 | 等价于 `--resume`（幂等键命中即跳过） |

**恢复的典型场景**：

- 预算超限 → 调高 `budget.cny_per_8measures` → `--resume`（已花的钱不重复花）；
- 写出校验失败 → 看 `judgements` 里的报警 → 修 prompt/参数 → `--force fuse` 之后继续；
- 网络中断 → 直接重跑，`calls/` 命中的不重复请求。

#### 7.1.5 明确不做

- **不自动删除**任何中间产物（证据就是资产）；
- **不对阻断性错误自动重试**（只有 V-05/V-06 的**调用级**错误重试）；
- **不写半成品 `.gp5`**；
- **不在阻断后继续花 API 钱**（停止派发；在途只等不新增）。

---

## 8. 状态布局、缓存与幂等

```
out/<song>/
├── input.json          # 输入登记（路径、sha256、class）
├── pageset.json        # 定位层结果
├── skeleton.json
├── staff/rhythm.json   # 读五线谱结果（每小节 MeasureRhythm + summary）
├── crops/              # 实际送出的裁片（证据留存；retain.crops=false 时可关）
├── calls/              # <callId>.req.json / <callId>.resp.json
├── measures/<n>.json   # 每小节读取结果（含 call 引用）
├── ir.json
├── judgements.json
├── metrics.json        # 每阶段指标（§8.2）
├── events.ndjson       # 本次运行完整事件流（与 stdout 同格式，GUI 可回放）
├── run.log             # stderr 全文（GUI 日志面板）
├── build/report.json
└── <song>.gp5
```

| 规则 | 说明 |
|---|---|
| 幂等 | 每个阶段以"上游产物 sha256 + 参数 sha256"为键；命中缓存直接复用 |
| `callId` | `sha256(stage ‖ cropSha256 ‖ promptVersion ‖ schemaVersion ‖ model)` 的前 16 位十六进制；同一输入重跑必须命中同一条 `calls/` 记录 |
| `--force <stage>` | 强制重跑该阶段及其下游 |
| 可回放 | `calls/` 完整保存请求与响应；`--provider stub` 时按顺序重放 |
| 并行 | 系统级并行；同一首歌的 `measures/` 写入必须按小节号原子落盘（先写 `.tmp` 再 rename） |

### 8.1 幂等与重复副作用

- 本项目所有动作都是"生成文件"，没有外部副作用（无支付/无通知），因此幂等只需保证**同一 `callId` 不重复计费**：命中 `calls/` 即复用，不再发请求。
- 重试不得改变 `callId` 的稳定性：重试用 `callId.attemptN` 记录，**主键仍是 `callId`**，取最后一次成功结果。

### 8.2 每阶段指标（`metrics.json`）

**必须**落盘，供评测与排障使用（对应"先观测再优化"）：

| 字段 | 说明 |
|---|---|
| `stage` | `locate / skeleton / staff / read / fuse / adjudicate / assemble / build` |
| `durationMs` / `p95Ms` | 阶段耗时（按系统统计，取 p95） |
| `calls` / `retries` / `emptyReturns` | 调用数、重试数、空返回数 |
| `inputTokens` / `outputTokens` / `cachedTokens` | 来自 `usage` |
| `cny` / `cnyPer8` | 按 `caps.pricing` **谷价**归一化计算，**四位小数**；`cnyPer8 = 该次调用成本 × 8 / 该次调用的小节数`；另记 `cnyActual`（按实际时段计价，供对账参考） |
| `systems` / `measures` / `alarms` / `alarmsResolved` | 规模与报警闭环 |
| `degradations[]` | 每个降级点的原因（如"拆小裁片""接受终裁结果""审计跳过"） |

**禁止**把原始用户图片内容写进 `metrics.json`；只允许哈希与尺寸。

---

## 9. 测试规范

### 9.1 测试四类

| 层 | 内容 | 是否联网 |
|---|---|---|
| **架构** | `tests/test_layers.py`：用 `ast` 静态扫描 import，强制 LAY-01..08；厂商字面量泄漏检查 | 否 |
| 单元 | 几何函数、时值换算、身份校验、schema 校验 | 否 |
| 契约 | 裁切规则（RD-01..10）、prompt 字段完整性、GP5 validate/build/verify、`MeasureTask→MeasureResult` 接缝 | 否（`--provider stub`） |
| 端到端 | 4 首 class 3 真谱 → `.gp5` → 审计 | 是（记录 fixture 后可离线重放） |

**`test_layers.py` 是四层拆分能否维持的唯一机械保证**：靠人 review 迟早会破；让它 CI 红一次就够了。

### 9.2 语料门（`eval/score.py`）

- 指标：`rest_pattern / string_fret / pitch_exact / bars_add_up / system_recall / json_valid / alarm_resolved / structure_change_recall`
  - `structure_change_recall`：真值里有中途换拍/换调时，被正确检测到的比例（分母 = 真值中的变化点个数；语料用带换拍的曲子，如 `Don't Cry`）
- 阈值在 `configs/thresholds.toml` 先声明
- `--selftest` 通过后才允许计分
- 按输入档分档报分，**禁止**用"支持图片"一句话覆盖
- 五线谱读的分组交叉表门（`二分 → 四分` 必须为零）与 abstain 原因分布见 `docs/spec-staff.md` §13
- **真值必须现导并校验**：`tools/dump.mjs` 导出的 JSON 要带每小节拍号；`load_truth` 校验每小节时值之和等于拍号，不通过即 `EvalError`。旧产物 `out/p1/*/truth.json` 已确认不可信（每小节多出三个四分休止），不复用

### 9.3 语料

| 来源 | 用途 |
|---|---|
| `老人与海`、`打上花火`（冻结真值 `truth.gp`） | 带分母打分 |
| `NIGHT DANCER`、`Клетка` | 回归对照 |
| DadaGP 渲染 + 加噪 | class 1/5/6 合成语料 |

### 9.4 fixture 录制与回放

目的：让"不可复现的模型输出"在测试里变成**可复现的输入**。

| 规则 | 说明 |
|---|---|
| F-01 | 任何一次真实调用，`calls/<callId>.{req,resp}.json` 即可作为 fixture，无需另存格式 |
| F-02 | `fixtures/<provider>/<case>/` 收录"有代表性的"调用（≥20 条）：正常、空返回、schema 错、多小节、拆分裁片 |
| F-03 | fixture **禁止**含 API key；请求里的 base64 图片可替换为 `sha256` 占位，但必须保留尺寸与像素统计 |
| F-04 | CI 默认 `--provider stub`；只有 nightly 或手动触发才跑真实 API |
| F-05 | fixture 与当前 `promptVersion` 不一致时，回放**必须** WARN 并标记 `stale`，不得静默通过 |

---

## 10. 控制台输出契约（GUI 的 API）

### 10.1 为什么先定这个

当前只做**控制台版本**，之后要写 GUI。所以 CLI 的输出不是"给人看的日志"，而是 **GUI 的接口**：GUI 只做 `spawn → 逐行解析 → 渲染`，不重复实现任何业务逻辑。**先把这条契约钉死，GUI 才可能是一个薄壳。**

### 10.2 两条流（硬规则）

| 流 | `--format ndjson`（GUI / 管道） | `--format human`（人） |
|---|---|---|
| **stdout** | **只有 NDJSON**，一行一个 JSON 对象，**永不打印自由文本、永不打印进度条** | 人读的阶段摘要（见 §10.6） |
| **stderr** | 人读日志 `<level> <stage> <message>`，默认 WARN 以上；`-v` 加 INFO，`-vv` 加 DEBUG | 同左 |
| **文件** | `out/<song>/run.log`：stderr 全文 + 事件时间线（GUI 的"日志"面板直接读它） | 同左 |

- `--format auto`（默认）：stdout 是 TTY → `human`；否则 → `ndjson`。
- `--color auto|always|never`；**非 TTY 禁止输出 ANSI 色码**。
- stdout **必须行缓冲**（每行 `flush`），否则 GUI 的进度会滞后。
- `--quiet`：stderr 只保留 ERROR。

### 10.3 事件通用结构

```jsonc
{"v":1,"seq":17,"ts":"2026-10-18T00:12:03.412Z","level":"info","stage":"read",
 "event":"call.finished","data":{"callId":"a1b2c3d4e5f60718","ok":true,"durationMs":2841,
 "tokens":{"in":1104,"out":812,"cached":0},"cny":0.0047,"cnyPer8":0.0063,"retries":0}}
```

| 字段 | 规则 |
|---|---|
| `v` | 事件 schema 版本；破坏性变更必须升 |
| `seq` | 从 1 单调递增，用于丢行检测与排序 |
| `stage` | ∈ `ingest / locate / skeleton / staff / read / verify / adjudicate / assemble / build / audit / eval / run` |
| `level` | ∈ `debug / info / warn / error` |
| `event` | 点分命名 `域.动作`；**GUI 遇到未知事件名必须忽略，不得崩溃** |
| `data` | 事件专属字段；遵循"小、平、可增量渲染" |

### 10.4 事件清单（"控制台上会出现什么"）

**run 级**

| event | 何时 | `data` 关键字段 |
|---|---|---|
| `run.started` | 启动 | `input`、`class`、`song`、`outDir`、`provider`、`configSha` |
| `run.finished` | 任何结束（含阻断） | `status`（ok/failed/aborted）、`exitCode`、`gp5`、`seconds`、`cny`、`artifacts[]`；失败时另有 `block{stage,error,reason,location,suggestions[]}`、`spentCny`、`spentCnyPer8`、`resumable`（见 §7.1.1） |
| `run.aborted` | 收到 SIGINT/SIGTERM | `signal`、`stage`、`partialArtifacts[]` |

**ingest 级**

| event | 何时 | `data` |
|---|---|---|
| `input.registered` | 每个输入文件 | `file`、`sha256`、`width`、`height`、`mp` |
| `input.rejected` | 不可用 | `file`、`error`、`reason` |

**locate 级**

| event | 何时 | `data` |
|---|---|---|
| `locate.page` | 每页 | `file`、`systems`、`deg` |
| `locate.system` | 每个系统 | `system`、`page`、`measures`、`y0/y1`、`tabLines[]`、`deg`、`warn?` |
| `locate.done` | 阶段结束 | `systems`、`measures`、`durationMs` |

**skeleton 级**

| event | 何时 | `data` |
|---|---|---|
| `skeleton.done` | 一次调用后 | `title`、`artist`、`tempo`、`tuning[]`、`stringCount`、`timeSignature`、`measureCount`、`defaulted[]` |

**staff 级（读五线谱，不联网）**

| event | 何时 | `data` |
|---|---|---|
| `staff.measure` | 每小节读完 | `index`、`status`（ok/partial/unknown）、`beats`（`duration`/`dots`/`rest`/`heads` 摘要）、`abstains[]`（AR 编号 + 拍号） |
| `staff.done` | 阶段结束 | `measures`、`ok`、`partial`、`unknown`、`abstainByReason{AR-xx}`、`durationMs` |

**read 级（每次模型调用都有）**

| event | 何时 | `data` |
|---|---|---|
| `read.dispatch` | 派单前 | `systems`、`batches`、`maxConcurrency` |
| `read.call.started` | 每次调用前 | `callId`、`system`、`measures[]`、`crop[l,t,r,b]`、`mpx`、`estTokens` |
| `read.call.finished` | 每次调用后 | `callId`、`ok`、`durationMs`、`tokens{in,out,cached}`、`cny`、`cnyPer8`、`retries`、`schemaValid` |
| `read.call.failed` | 重试/放弃 | `callId`、`error`（错误码）、`attempt`、`willRetry`、`willSplit` |
| `read.done` | 阶段结束 | `systems`、`measures`、`calls`、`emptyReturns`、`cny`、`durationMs` |

**verify / adjudicate 级**

| event | 何时 | `data` |
|---|---|---|
| `alarm.raised` | 每条报警 | `alarmId`、`rule`（A1…A10）、`measure`、`claimed`、`expected`、`crop` |
| `reread.started` / `reread.finished` | 报警复读 | `alarmId`、`callId`、`changed` |
| `adjudicate.call` / `adjudicate.done` | 终裁 | `alarmId`、`final`、`reason`、`overrode`（`read`/`locate`/`null`）、`callId` |
| `verify.done` | 阶段结束 | `alarms`、`byRule{}`、`durationMs` |

**assemble / build / audit 级**

| event | 何时 | `data` |
|---|---|---|
| `assemble.done` | 装配后 | `measures`、`repeats`、`multiRestExpanded`、`droppedTechniques`、`durationMs` |
| `build.validate` | 写出前 | `ok`、`errors[]` |
| `build.written` | 写出后 | `path`、`bytes`、`roundtrip`（OK/FAIL） |
| `build.failed` | 失败 | `error`、`detail` |
| `audit.result` | 审计后 | `pitchMismatch`、`barErrors`、`skipped?` |

**通用**

| event | 何时 | `data` |
|---|---|---|
| `progress` | 阶段内节流上报 | `stage`、`done`、`total`、`unit`（systems/measures/calls） |
| `metrics.summary` | 结束前 | `systems`、`measures`、`calls`、`retries`、`emptyReturns`、`cny`、`cnyPer8`、`seconds`、`alarms`、`alarmsResolved`、`degradations[]` |

**eval 命令专用**

| event | 何时 | `data` |
|---|---|---|
| `eval.selftest` | 计分前 | `verified`、`failures[]` |
| `eval.metric` | 每个指标 | `name`、`value`、`denominator`、`threshold`、`pass` |
| `eval.verdict` | 结束 | `pass`、`failedMetrics[]` |

### 10.5 progress 节流

`progress` 事件默认 **≤5 次/秒**（`--progress-interval 200ms`）；GUI 用它画进度条，不要用 `read.call.*` 自己算进度（乱序与重试会算错）。

### 10.6 human 模式长什么样

```
$ aiaomr run --input 打上花火/1.png --class 3 --song 打上花火 --format human
locate      ▸ 18 systems, 107 measures                        1.2s
skeleton    ▸ B major, 4/4, ♩=96, 4-string EADG               3.1s
read        ▸ 18/18 systems, 21 calls, 0 empty returns        11.4s
verify      ▸ 9 alarms (A1×4, A8×3, A9×2)
adjudicate  ▸ 9/9 resolved  (overrode read 3, locate 1)        4.8s
build       ▸ ROUND-TRIP OK · audit 0/0
✓ out/打上花火/打上花火.gp5
  cost ¥0.1120 (off-peak; ¥0.0087 per 8 measures) · 14.2 s
```

human 模式下**只**打印这些阶段摘要行与最终块；明细进 `run.log`。

**阻断时长这样**（同一套行的最后一行换成失败块）：

```
$ aiaomr run --input … --class 3 --song 打上花火 --format human
locate      ▸ 18 systems, 107 measures                        1.2s
skeleton    ▸ B major, 4/4, ♩=96, 4-string EADG               3.1s
read        ▸ 18/18 systems, 21 calls, 0 empty returns        11.4s
verify      ▸ 9 alarms (A1×4, A8×3, A9×2)
adjudicate  ▸ 7/9 resolved                                    3.9s
build       ▸ ✗ E_BUILD_VALIDATE  m57 ticks 4020 ≠ 3840
✗ 阻断于 build · 已花费 ¥0.0721 · 产物保留在 out/打上花火/ · 可 --resume
  hints: 重读 m56-58；检查 m57 是否漏读休止
```

### 10.7 退出码与中断

| 退出码 | 含义 |
|---|---|
| 0 | 成功（`.gp5` 已写出且审计通过） |
| 1 | 输入不可用 / 阶段级失败（见 §3.3、§7） |
| 2 | 工具故障（模型调用、写出、审计） |
| 3 | 成本超限（`E_BUDGET_EXCEEDED`） |
| 130 | 被 SIGINT 中断 |

中断时**必须**先打印 `run.finished`（`status=aborted`）或 `run.aborted`，已写出的产物保留（GUI 可提示"部分完成"）。

**所有非零退出码的共同约定**（细节见 §7.1）：

- 产物**保留**、**原子写**（不会读到半个文件）；
- `run.finished.data.block` 必填，含 `stage` / `error` / `reason` / `location` / `suggestions[]`；
- `spentCny` / `spentCnyPer8` 必填（已发生的调用不退钱，要能算清）；
- `resumable: true`，修复后 `--resume` 不重复计费。

### 10.8 对 GUI 的稳定性承诺

1. 事件名、字段名、退出码是**兼容性契约**；破坏性变更必须升 `v`。
2. `run.finished.data.artifacts[]` 列出全部产物路径，GUI 不需要自己拼路径。
3. GUI **禁止**解析 stderr 判断状态；stderr 只用于日志面板。
4. 取消 = 发 SIGINT，然后等 `run.aborted` 或进程退出再回收。
5. 同一首歌重跑时，事件流应**逐行相同**（除 `ts`/`durationMs`/`cny` 外）；不一致即为回归。

### 10.9 明确不打印的东西

- API key、完整 prompt、完整模型响应（只落 `calls/`；`-vv` 也只打截断摘要 ≤500 字符）；
- 用户图片的原始内容（只打 sha256 与尺寸）；
- 真值内容（eval 只打指标与分母，**永不**打 `truth.gp` 里的音符）。

---

## 11. 验收命令

```bash
# 端到端 —— 人读模式（控制台版默认 TTY 下）
python -m aiaomr.cli run --input "corpus/打上花火/1.png" --class 3 --song 打上花火
#   → out/打上花火/打上花火.gp5
#   → 阶段摘要 + 最终块（§10.6）

# 端到端 —— 事件流模式（GUI / 管道）
python -m aiaomr.cli run --input … --class 3 --song 打上花火 --format ndjson > out/打上花火/events.ndjson
#   → 每行一个 JSON；最后一行 run.finished
#   → `jq -e 'select(.event=="run.finished") | .data.exitCode == 0'`

# 事件流完整性
#   每行都必须是合法 JSON；seq 从 1 连续；run.started 与 run.finished 各恰好一次
python -c "import json,sys;[json.loads(l) for l in sys.stdin]" < out/打上花火/events.ndjson && echo EVENTS OK

# 显式指定 provider（将来多模型时用）
python -m aiaomr.cli run --input … --class 3 --provider deepseek_flash

# 审计
node tools/audit.mjs out/打上花火/打上花火.gp5
#   → {"pitchMismatch":0,"barErrors":0}

# 打分
python -m aiaomr.cli eval --ir out/打上花火/ir.json --gp corpus/打上花火/truth.gp --max-measures 61
#   → 先 eval.selftest verified=true，再逐条 eval.metric（带分母），最后 eval.verdict

# 离线回放（不联网）
python -m aiaomr.cli run --input … --class 3 --provider stub

# 多 provider 对照（新增 provider 时）
python -m aiaomr.cli eval --provider deepseek_flash --report out/eval/deepseek.json
```

**通过标准**：

- 审计全 0；
- `eval` 各指标不低于 `configs/thresholds.toml` 声明值；
- **事件流合法**：NDJSON 可逐行解析、`seq` 连续、`run.finished` 唯一；
- **重跑一致性**：同一输入重跑，事件流除 `ts`/`durationMs`/`cny` 外逐行相同（§10.8 第 5 条）。

---

## 12. 性能与成本预算

| 项 | 预算 | 超出即 |
|---|---|---|
| 调用次数/首 | ≤ 24 | 报告 WARN（不阻断） |
| 墙钟/首（107 小节） | ≤ 20 s | 报告 WARN |
| 成本 | **每 8 小节 ≤ ¥0.0150**（硬上限，**谷价**口径）。P0 实测（thinking 关、1.6 MP 裁片）：一次调用约 ¥0.0035，折合每 8 小节约 ¥0.004；thinking 开在整系统读数上会失控（16k reasoning token 仍无输出），当前默认关 | 单次调用超限或累计超派生上限即 `E_BUDGET_EXCEEDED` |
| 峰值内存 | ≤ 1.5 GB | 报告 WARN |

---

## 13. 版本与变更

| 版本项 | 规则 |
|---|---|
| IR `version` | 结构性变更必须升次版本；`3.0` 起 |
| `schemaVersion` | 跟随 `kernel/ir.py` 的 Pydantic 模型；任一字段变更即升 |
| prompt `version` | 任何语义改动必须升版本；每次调用落盘 |
| provider | 新增 provider **不**升 IR 版本（IR 与厂商无关），但必须升 `promptVersion` 并重跑语料门（V-14） |
| 阈值 | 只能通过提交修改，且提交信息必须写"为什么这次改阈值不算作弊" |
| 模型 | 更换模型必须重跑语料门并在报告里附对比 |

### 13.1 已定与待定

**已定（本规范确立）**

- **四层依赖模型**（§2.0）：L1 `providers` → L2 `measure` → L3 `score` → L4 `writers`，共享 `kernel`；三条数据接缝 S-IF1/2/3；LAY-01..08 由 `tests/test_layers.py` 机械强制；
- provider 抽象层：`providers/base.py` + `caps.py` + `registry.py`，`deepseek_flash` 为唯一实现；
- 四道闸（输出校验的 G1–G4）与 schema-as-code；
- 调用留证（`calls/` + `crops/` + `metrics.json`）；
- prompt 归属各层、稳定前缀以命中 cache；
- **控制台输出契约**（§10）：stdout = NDJSON 事件流、stderr = 日志、`events.ndjson` / `run.log` 落盘；**GUI 只做 spawn + 解析**，不重写逻辑。

### 13.2 GUI 演进（先控制台，后 GUI）

| 阶段 | 形态 | 约束 |
|---|---|---|
| **当前** | 纯控制台 CLI | 输出契约按 §10 定死 |
| 后续 | GUI 薄壳（Electron / Tauri / Web 均可） | 只消费 §10 事件流；**禁止**在 GUI 里实现裁切、验算、装配、写出 |
| 再后续 | 多 provider / 批处理 / 队列 | 复用同一 CLI 与事件契约 |

**判据**：如果一个功能在 GUI 里实现而不是在 CLI 里，它就不算完成——因为控制台版本无法回归它。

**待定**：见 §14 的待审核项；P0 用实测数据回填。

---

## 14. 待审核项（Spec 层的开放点）

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| 1 | `crop.max_measures_per_call = 8`、`target_mp 0.9–1.6` | **已确认（用户 2026-10-17）** | 初值保留，P0 只用于标定，不改变结构 |
| 2 | `read.min_deg_eff = 12` | **已确认（用户 2026-10-18）** | **含义**：裁片被 provider 压缩后的**有效谱线间距**（像素）。`deg_eff = deg × sqrt(1.69MP / P)`；低于该值记录 WARN（不阻断）。12 是保守初值，P0 用 deg 8/10/12/14 各读一次来标定 |
| 3 | `budget.cny_per_8measures = 0.0150` | **已确认（用户 2026-10-18）** | **单位 = 人民币元 / 每 8 小节 / 谷价口径**，四位小数；它是预算闸不是账单。峰价按 2× 折算，闸门一律用谷价归一化，避免"同样的活跑在峰时被判超支" |
| 4 | 技巧枚举 | **已扩为四组（§3.4）** | A 音符级 20 项 / B 拍级 3 项（含互斥规则）/ C 音符类型 1 项 / D 只记录不映射 8 项 |
| 5 | 只支持单声部 | **已确认（用户 2026-10-17）** | 双音/和弦记为同 beat 多 note，仍单声部；>2 声部只保留主声部并记录 |
| 6 | **总小节数** | **已删除（用户 2026-10-18）** | 不读；`measureCount = len(measures)`；相关检查取消（S-06） |
| 7 | **中途换拍号 / 换调号** | **已支持（用户 2026-10-18）** | 拍号/调号改为事件列表；A11/A12 聚类检测兜底（§2.2.3） |
| 8 | **骨架分级** | **已改（用户 2026-10-18）** | P0 拍号+调弦/弦数、P1 调号、P2 速度、P3 曲名/作者；**任何一项读不出都不失败**，按表兜底并记 `skeletonProvenance` |
