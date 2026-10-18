# AIAOMR v3 控制台版实施计划（P0 与 P1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## 这份计划要做什么

写一个命令行程序，名字叫 `aiaomr`。它的工作很简单：你给它一张贝斯谱的图片，它认谱，然后把结果写成一个 Guitar Pro 5 文件（`.gp5`），你可以直接用 Guitar Pro 打开来弹。

这一轮只处理一类图片：用电脑导出的、清晰的谱子图，也就是方案里说的第 3 类输入。手机上拍的照片、视频截图，都留到后面的计划里做。

程序要能在终端里从头跑到尾，中途断了可以接着跑，而且每一刻在干什么都能被另一个程序读出来——因为后面要给它配图形界面，界面只需要读取这些消息，不该再重写一遍业务逻辑。

## 为什么这样分

程序从下往上分成四层：模型接入、读谱小节、读谱框架、输出格式。另外有一层共用的数据结构，四层都可以用。

这样分只为一件事：以后想换一个视觉模型，只需要改最下面那层，上面三层一行都不用动。

认谱这件事，只交给 DeepSeek 一个模型做。程序自己不做任何"认"的判断，只做两类工作：一是算坐标（比如谱线在哪里、小节从哪里开始），二是事后检查结果自不自洽（比如一小节加起来是不是刚好四拍、音高和"弦号加品数"对不对得上）。算坐标是确定的，交给人肉眼反而更慢；检查对错是机械的，不该再花钱问模型。

## 技术栈

用 Python 3.10 以上。图像处理用 numpy 和 OpenCV，裁图用 Pillow，写 gp5 用 PyGuitarPro（已经下载好放在项目里），调模型用 requests，数据结构用 pydantic 定义，测试用 pytest。另外装一个 Node 环境，只为了跑 alphaTab 做独立校验——alphaTab 是第三方的谱面库，不读我们自己的代码，用它的结论来对照我们的结果。

不用 GPU，不引入任何 AGPL 授权的依赖。

## 依据

设计细节全部写在 `docs/spec-v3.md` 里。这份计划负责把它拆成能一步步做的活。如果计划和规格有出入，以规格为准。

## 本计划不做的事

只做 P0 和 P1 两段。P0 是一次小规模实测，用来定几个参数；P1 是把第 3 类图片从头到尾跑通。

报警后的自动复读、多个系统的并发、评测语料库，留到 P2。视频截图（第 5、6 类）留到 P3、P4。手机照片（第 1 类）留到 P5。图形界面留到 P6。这些各自会另写一份计划。

---

## 必须遵守的硬约束

下面这些是从规格里抄过来的，每一条都适用于所有任务。

1. 用 Python 3.10 以上，不碰 GPU。允许的第三方库只有 pillow、numpy、opencv-python-headless、requests、pydantic、PyGuitarPro 和 pytest。
2. 不允许引入 homr、oemer、Audiveris，也不允许引入 litellm 这类"假装所有模型接口都长一样"的中间层。
3. 只接一个模型：DeepSeek V4.1-Flash，调用时模型名写 `deepseek-flash`，图片清晰度参数固定传 `original`。图片只能放在 user 消息里，不能放进 system 消息。
4. 每次请求都要开 JSON 模式，提示词里必须出现 `json` 这个词并且给一个输出示例。一次请求最多 14 张图，单张图不超过 32 MiB。
5. 裁片统一缩放到 1.6 百万像素：比它小的上采样，比它大的按小节边界拆开；长边上限 4096 像素。一次调用最多读 8 个小节。裁片必须包含完整的谱号和调号区域。
6. 成本预算按"每 8 小节"算，上限是 0.0150 元人民币，按闲时价格，保留四位小数。比较成本时一律换算成闲时价格，不然同一件事跑在高峰时段会被误判成超支。
7. `read.min_deg_eff` 取 12。它指的是裁片被模型压缩之后，谱线之间还剩多少像素；低于这个数只记一条警告，不中断。
8. 中间数据的版本号是 3.0。弦号约定第 1 弦是最低音弦。模型返回的弦号按 Guitar Pro 习惯（1 是最上面那条 TAB 线），在 `measure/` 里翻一次；写成 gp5 时再翻成"第 1 弦是最高音弦"，这个翻转只允许出现在 `writers/gp5/` 里。
9. 不读总小节数。小节总数直接取实际读到的小节个数。
10. 全局参数分四级：拍号和调弦、弦数是必须读的；调号次之；速度再次；曲名和作者最不重要。任何一项读不出来都不算失败，按缺省值补上，并把来源记在 `skeletonProvenance` 里。
11. 四层之间的依赖关系由 `tests/test_layers.py` 扫描 import 来强制检查。模型名字、各家接口的特殊参数这类东西，只能出现在 `providers/` 和 `configs/providers/` 目录里。
12. 终端输出分两条流：标准输出只放机器能读的事件，一行一个 JSON；标准错误放给人看的日志。事件序号从 1 开始连续递增，`run.finished` 全局只能出现一次。
13. 所有 JSON 和 gp5 文件都先写临时文件再改名，保证进程被杀时不留下半个文件。支持断点续跑，已经付过钱的调用不能重复付。
14. 检查不通过只报警，不中断。真正会中断的只有三种情况：图片根本没法用、成本超预算、写出的文件通不过自检。
15. 中文标题必须能按 cp936 编码写出。编不进去就报错退出，绝不允许写出乱码。
16. 程序不许自己补音符、补休止或者猜时值。不许把整页图发给模型。不许为了看清一个数字单独发一张小图，要问就拼成一张大图。裁片原则上不放大，只有像素实在太少时才可以放大，而且要记录下来。

