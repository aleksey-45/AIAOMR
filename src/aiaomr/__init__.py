"""aiaomr：把贝斯谱图片认成 Guitar Pro 5 文件。

代码分四层（providers → measure → score → writers），共享 kernel。
依赖方向由 tests/test_layers.py 扫描 import 强制检查。
"""

__version__ = "0.1.0"
