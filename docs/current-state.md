# AIAOMR 现状（人工审核用）

> 基线：决定废弃几何读谱层之后的 commit（2026-10-19）。这份文档的目的是**让人审**，
> 不是汇报成绩；能力、缺口、已知问题和没验证的东西都列出来。数字都可以用文末命令复现。
>
> **2026-10-19 更新（重要）**：几何读谱层（`score/staff/`，13 个文件约 1776 行）已整体废弃，
> 代码与规范移入 `legacy/geometry/`，CLI 的 `staff` 阶段、`MeasureRhythm` 等契约与 40 个
> `staff.*` 参数一并移除。原因与复活方法见 [`legacy/README.md`](../legacy/README.md)。
> 下面凡是提到“读五线谱/几何时值”的段落都已按此更新；仍保留的几何只有定位层。

## 1. 一句话与边界

把电脑导出的贝斯谱图片（五线谱 + 4/5 弦 TAB）认成 Guitar Pro 5 文件（`.gp5`）。
当前只做第 3 类输入（清晰导出图/截图），不做手机照片、视频、长条谱；不引入 GPU、不引入
homr/oemer/Audiveris、不引入 litellm 之类中间层；模型只用 DeepSeek V4.1-Flash。

核心分工（多轮讨论后定的）：

- **几何**：只保留定位（系统、小节网格、TAB 带、裁片坐标）；符号识别层的尝试已废弃，见 `legacy/`；
- **骨架层**：谱号/调号/拍号/调弦/速度/曲名这些全局事实，**先读好**，绝不进读小节的窗口；
- **模型**：读小节的弦号、品位、时值（当前 P1 路径），未来做争议小节的复读与终裁；
- **程序**：音高由调弦+品数算，不变量验算，报警不阻断。

## 2. 现在能跑什么、不能跑什么

| 能力 | 状态 | 证据 |
|---|---|---|
| 图片登记、定位（系统/小节网格） | 能 | `locate` 阶段；打上花火 4 页 15 个系统 79 小节 |
| 骨架读取（拍号/调号/调弦/速度/曲名） | 能（模型） | `skeleton` 阶段；打上花火调号读成 B major |
| 读小节（模型，含弦号/品位/时值） | 能 | P1 四首跑通，代价约 ¥0.08–0.13/首 |
| 验算（A1–A5、A4b） | 能 | `verify` 阶段，报警不阻断 |
| 装配 + 写 `.gp5` + 往返核对 | 能（结构上） | P1 四首都能写出文件，但都因小节和报警被阻断 |
| 读五线谱（几何） | **已废弃**：真页面只做到 2/7 逐拍正确，代码移入 `legacy/geometry/` | `legacy/README.md` |
| 复读、终裁、A6–A12、缓存/预算并发、语料门 | **未做** | 见 P2 计划 |

## 3. 端到端流程与产物

八个阶段（`--until` 可停在任意一个）：`input → locate → skeleton → read → verify → assemble → write → audit`。

| 阶段 | 输入 | 产物（`out/<song>/`） | 联网 |
|---|---|---|---|
| input | 图片路径/目录 | `input.json` | 否 |
| locate | 图片 | `pageset.json` | 否 |
| skeleton | 首页头部裁片 + 调号窄图 | `skeleton.json` | 是 |
| read | 系统裁片 | `measures/*.json`、`calls/*.json` | 是 |
| verify | 小节读数 + 骨架 | `judgements.json` | 否 |
| assemble | 读数 + 骨架 + 报警 | `ir.json`（内存，完整跑到 audit 才落盘） | 否 |
| write | IR | `<song>.gp5` | 否 |
| audit | `.gp5` | 事件 `audit.result` + `build/report.json` | 否（走 alphaTab） |

控制台契约：stdout 只放 NDJSON 事件，stderr 放日志；`run.finished` 恰好一次；退出码 0/1/2/3/130。
主要事件见 `docs/spec-v3.md` §10.4。

## 4. 代码结构