---

## 评审重点：五类最容易咬人的情况

规格里提到了这些情况，但没有哪条任务天然会覆盖它们。下面逐条写清楚，并且都在对应任务里钉了测试。

第一，**最后一行谱往往很短**，有时候只占页面宽度的三成多。如果切图时按整页宽度算阈值，这一行会被整个丢掉。要专门处理，测试放在任务 4。

第二，**后面的行不会重复印拍号和调号**。如果把"没印"当成"换了拍号"，整首曲子的拍号都会错。测试放在任务 8。

第三，**两位数是一个数字、两个字形**。比如 `12` 占两格，但它只代表一个音符。拿字形个数去比音符个数会误报。测试放在任务 9。

第四，**裁片把谱号切掉**，模型读出来的音高会整段平移，而且它自己不会报错。这种裁片必须在送给模型之前就拒绝。测试放在任务 7。

第五，**中文标题**。gp5 文件里没有编码标记，用错编码写就会变成乱码，而且 Guitar Pro 不会提示。测试放在任务 11。

---

## 文件结构

下面这些文件都要新建，除非注明是修改。

```
AIAOMR/
├── pyproject.toml                  项目声明与依赖
├── src/aiaomr/
│   ├── cli.py                      命令行入口：解析参数、按顺序调各层、把结果转成事件
│   ├── events.py                   事件对象、写出 JSON 行、控制台人类可读的渲染
│   ├── kernel/
│   │   ├── ir.py                   中间数据结构（版本 3.0），也用它生成校验用的 schema
│   │   ├── contracts.py            各层之间传的数据类：页面、系统、小节框、裁片、任务、结果
│   │   ├── errors.py               错误码
│   │   └── config.py               读配置文件，处理覆盖顺序和四位小数
│   ├── providers/
│   │   ├── base.py                 模型接入的统一接口与能力声明
│   │   ├── registry.py             按名字取接入实现
│   │   └── deepseek_flash/
│   │       ├── client.py           构造请求、分类重试、算钱、离线回放
│   │       ├── caps.py             这个模型的能力表
│   │       └── README.md           接入说明、计费口径、踩过的坑
│   ├── measure/
│   │   ├── crop_plan.py            决定怎么裁、一张图放几个小节
│   │   ├── schema.py               校验模型返回的 JSON 结构
│   │   └── read.py                 一次调用的完整流程：裁片、提问、四道校验、转成结果
│   ├── score/
│   │   ├── locate/
│   │   │   ├── systems.py          找谱线、把五线谱和 TAB 配成一个系统
│   │   │   ├── bars.py             找小节线、把系统切成小节
│   │   │   └── crops.py            从页面图上裁出系统图
│   │   ├── skeleton/read.py        读全局参数，带缺省值
│   │   ├── verify/invariants.py    事后检查，产出一条条报警
│   │   └── assemble/assemble.py    排小节号、展开多小节休止、组装成中间数据
│   ├── writers/
│   │   ├── base.py                 输出格式的统一接口
│   │   ├── registry.py             按格式取写出实现
│   │   └── gp5/writer.py           写 gp5：先自检、再写、写完再读回来核对
│   └── eval/score.py               打分：先自测尺子，再量分数
├── tools/audit.mjs                 用 alphaTab 做的独立校验脚本
├── configs/
│   ├── default.toml                与模型无关的参数
│   ├── thresholds.toml             验收阈值
│   └── providers/deepseek-flash.toml  这个模型专用的参数
├── tests/                          测试，含 test_layers.py 检查分层
├── scripts/p0_probe.py             一次性的实测脚本，只用来定参数
└── out/                            运行产物，不入库
```

