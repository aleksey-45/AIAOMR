# tools/review —— 人工审核用的脚本

这里放**一次性或常用的人工审核工具**：把流水线的中间结果画出来给人看，不参与产品路径。
与 `tools/` 下的 `audit.mjs`（alphaTab 审计）和 `dump.mjs`（真值导出）不同，这里的脚本
输出的是图片/表格，用来肉眼核对，不产生交付物。

规矩：

- 只读 `src/aiaomr`，不改任何业务行为；发现框画错了，回 `src` 里改定位层，不在脚本里绕。
- 输出默认写 `out/review/`（`out/` 已 gitignore），不要往 `corpus/` 或 `tests/fixtures/` 写。
- 一个脚本一个用途，文件名说明画的是什么；不要在这里堆流程编排。

## overlay_boxes.py

把定位层的小节框、五线谱带、TAB 带、谱号区（以及可选的"送给模型的裁片框"）画到页面上。

```bash
# 单页
.venv/Scripts/python.exe tools/review/overlay_boxes.py \
    --input "E:/Bass Guitar/AIAOMR/打上花火/1.png" --out out/review/打上花火_p1.png

# 整个目录（每页一张）
.venv/Scripts/python.exe tools/review/overlay_boxes.py \
    --input "E:/Bass Guitar/AIAOMR/打上花火" --out out/review

# 同时画出实际送给模型的裁片（按 system 分批 + 头部引用条）
.venv/Scripts/python.exe tools/review/overlay_boxes.py \
    --input "E:/Bass Guitar/AIAOMR/打上花火/1.png" --out out/review/打上花火_p1_crops.png --crop-plan
```

颜色：红 = 小节内容框，蓝 = 五线谱带，绿 = TAB 带，橙 = 谱号/调号/拍号区，品红 = 实际裁片框。
每页还会打印一段 JSON（系统数、小节数、裁片清单），可以贴进报告。