依赖四层：`kernel`（纯数据）← `providers`(L1) ← `measure`(L2) ← `score`(L3) ← `writers`(L4)，`eval`/`cli` 在最上面；
由 `tests/test_layers.py` 用 AST 扫描强制（LAY-01..08；LAY-09 随 `score/staff/` 一并移除）。

| 包 | 行数 | 职责 |
|---|---|---|
| `kernel/` | 约 950 | IR、契约、错误码、配置 |
| `providers/` | 422 | DeepSeek 接入（唯一发 HTTP 的目录）、stub 回放 |
| `measure/` | 478 | 裁片规划（1.6 MP）、小节 schema、单次调用 |
| `score/locate/` | 394 | 纯 CV：系统、小节网格、谱线行 run、调号窄图 |
| `score/skeleton/` | 305 | 骨架读取（分级、兜底） |
| `score/verify/` | 187 | 不变量 A1–A5、A4b |
| `score/assemble/` | 103 | 多小节休止展开、小节号链、IR 组装 |
| `writers/` | 389 | GP5 validate/build/往返核对、alphaTab 审计 |
| `eval/` | 208 | 打分器与真值校验 |
| `cli.py` + `events.py` + `__main__.py` | 1074 | 编排、事件流、人读渲染 |

读五线谱层（原 `src/aiaomr/score/staff/`，13 个文件约 1776 行）已移入 `legacy/geometry/`，不再在源码树里；
它的文件清单与职责见 `legacy/geometry/spec-staff.md` §12。

## 5. 规范与文档地图

| 文档 | 定位 | 状态 |
|---|---|---|
| `AGENTS.md` | 仓库规矩（红线、分层、写作用域、测试要求） | 有效 |
| `docs/spec-v3.md` | **规范，唯一权威**：接口、错误码、参数表、事件、失败语义 | 与代码同步；staff 相关章节已摘除 |
| `legacy/geometry/spec-staff.md`（429 行） | **已废弃**的读五线谱配套规范，随代码一起存档 | 只作历史参考 |
| `docs/plan-v3.md`（557 行） | 方案与取舍（为什么这么设计、放弃了什么） | 有效 |
| `docs/superpowers/plans/` | 三个计划：控制台版（P0+P1，任务 0–15）、P2（11 任务）、读谱小计划（6 任务） | 勾选框状态过期，进度看 git log |
| `docs/p0-results.md` | P0 实测：1.6 MP、thinking 关、单系统整图 | 已冻结 |
| `docs/p1-report.md` | P1 验收：0/4 通过、卡在哪、成本 | 已冻结 |
| `docs/plan-measure-score.md` | **设计稿**：小节打分 → 直接通过/AI 复审/判错 三档 | 未实现 |
| `README.md` | 给使用者的入口文档 | 已按废弃决定更新 |

## 6. 关键设计决策（审核重点）

| 决策 | 理由 | 代价 |
|---|---|---|
| 几何定坐标、模型定符号、TAB 定音、记谱定时、程序验算、模型终裁 | 分工清晰，各自可测 | 几何需要全部符号判据，目前是瓶颈 |
| 谱号/调号/拍号由骨架层先读、**绝不进读小节窗口** | 全局事实与局部内容分离 | 第一个小节的窗口要按 `headerX1` 截断 |
| 三条铁律：不用横向间距推时值/onset；拍格只作否决；判不准就 abstain | 防“猜” | 真页面大量 abstain |
| 报警不阻断；低分小节标 unknown 继续跑完、报告统一列出 | 不让一个小节毁掉整首（已定，2026-10-19） | 报告会变长，需按分数排序 |
| 像素阈值全部以 deg 为单位、进参数表 | 换分辨率不崩 | 参数已 40 个，开始难维护 |
| 真值以“谱面那份”为准：`打上花火` 用 GPX 重转的 `.gp5` | 同目录那份 `.gp5` 是另一份转写，107 小节有 10 小节不同 | 旧 `out/p1/*/truth.json` 已过期 |
| 写法：先写失败测试、按规范编号实现、一处判据一个文件 | 可回溯 | 单元测试多，真页面门缺失 |