---

## 任务 0：先花两分钱做一次实测（需要模型的 key，可与后面的任务并行）

规格里有三个参数是拍脑袋定的：一张图放几个小节、裁片要多大、清晰度低到多少还能读。这三个数不实测就是在猜，所以开工前先花两分钱测一下。这一步的产出只有一份实测记录和三个改过的配置值，不进入正式代码。

**涉及文件**

新建 `scripts/p0_probe.py` 和 `docs/p0-results.md`。改 `configs/default.toml` 里的三个值。

- [x] **1. 写脚本。** 取统一小节，用三种清晰度各问一遍，再用一张图和六张图两种拿法各问三遍；记下用量、耗时、能不能解析、读出来的音符对不对。
- [x] **2. 跑脚本。** 需要 `DEEPSEEK_API_KEY`，命令是 `python scripts/p0_probe.py --out docs/p0-results.md`。
- [x] **3. 按结果改配置。** 把裁片大小、最低清晰度、每次调用的小节数改成实测出来最划算的值，并在实测记录里写清楚为什么这么定。
- [x] **4. 提交。** `git add scripts/p0_probe.py docs/p0-results.md configs/default.toml && git commit -m "chore: P0 probe results and calibrated crop params"`

> 没有 key 的时候这一步先空着，后面的任务照常做，各层测试全部走离线回放。

---

## 任务 1：项目骨架与共用数据结构

这一步先把项目立起来，并且把各层之间传递的数据格式定死。后面所有任务都依赖这里定义的名字，所以要先做，而且做完就不再改。

**涉及文件**

新建 `pyproject.toml`、`src/aiaomr/__init__.py`、`src/aiaomr/kernel/` 下的 `ir.py`、`contracts.py`、`errors.py`。测试写在 `tests/kernel/test_ir.py`、`tests/kernel/test_contracts.py`，分层检查写在 `tests/test_layers.py`。

**对外接口**

`ir.py` 定义 `IR`、`Score`、`Measure`、`Beat`、`Note`、`Structure`、`SkeletonProvenance` 这些类，字段照规格第 3.1 节。提供 `IR.from_json(path)` 和 `IR.to_json(path)`，后者必须是原子写。

`contracts.py` 定义 `PageSet`、`Page`、`System`、`MeasureBox`、`Crop`、`MeasureTask`、`MeasureResult`、`MeasureRead`、`Skeleton`、`Judgement`。其中 `Crop` 必须带一个布尔字段 `has_clef`，用来标记这张裁片有没有包含谱号区。

`errors.py` 定义 `ErrorCode` 枚举，成员照规格第 3.3 节。

- [x] **1. 先写一个会失败的测试。** 在 `tests/kernel/test_ir.py` 里写 `test_ir_roundtrip_and_invariants`：造一个最小的合法 IR，存成 JSON 再读回来，两者要相等；把调弦改成不递增，应该抛校验错误；把小节总数改成和实际条数不一致，也应该抛校验错误。
- [x] **2. 跑一遍，确认它失败。** 命令是 `pytest tests/kernel/test_ir.py -v`，这时候模块还不存在，应该看到导入失败。
- [x] **3. 实现 `ir.py`。** 用 pydantic 写数据类。小节总数不要当字段存，用校验器保证它等于小节列表的长度。拍号、调号、速度这三个列表，都要保证其中的小节号严格递增。
- [x] **4. 实现 `contracts.py` 和 `errors.py`。** 这两个文件里只有数据结构，不许有输入输出，也不许有业务判断。
- [x] **5. 写分层检查。** 在 `tests/test_layers.py` 里读一遍 `src/aiaomr` 下所有 Python 文件的 import 语句，逐条断言第 11 条硬约束里的依赖方向。比如 `providers/` 里的文件不许 import `measure`、`score`、`writers`。
- [x] **6. 跑全部测试。** 命令是 `pytest -q`，应该全绿。
- [x] **7. 提交。** `git add -A && git commit -m "feat(kernel): IR v3.0 schema and shared contracts"`

