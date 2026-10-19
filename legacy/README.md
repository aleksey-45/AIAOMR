# legacy —— 已废弃的代码

这里存放**不再维护**、但从 git 历史里单独摘出来会更难找回的东西。目前只有一个：几何读谱层。

## 目录

```
legacy/geometry/
├── staff/            原 src/aiaomr/score/staff/（判据、归属、时值、拍格、编排，13 个文件约 1776 行）
├── tests/            原 tests/staff/（257 个测试里属于它的那部分）
├── fixtures-heads/   原 tests/fixtures/heads/（28 个真图符头/休止/附点样本 + 真图节奏合成器）
├── spec-staff.md     原 docs/spec-staff.md（SR-01..62、AR-01..12、参数表；429 行）
└── cut_head_fixtures.py  原 tools/cut_head_fixtures.py（从真图裁样本的工具）
```

这些文件**不在** `src/aiaomr` 与 `tests/` 下，所以不参与分层检查、不被 pytest 收集、也不进包。

## 为什么废弃（2026-10-19）

结论：几何全符号主读这条路线，投入产出比不成立。证据：

1. **真页面只做到 2/7**：打上花火第 1 页第 1 系统 7 个小节里，只有 m17、m21 逐拍正确
   （half, eighth, dotted-quarter），其余 5 个小节因假休止、假符干、横梁层数错而 abstain。
2. **错的是 precision，不是分类**：28 个真图样本的符头/休止/附点混淆表全部在对角线上，
   真页面上符头数量也和真值一致；错的全是"本不该出现的符号"（连音弧被当休止、小节线残余被当竖线、
   粗横梁被拆成两层）。这些是分割/候选生成问题。
3. **维护成本失控**：一层里塞了 40 个参数、一批绝对像素偏移、三套表示（Finding/NoteGlyph/RhythmBeat）、
   两套坐标；编排文件 `read.py` 长到 302 行，主要是在吸收补丁式的过滤规则。
4. **根因在预处理**：全局阈值二值化 + 按等距网格整行抹谱线，会把穿线符号切坏（空心符头被切成弧、
   附点被吃掉、符干被切短）。要修得重做二值化、按列擦线、形态学提取、负样本校准——等于重写，
   而不是继续打补丁。

替代方案：时值回到"模型读、程序验算"的主路径（P1 已经跑通），几何只保留定位层
（系统、小节网格、TAB 带、裁片坐标）。这也和 AllegScore（模型读符号 + 人给全局参数）的做法一致。

## 如果将来要复活

这份代码在 `635de1a` 是完整可运行的。复活步骤：

1. `git show 635de1a:docs/spec-v3.md` 看当时 §2.11/§3.2/§5/§8/§10 的 staff 条目；
2. 把 `legacy/geometry/staff/` 拷回 `src/aiaomr/score/staff/`；
3. 从 `635de1a` 恢复 `kernel/contracts.py` 的四个数据结构与 `System.staffLines`、
   `kernel/config.py` 的 `StaffConfig` 与 `load_staff_config`、`configs/default.toml` 的 `[staff]`、
   `score/locate/systems.py` 的 `staff_line_runs`；
4. 把 `legacy/geometry/tests/` 拷回 `tests/staff/`（注意 `test_read.py` 要改名 `test_staff_read.py`，
   `tests/` 下没有 `__init__.py`，同名文件会冲突）；
5. 恢复 CLI 的 `staff` 阶段与事件（`635de1a:src/aiaomr/cli.py`）。

**不要原样复活**：先读 `docs/current-state.md` 与 git log 里 635de1a 之前的提交，
至少先换掉二值化与谱线移除，否则同样的 2/7 会再出现一次。

## 复用时值得先看的教训

- 模板匹配是**检测**，不是"先分割再分类"：把符头模板在整幅图上滑动相关，可以直接得到位置，
  不需要先把符头从符干/谱线里切出来（Audiveris 的 HEADS 步就是这么做的）。
- 绝对像素偏移是逐症状修补的产物：每一次"这张图上够用"的 `±2 px`，在换分辨率后都会变成错。
- 判据之间的契约要类型化，不能靠 `evidence` 字典的字符串键（`attachLeft`、`anchor`、`category`…）。