## 7. 参数与阈值

参数分三组：`crop`/`read`/`locate`/`budget`/`skeleton`/`structure`/`emit`/`adjudicate`/`retain`/`run`
（`configs/default.toml`）。原来 `[staff]` 的 40 个几何阈值已随读谱层一起删除；这部分设计与
“参数卫生”的教训留在 `legacy/` 供参考。

## 8. 测试现状

- `pytest -q`：**140 通过、2 跳过**（跳过的是需要 `ALPHATAB_PATH` 的审计用例；废弃几何层后从 257 条降到 140 条）。
- 覆盖：kernel 契约/配置、providers 客户端、measure schema、locate 系统/小节、GP5 写出与往返、
  eval 校验、CLI 端到端（stub 回放）。几何读谱层的测试随之移入 `legacy/geometry/tests/`，不再参与全量测试。
- **缺口**：没有真页面 golden 测试。m17/m21 逐拍正确是手跑脚本验证的，改动后没有自动回归门；
  真页面只验证了打上花火第 1 页第 1 系统，其他系统/歌没测。

## 9. 真页面实测（几何层废弃前的最后一次实测，对照 GPX 真值，留存作证据）

| 小节 | 真值 | 几何结果 | 结论 |
|---|---|---|---|
| m16（整小节休止） | 全休止 | 7 个假音符 | 休止条覆盖不到阈值，未识别 |
| m17 | half, eighth, dotted-quarter | half, eighth, dotted-quarter | **正确（ok）** |
| m18 | half, eighth, dotted-quarter | half, **16th**, dotted-quarter | 横梁多算一层；一根 166.5 的假符干 |
| m19 | half, 4×eighth | half, **5×eighth** | 多一个拍 |
| m20 | quarter, eighth, eighth, quarter | 4 个十六分 | 横梁层数与附点误判 |
| m21 | half, eighth, dotted-quarter | half, eighth, dotted-quarter | **正确（ok）** |
| m22 | half, eighth, dotted-quarter | half, **16th**, dotted-quarter | 同 m18 |

即 **2/7 逐拍正确、全部 `ok` 的小节只有这 2 个**；其余 5 个 abstain（AR-03/AR-04/AR-05）。

## 9.1 NIGHT DANCER 的 TAB 实测（2026-10-19，80 次真实调用）

- 覆盖：4 页共 81 个显示小节，对齐到真值 102 个小节（差额是多小节休止条展开），
  非空小节逐小节比对 72 个；5 个显示小节整小节读不出（`unreadable`）。
- **只比品数（不管弦号）：66/72 = 91.7% 的小节完全一致。**
- **弦号 + 品数一起看：26/72 = 36.1% 完全一致。**
- 典型错法（第 1 页第 1 系统第 2 小节）：谱面品数是 8/6/6/5/5/3，真值弦号是
  (4,8)(2,6)(2,6)(2,5)(2,5)(1,3)，模型读成 (2,8)(1,6)(2,6)(2,5)(2,5)(3,3)——
  **品数全对，弦号错位**。另外 5 个多小节休止条没有报 `multiRest`，对齐时要靠序列对齐兜底。
- 结论：现在不能保证"所有小节几弦几品全对"。下一步应把弦号从"模型猜"改成"程序定"：
  让模型报每个品数数字的纵向位置，程序按 TAB 弦线坐标把位置映射成弦号（这属于定位层的
  最小几何，不是被废弃的符号识别）。
- 回归测试：`tests/corpus/test_night_dancer_tab.py`（品数门 90%，弦+品目标 100% 记为 xfail）
  与 `tests/tools/test_compare_tab.py`（对齐算法单测）。

## 10. 已知问题清单

**P0（会直接决定成败）**

1. **几何读谱层已废弃**（2026-10-19 执行）：一层 40 个参数、一批绝对像素偏移、补丁式过滤，
   真页面只做到 2/7；代码与规范已移入 `legacy/geometry/`，CLI/契约/参数表已摘除。
   替代路线回到“模型读时值、程序验算、几何只定位”。