---

## 任务 2：事件流

以后的图形界面全靠这条流工作，所以它要在最前面做好。标准输出只放 JSON，一行一个；标准错误放人读的日志。

**涉及文件**

新建 `src/aiaomr/events.py`，测试写在 `tests/test_events.py`。

**对外接口**

`Event` 数据类，字段是版本号、序号、时间戳、级别、阶段、事件名和数据。

`Emitter` 类，初始化时接收一个输出流，提供 `emit(stage, event, level="info", **data)` 方法。

`HumanRenderer` 类，提供 `render(event)` 方法，返回要打印的那一行文字；遇到不认识的事件名返回 `None`。

`open_sink(path, fmt)` 函数，根据格式打开标准输出或者文件。

- [x] **1. 先写会失败的测试。** 三个测试：序号从 1 开始并且递增；每个事件恰好一行，每行都能被 JSON 解析，而且写完立刻刷出去；遇到不认识的事件名，人类可读渲染器返回 `None` 而不是崩溃。
- [x] **2. 跑一遍，确认失败。** `pytest tests/test_events.py -v`
- [x] **3. 实现 `events.py`。** 时间戳用带毫秒的 UTC 时间。写 JSON 时关掉 ASCII 转义，保证中文原样输出。每写完一行都要刷缓冲，否则界面上的进度会滞后。
- [x] **4. 跑一遍，确认通过。** `pytest tests/test_events.py -v`
- [x] **5. 提交。** `git commit -m "feat(events): NDJSON event stream and human renderer"`

---

## 任务 3：读配置

参数分散在三个文件里，要有一个地方按固定顺序合并它们。

**涉及文件**

新建 `src/aiaomr/kernel/config.py`，以及 `configs/default.toml`、`configs/thresholds.toml`、`configs/providers/deepseek-flash.toml`。测试写在 `tests/kernel/test_config.py`。

**对外接口**

`load_config(provider, overrides=None)` 返回一个不可变的 `Config`，可以通过属性读到裁片、读取、预算、模型四组参数。其中预算字段是 `Decimal` 类型，保留四位小数。

- [x] **1. 先写会失败的测试。** 四个：默认值能读出来，并且预算等于 `Decimal("0.0150")`；模型专用文件会覆盖默认值；写错的参数名要报错；预算按四舍五入保留四位小数。
- [x] **2. 跑一遍，确认失败。** `pytest tests/kernel/test_config.py -v`
- [x] **3. 实现。** 用 `tomllib` 依次读三个文件（Python 3.10 上没有这个标准库，用 `tomli` 顶替，3.11 起直接用标准库），优先级从低到高是默认文件、模型文件、命令行。遇到未知参数直接报错，不要静默忽略。
- [x] **4. 跑一遍，确认通过。** `pytest tests/kernel/test_config.py -v`
- [x] **5. 提交。** `git commit -m "feat(config): layered TOML config with four-decimal CNY budget"`

---

## 任务 4：找系统

这是整个流程的第一步：把整页谱按行切开。每一行里，上面是五线谱，下面是四线或五线的 TAB，要把它们配成一对。

**涉及文件**

新建 `src/aiaomr/score/locate/systems.py`。测试写在 `tests/score/test_systems.py`，测试用的合成页面放在 `tests/fixtures/pages.py` 里，用 numpy 现画。

**对外接口**

`row_groups(mask, frac, axis=1)` 返回一组行区间。

`staff_lines(arr, frac=0.60, max_thickness=60)` 返回每条谱线中心的纵坐标。

`pair_systems(lines, page_width, min_w)` 把谱线按五加四配对，返回 `System` 列表，每个系统带上下边界、TAB 区边界和 TAB 各弦的位置。

`find_systems(arr, page_width)` 是上面几步的组合，直接返回系统列表。

- [ ] **1. 先写会失败的测试。** 三个：合成一张画着三组谱表的页面，应该找到三个系统；**最后一行只画到页面宽度的三成四，仍然必须找到**（这是评审重点第一条）；画一条四十像素粗的黑边，不能被当成谱线。
- [ ] **2. 跑一遍，确认失败。** `pytest tests/score/test_systems.py -v`
- [ ] **3. 实现。** 把以前那个项目里的切图代码搬过来，但要把所有写死的像素值改成"谱线间距的倍数"。短末行不能用整页宽度判断，要对候选线组单独算它自己的覆盖率。
- [ ] **4. 跑一遍，确认通过。** `pytest tests/score/test_systems.py -v`
- [ ] **5. 提交。** `git commit -m "feat(locate): system detection with local-width fallback for short last lines"`

---

## 任务 5：切小节、定裁片

系统切出来以后，要找出小节线，并且决定每次给模型看多大一块。

**涉及文件**

新建 `src/aiaomr/score/locate/bars.py`、`src/aiaomr/score/locate/crops.py`、`src/aiaomr/measure/crop_plan.py`。测试写在 `tests/score/test_bars.py` 和 `tests/measure/test_crop_plan.py`。

**对外接口**

`bars.py` 里的 `find_bars(arr, system, deg)` 返回小节框列表。

`crops.py` 里的 `system_crop(img, system, pad_px=8)` 返回裁好的图和外框坐标。

`crop_plan.py` 里的 `plan(tasks, cfg)` 返回每张裁片和它对应的小节。裁片统一缩放到 1.6 百万像素：不足这个数的上采样，超过的按小节边界等分成 k 份，每份不超过上限；第二份之后的每一份，左边要拼一条几十像素宽的谱号调号条，并在提示里说明"左边这条是引用，不属于本段"。

- [ ] **1. 先写会失败的测试。** 四个：谱号区要并回第一个小节，不能凭空多出一个小节；裁剪边距不能叠加，否则会吃掉第一小节第一个数字；三百万像素的系统要切成两份；第二份要带上谱号条。
- [ ] **2. 跑一遍，确认失败。** `pytest tests/score/test_bars.py tests/measure/test_crop_plan.py -v`
- [ ] **3. 实现。** 同样从以前的项目里搬小节切分和裁图的代码，阈值一律改成谱线间距的倍数。谱号区宽度小于中位小节宽度的四成五时，判定它是系统边线而不是小节线。
- [ ] **4. 跑一遍，确认通过。**
- [ ] **5. 提交。** `git commit -m "feat(locate): measure grid and crop planner"`

---

## 任务 6：接模型

这一层是唯一允许发网络请求的地方。别的层只能通过它拿结果。

**涉及文件**

新建 `src/aiaomr/providers/base.py`、`src/aiaomr/providers/registry.py`、`src/aiaomr/providers/deepseek_flash/` 下的 `__init__.py`、`caps.py`、`client.py`、`README.md`。测试写在 `tests/providers/` 下。

**对外接口**

`base.py` 里定义 `ProviderCapabilities` 数据类，字段与规格第 2.3.2 节那张能力表一一对应；再定义 `VisionProvider` 协议，只有一个方法 `read(request)`，返回模型输出和用量。

`caps.py` 里给出 DeepSeek 的能力值。价格按人民币算，闲时输入每百万 token 一元、缓存命中两分钱、输出四元；高峰时段整体翻倍。

`client.py` 里 `DeepSeekClient` 实现上面那个协议。另有 `build_request(...)` 负责拼请求体，`cost_cny(usage, peak=False)` 负责算钱，`StubClient` 负责从录好的文件里回放、不发网络。

`registry.py` 里 `get_provider(name, cfg)` 按名字取实现，名字不认识就报错。

- [ ] **1. 先写会失败的测试。** 六个：图片只能出现在 user 消息里；请求开着 JSON 模式而且提示词里有 `json` 字样；返回空内容时重试两次后报结构错误；遇到 401 立刻报错不重试；闲时价格算出来是 `Decimal("0.0046")`；能力表的每个字段都要有值。
- [ ] **2. 跑一遍，确认失败。** `pytest tests/providers -v`
- [ ] **3. 实现。** 请求体只放白名单里的字段。重试按错误类型分：空内容和格式错重试两次，网络和服务端错误最多重试五次，鉴权错误一次都不重试。重试时只把截断到五百字以内的错误摘要发回去，不要把上一次的完整回复贴回去。
- [ ] **4. 跑一遍，确认通过。**
- [ ] **5. 写 `README.md`，记下模型版本、计费口径和踩过的坑，然后提交。** `git commit -m "feat(provider): DeepSeek V4.1-Flash adapter with caps and cost model"`

---

## 任务 7：读小节

这一层负责把一张裁片变成一组结构化的音符。模型返回的东西要过四道关：提示词约束、JSON 解析、结构校验、业务判断。前三道在这层做，第四道在任务 9。