2. **时值主路径回到模型之后，精度上限由模型决定**：P1 的 A1 报警（时值和）仍然存在，
   复读/终裁与 A6–A12 尚未实现；这是 P2 的主要缺口。
3. **无真页面 golden 门**：现状无法自动防止回归。
4. **定位层遗留**：播放光标竖线被当小节线、page1 第 4 系统漏检、跨页重叠（backlog）。

**P1（流程层的遗留）**

5. 定位层三处：播放光标竖线被当小节线、page1 第 4 系统漏检、跨页重叠（backlog 任务已登记）。
6. m16 这类整小节休止的识别：`rest_bar` 覆盖率阈值在真页面不够。
7. 旧产物 `out/p1/*/truth.json` 已过期（打上花火用了错误的转写），需要按新口径重导后再谈指标。
8. P2 计划剩余：复读/终裁、A6–A12、并发与预算、prompt 版本化缓存、语料门、prompt 注册表。

**P2（文档与一致性）**

9. 计划文件里的勾选框与 README 的进度表都落后于代码；本文档为当前口径。
10. `legacy/geometry/spec-staff.md` 是废弃版规范，不要再当权威读。

## 11. 钱与性能

- P0 实测：13 次调用 ¥0.0324（thinking 开多一次 ¥0.0642）；结论是 thinking 关、裁片统一 1.6 MP、单系统整图。
- P1：四首共约 ¥0.42；单次调用 ¥0.0025–0.0035；预算口径 **人民币每 8 小节，谷价，四位小数，默认 0.0150**。

## 12. 怎么跑

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m aiaomr run --input "E:/Bass Guitar/AIAOMR/打上花火/1.png" \
    --until locate --format ndjson
.venv/Scripts/python.exe tools/truth_to_gp5.py --truth out/tmp/x.json --out corpus/truth/x.gp5
# 真值导出（需要 alphaTab）：
ALPHATAB_PATH="E:/Bass Guitar/AIAOMR/tools/gpverify/node_modules/@coderline/alphatab/dist/alphaTab.core.mjs" \
  node tools/dump.mjs corpus/truth/打上花火.gp5 > out/tmp/daoko.json
```

## 13. 建议的审核顺序

1. [`legacy/README.md`](legacy/README.md)——废弃几何层的证据与复活步骤，确认这个决定是否认可；
2. `docs/spec-v3.md` 与代码是否还对得上（本次已同步摘除 staff 阶段、契约、参数、事件）；
3. `docs/plan-measure-score.md`——打分与三档分流的口径是否认可（这是“模型读、分数挑争议”的配套）；
4. 本文 §10 的问题清单——决定下一步是补模型侧的复读/终裁，还是先修定位层；

## 14. 需要你决定的三个点

1. ~~几何是否继续全符号主读~~ **已决定：不做**，几何只保留定位层；剩余决策是模型侧怎么补（复读/终裁）以及要不要用 TAB 数字做独立对账。
2. **真页面门的范围**：只要求打上花火第一页，还是四首各取一页？后者需要先修定位层的三处遗留。
3. **下一步优先级**：先补定位层三处遗留（影响裁片质量），还是先做 P2 的复读/终裁（影响读数质量）？

## 15. 我没验证过的、可能有错的地方

- 真页面只看了打上花火 page1 第一系统；“2/7”不是全曲线指标，只是这一块的实测。
- 参数没有在负样本上校准过；“28/28 样本全对”只说明正样本能过，precision 未知。
- fixtures 混了两种分辨率（打上花火截图 deg≈17、NIGHT DANCER 大图 deg≈35.5），跨分辨率行为只做过定性检查。
- 旧项目的对比结论（旧 AIAOMR 几何节奏、AllegScore 用 homr）来自读代码与旧文档，没有端到端复跑。
- 计划文件里的历史勾选与本文档的数字若冲突，以本文档和 `git log` 为准。