**涉及文件**

新建 `src/aiaomr/measure/schema.py` 和 `src/aiaomr/measure/read.py`。测试写在 `tests/measure/test_read.py`。

**对外接口**

`schema.py` 里 `ModelMeasure` 描述模型返回的单个小节，`ModelResponse` 描述整个回复，`validate(raw)` 把字符串变对象，结构不对就抛错。

`read.py` 里 `read_systems(tasks, provider, cfg, emit)` 是这层的入口，返回 `MeasureResult` 列表。内部按"一次最多八小节"分批，并发数不超过配置里的上限。

- [ ] **1. 先写会失败的测试。** 五个：合法的返回能变成结果；缺了音高字段要报结构错误；小节顺序和请求对不上要报错；**裁片没有谱号区时，必须在发请求之前就拒绝**（这是评审重点第四条）；`12` 这种两位数要记成一个数字、两个字形。
- [ ] **2. 跑一遍，确认失败。** `pytest tests/measure/test_read.py -v`
- [ ] **3. 实现。** 四道关按顺序走。结构校验失败时，回给模型的错误摘要要截断，不能把整段回复贴回去。
- [ ] **4. 跑一遍，确认通过。**
- [ ] **5. 提交。** `git commit -m "feat(measure): four-gate response validation and system reading"`

---

## 任务 8：读全局参数

拍号、调号、调弦这些东西，一张谱上只印一两次，但错了会连累整首。所以这里要分级处理，读不出来就用缺省值顶上，并且记下这个值是哪来的。

**涉及文件**

新建 `src/aiaomr/score/skeleton/read.py`。测试写在 `tests/score/test_skeleton.py`。

**对外接口**

`read_skeleton(header_crop, provider, cfg, emit)` 返回 `Skeleton`。

`apply_ts_inference(skel, bar_durations)` 在拍号读不出来时，用各小节时值的众数回填，并把来源标成"推断"。

`Skeleton` 里存拍号变化列表、调号变化列表、速度变化列表、调弦、弦数、曲名、作者，还有一个记录每项来源的字典。

- [ ] **1. 先写会失败的测试。** 五个：能从页眉读出拍号和调号；**后面的系统没印拍号时要继承上一小节的值，不能生成一个变化事件**（这是评审重点第二条）；曲名读不出来时用文件名代替；速度读不出来时用 120 并把来源标成缺省；拍号读不出来时能靠小节时值推断。
- [ ] **2. 跑一遍，确认失败。** `pytest tests/score/test_skeleton.py -v`
- [ ] **3. 实现。** 按"必须读、次重要、可缺、最不重要"四级走。每一项读不出来都要有缺省值和来源标记，绝不允许因为缺一项就整首失败。
- [ ] **4. 跑一遍，确认通过。**
- [ ] **5. 提交。** `git commit -m "feat(skeleton): tiered reading with fallbacks and provenance"`

---

## 任务 9：事后检查

这一层不看图，只看读出来的结果，检查前后有没有矛盾。检查不通过只产生报警，不中断流程。

**涉及文件**

新建 `src/aiaomr/score/verify/invariants.py`。测试写在 `tests/score/test_invariants.py`。

**对外接口**

`Alarm` 数据类，记报警编号、规则、小节、声称值、期望值和裁片位置。

`check_all(measures, skel)` 返回报警列表。本计划只实现五条规则：小节时值对不对、音高和"弦号加品数"对不对得上、品数有没有越界、数字和音符的个数关系、反解出来的调弦和声明是否一致。

- [ ] **1. 先写会失败的测试。** 每条规则正反各一个。其中一条要专门写成：**七个数字、十三个字形、七个音符的情况下不能报警**（这是评审重点第三条，以前的项目在这里误报过）。还有一条：一个音符没有对应数字、又没有标成连音后半时，要报警。
- [ ] **2. 跑一遍，确认失败。** `pytest tests/score/test_invariants.py -v`
- [ ] **3. 实现。** 全是纯函数，输入输出不碰文件。判断小节时值要用"该小节生效的那个拍号"，不是全局唯一值。
- [ ] **4. 跑一遍，确认通过。**
- [ ] **5. 提交。** `git commit -m "feat(verify): invariants A1-A5 with digit/glyph asymmetry"`

---

## 任务 10：组装中间数据

把前面读到的碎片拼成最终要写出的结构：排好小节号、把多小节休止展开成对应数量的空小节。

**涉及文件**

新建 `src/aiaomr/score/assemble/assemble.py`。测试写在 `tests/score/test_assemble.py`。

**对外接口**

`assemble(measures, skel, alarms)` 返回 `IR`。

- [ ] **1. 先写会失败的测试。** 三个：标着"休止八小节"的地方要展开成八个空小节，同时保留这个标记；小节总数等于实际小节列表的长度；谱面上印的小节号优先于靠累加算出来的号。
- [ ] **2. 跑一遍，确认失败。** `pytest tests/score/test_assemble.py -v`
- [ ] **3. 实现。** 小节号先看谱面印的，没印就接着上一个加一；反复、房子、跳转这些只记下来，不在这里展开成物理小节。
- [ ] **4. 跑一遍，确认通过。**
- [ ] **5. 提交。** `git commit -m "feat(assemble): numbering chain and multi-rest expansion"`

---

## 任务 11：写 gp5

把中间数据写成 Guitar Pro 5 文件。写之前要自检一遍，写完要重新打开逐音核对一遍。

**涉及文件**

新建 `src/aiaomr/writers/base.py`、`src/aiaomr/writers/registry.py`、`src/aiaomr/writers/gp5/writer.py`。测试写在 `tests/writers/test_gp5.py`。

**对外接口**

`Writer` 协议只有一个方法 `write(ir, path)`，返回报告对象。`GP5Writer` 实现它。报告里记文件路径、字节数、往返核对结果和错误列表。

- [ ] **1. 先写会失败的测试。** 四个：写出去再用 PyGuitarPro 读回来，逐个音符要一致；弦号翻转只在这一处发生（中间数据里第 1 弦是最低弦，写进文件后要变成第 4 弦）；不认识的时值要报错；**中文标题要能按 cp936 写出去，编不进去时必须报错而不是写乱码**（这是评审重点第五条）。
- [ ] **2. 跑一遍，确认失败。** `pytest tests/writers/test_gp5.py -v`
- [ ] **3. 实现。** 从以前项目的 `gp_build.py` 搬自检、写出、回读三段。注意三个坑：PyGuitarPro 不会自动把音符挂到小节上，要显式 append；拍的默认状态是空，要设成正常；新建的曲子自带一条多余的吉他轨，要先清掉。
- [ ] **4. 跑一遍，确认通过。**
- [ ] **5. 提交。** `git commit -m "feat(writers): GP5 writer with roundtrip and cp936"`

---

## 任务 12：用第三方工具再查一遍

自己写自己验不算数。用 alphaTab 这个第三方库把写出来的 gp5 再读一遍，检查音高和时值对不对。

**涉及文件**

新建 `tools/audit.mjs` 和 `src/aiaomr/writers/audit.py`。测试写在 `tests/writers/test_audit.py`。

**对外接口**

`audit(gp5_path)` 返回一个字典，里面有音高不匹配的条数、时值错误的条数，以及明细。`audit.mjs` 读 gp5 输出同样的 JSON，Python 这边用子进程调它。

- [ ] **1. 先写会失败的测试。** 两个：任务 11 写出来的合法文件应该两项都是零；人为改坏一个小节的时值，错误数应该大于零。
- [ ] **2. 跑一遍，确认失败。**
- [ ] **3. 实现。** 把以前项目的 `gp_audit.mjs` 搬过来，改成本项目需要的数据格式。
- [ ] **4. 跑一遍，确认通过。** 机器上没装 Node 时这个测试跳过。
- [ ] **5. 提交。** `git commit -m "feat(writers): alphaTab audit as independent second opinion"`

---

## 任务 13：命令行跑通全流程

把前面各层串起来，做成一个能用的命令。同时把中断、续跑、退出码这些行为定下来。

**涉及文件**

新建 `src/aiaomr/cli.py`。测试写在 `tests/test_cli.py`，全部用离线回放，不联网。

**对外接口**

命令是 `python -m aiaomr.cli run`，参数包括输入、输入类别、曲名、输出格式、用哪个模型、是否续跑、强制重跑哪一段、停在哪一段。退出码：零表示成功，一表示输入不可用，二表示工具故障，三表示超预算，一百三十表示被中断。

- [ ] **1. 先写会失败的测试。** 四个：正常跑完要写出 gp5，并且事件流每行都是合法 JSON、序号连续、结束事件只有一个；写出校验失败时要留下阻断信息、之前的中间产物不能删、退出码是二；第二次带续跑参数运行时，调用次数不能增加；收到中断信号时，要等在途请求记账完再退出，退出码一百三十。
- [ ] **2. 跑一遍，确认失败。** `pytest tests/test_cli.py -v`
- [ ] **3. 实现。** 阶段顺序固定：登记输入、找系统、读全局参数、读小节、检查、组装、写文件、审计。每段开始和结束都发事件。所有文件原子写。中断处理只置标志位，不直接杀进程。
- [ ] **4. 跑一遍，确认通过。**
- [ ] **5. 提交。** `git commit -m "feat(cli): staged orchestration, NDJSON events, block semantics and resume"`

---

## 任务 14：打分器

要能量出"到底对了几成"，否则改了什么都是在猜。

**涉及文件**

新建 `src/aiaomr/eval/score.py`，并补全 `configs/thresholds.toml`。测试写在 `tests/eval/test_score.py`。

**对外接口**

`measure(ir, truth, max_measures=None)` 返回四个指标：对齐是否可信、弦号加品数是否一致、音高加时值是否完全一致、小节时值是否自洽。每个指标都必须带分母。

`selftest()` 先拿一个完美答案，再故意按已知方式破坏它，看每个指标是不是按预期下降；如果测不出来，就判定尺子不可信，拒绝打分。

- [ ] **1. 先写会失败的测试。** 三个：故意删掉一个音、把一个品数加一、改掉一个时值，对应指标要按预期下降；完美答案应该是满分；每个指标都要带分母。
- [ ] **2. 跑一遍，确认失败。** `pytest tests/eval/test_score.py -v`
- [ ] **3. 实现。** 从以前项目的 `accuracy.py` 搬方法论：阈值先写死再测量、必须带分母、先证明尺子能动。真值用以前项目里存好的 `.gp` 文件，用 `gp_dump.mjs` 导成 JSON 再比。
- [ ] **4. 跑一遍，确认通过。**
- [ ] **5. 提交。** `git commit -m "feat(eval): denominator-carrying metrics with selftest"`

---

## 任务 15：拿四首歌验收

这一步不再写代码，只跑真图、记结果。

**涉及文件**

新建 `docs/p1-report.md`；如果需要调整阈值，改 `configs/thresholds.toml`。

- [ ] **1. 跑四首歌。** 打上花火、NIGHT DANCER、Клетка、老人与海。每首跑一遍完整流程，再跑一遍审计和打分。
- [ ] **2. 把数字记进 `docs/p1-report.md`。** 每首一行：系统数、小节数、调用次数、重试次数、空返回次数、每 8 小节的成本、总耗时、审计结果、四个指标。
- [ ] **3. 判断过不过。** 弦号加品数一致率不低于 0.90，小节时值自洽率不低于 0.95，审计两项都是零，往返核对通过，事件流合法，同一输入重跑结果除时间与花费外逐行相同。任何一项不达标就回去改实现，不许改阈值；确实要改阈值，必须按规格第 16 节的例外流程写清理由。
- [ ] **4. 提交。** `git commit -m "docs: P1 acceptance report (class 3, 4 songs)"`

---

## 做的顺序和门

任务 1 到 3 互不依赖，可以同时开。任务 4、5 要等任务 1。任务 6 要等任务 1 和 3。任务 7 要等任务 5 和 6。其余按编号往下做。

任务 15 不过，不进 P2。任务 0（那次两分钱的实测）没做也能往下走，只是参数用估计值，验收报告里要注明"参数未标定"。

## 我自查过的地方

规格的每一节都能在这一份计划里找到对应的任务，除了这几块故意留到后面：报警后的复读与终裁、并发、剩下几条检查规则、视频与照片输入、图形界面。它们各自另写计划。

每个任务的第一步都是先写一个会失败的测试，第二步跑一遍确认它真的失败，然后才动实现。测试用例里写死了规格里的具体数值，比如 1.6 百万像素、0.0150 元、cp936，实现的人不需要再猜。

五个评审重点各自钉了一个测试，位置在任务 4、7、8、9、11。

## 以后另出的计划

P2 补报警后的自动复读和终裁，加上并发和真实语料库。P3 做视频截图，P4 做演奏视频里的长条谱，P5 做手机照片，P6 做图形界面。图形界面只读这份计划里那条事件流，不重写任何业务逻辑。
