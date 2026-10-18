"""分层依赖检查：用 ast 扫描 src/aiaomr 下所有 Python 文件的 import 语句。

依据：规格 §2.0 的 LAY-01..LAY-06 与 §1.4（`tomli` 只用来读 TOML）。
规则不是写死的文件清单：扫描的是目录树，将来新增的文件自动纳入检查。
"""

import ast
import sys
from pathlib import Path

PKG = "aiaomr"
SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / PKG

# LAY-02..LAY-06：每一层禁止 import 的层。kernel 单独按 LAY-01 检查。
LAYER_FORBIDDEN = {
    "providers": {"measure", "score", "writers", "eval", "cli"},
    "measure": {"score", "writers", "eval", "cli"},
    "score": {"writers", "eval", "cli"},
    "writers": {"score", "measure", "providers", "eval", "cli"},
}
LAYER_RULE_ID = {
    "providers": "LAY-02",
    "measure": "LAY-03",
    "score": "LAY-04",
    "writers": "LAY-05",
}

# LAY-01：kernel 只许标准库与 pydantic。`tomli` 是规格 §2.0 LAY-01 与 §1.4
# 明写的例外：Python 3.10 上用它在 kernel/config.py 里读 TOML，3.11 起走标准库。
# `tomllib` 在 3.11 起才是标准库，这里按"标准库的一部分"处理。
KERNEL_ALLOWED_EXTERNAL = {"pydantic", "tomli", "tomllib"}

# LAY-03/LAY-04：只有 providers/ 允许直接发 HTTP。
HTTP_CLIENTS = ("requests", "urllib3", "httpx", "aiohttp", "http.client", "urllib.request")

# LAY-09：读五线谱（score/staff/）只许标准库、numpy、cv2 与 kernel/其它 L3 模块；
# 不许调模型、不许碰 providers/measure/writers（spec-staff.md §12.5）。
STAFF_ALLOWED_EXTERNAL = {"numpy", "cv2"}


def _module_name(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_targets(path: Path, root: Path):
    """返回 (被 import 的绝对模块名, 行号)，相对 import 也解析成绝对名。"""
    module = _module_name(path, root)
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = package.split(".")
                keep = len(base_parts) - (node.level - 1)
                base = ".".join(base_parts[:keep])
                target = f"{base}.{node.module}" if node.module else base
            else:
                target = node.module or ""
            targets.append((target, node.lineno))
            for alias in node.names:
                if alias.name != "*":
                    # `from aiaomr.score import writers` 这种要能看见 writers。
                    targets.append((f"{target}.{alias.name}", node.lineno))
    return targets


def _is_http_client(target: str) -> bool:
    return any(
        target == client or target.startswith(client + ".") for client in HTTP_CLIENTS
    )


def violations(root: Path = SRC_ROOT):
    """扫一遍源码树，返回所有违反 LAY 规则的说明。合法时返回空列表。"""
    problems = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parent).as_posix()
        module = _module_name(path, root)
        parts = module.split(".")
        layer = parts[1] if len(parts) > 1 else ""
        for target, lineno in _import_targets(path, root):
            top = target.split(".")[0]
            if rel.startswith("aiaomr/score/staff/"):
                if (
                    top not in sys.stdlib_module_names
                    and top not in STAFF_ALLOWED_EXTERNAL
                    and not target.startswith(PKG)
                ):
                    problems.append(
                        f"{rel}:{lineno}: LAY-09 score/staff/ 只允许标准库、numpy 与 cv2，"
                        f"这里 import 了 {target}"
                    )
                elif target.startswith(PKG + ".") and target.split(".")[1] in (
                    "providers", "measure", "writers",
                ):
                    problems.append(
                        f"{rel}:{lineno}: LAY-09 score/staff/ 禁止 import "
                        f"{target.split('.')[1]}/（{target}）"
                    )
            if layer == "kernel":
                allowed = (
                    top in sys.stdlib_module_names
                    or top in KERNEL_ALLOWED_EXTERNAL
                    or target == PKG
                    or target.startswith(PKG + ".kernel")
                )
                if not allowed:
                    problems.append(
                        f"{rel}:{lineno}: LAY-01 kernel/ 只允许标准库与 pydantic，"
                        f"这里 import 了 {target}"
                    )
                continue
            if target == PKG or target.startswith(PKG + "."):
                target_layer = target.split(".")[1]
                is_entrypoint = rel.endswith("aiaomr/__main__.py")
                if target_layer in ("eval", "cli") and not is_entrypoint:
                    # LAY-06：任何层都不许回头依赖编排与评测；__main__ 是入口本身，例外。
                    problems.append(
                        f"{rel}:{lineno}: LAY-06 {layer}/ 禁止 import "
                        f"{target_layer}/（{target}）"
                    )
                elif target_layer in LAYER_FORBIDDEN.get(layer, set()):
                    rule = LAYER_RULE_ID[layer]
                    problems.append(
                        f"{rel}:{lineno}: {rule} {layer}/ 禁止 import "
                        f"{target_layer}/（{target}）"
                    )
            if layer != "providers" and _is_http_client(target):
                problems.append(
                    f"{rel}:{lineno}: LAY-03/LAY-04 只有 providers/ 允许 import "
                    f"HTTP 客户端，这里 import 了 {target}"
                )
    return problems


def _write_source(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _violations_of(tmp_path: Path, rel: str, source: str):
    src = tmp_path / "src"
    _write_source(src, rel, source)
    return violations(src / PKG)


def test_source_tree_respects_layer_rules():
    assert violations() == []


def test_providers_may_not_import_measure(tmp_path):
    problems = _violations_of(
        tmp_path, "aiaomr/providers/x.py", "from aiaomr.measure import read\n"
    )
    assert any("LAY-02" in problem for problem in problems)


def test_providers_may_import_http_clients(tmp_path):
    problems = _violations_of(
        tmp_path,
        "aiaomr/providers/deepseek_flash/client.py",
        "import requests\nimport urllib3\n",
    )
    assert problems == []


def test_measure_may_not_import_score_or_writers(tmp_path):
    problems = _violations_of(
        tmp_path, "aiaomr/measure/read.py", "from aiaomr.score import assemble\n"
    )
    assert any("LAY-03" in problem for problem in problems)
    problems = _violations_of(
        tmp_path, "aiaomr/measure/read.py", "import aiaomr.writers.gp5.writer\n"
    )
    assert any("LAY-03" in problem for problem in problems)


def test_measure_may_not_import_requests(tmp_path):
    problems = _violations_of(tmp_path, "aiaomr/measure/read.py", "import requests\n")
    assert any("HTTP 客户端" in problem for problem in problems)


def test_measure_may_import_providers(tmp_path):
    problems = _violations_of(
        tmp_path, "aiaomr/measure/read.py", "from aiaomr.providers import base\n"
    )
    assert problems == []


def test_score_may_not_import_writers(tmp_path):
    problems = _violations_of(
        tmp_path,
        "aiaomr/score/assemble/assemble.py",
        "from ...writers.gp5 import writer\n",
    )
    assert any("LAY-04" in problem for problem in problems)


def test_writers_may_not_import_score(tmp_path):
    problems = _violations_of(
        tmp_path, "aiaomr/writers/gp5/writer.py", "from aiaomr.score import assemble\n"
    )
    assert any("LAY-05" in problem for problem in problems)


def test_kernel_only_imports_stdlib_pydantic_and_tomli(tmp_path):
    problems = _violations_of(
        tmp_path,
        "aiaomr/kernel/config.py",
        "import json\nimport tomli\nfrom pydantic import BaseModel\n",
    )
    assert problems == []
    problems = _violations_of(tmp_path, "aiaomr/kernel/ir.py", "import numpy\nimport requests\n")
    assert len([problem for problem in problems if "LAY-01" in problem]) == 2


def test_layers_may_not_import_eval_or_cli(tmp_path):
    problems = _violations_of(
        tmp_path, "aiaomr/score/assemble/assemble.py", "import aiaomr.eval.score\n"
    )
    assert any("LAY-06" in problem for problem in problems)
    problems = _violations_of(tmp_path, "aiaomr/kernel/ir.py", "from aiaomr.cli import run\n")
    assert any("LAY-01" in problem for problem in problems)


def test_staff_may_not_import_model_layers(tmp_path):
    """LAY-09：读谱层不调模型、不碰 providers/measure/writers（spec-staff.md §12.5）。"""
    problems = _violations_of(
        tmp_path, "aiaomr/score/staff/read.py", "from aiaomr.providers import base\n"
    )
    assert any("LAY-09" in problem for problem in problems)
    problems = _violations_of(
        tmp_path, "aiaomr/score/staff/heads.py", "from aiaomr.measure import schema\n"
    )
    assert any("LAY-09" in problem for problem in problems)


def test_staff_may_import_numpy_and_cv2(tmp_path):
    problems = _violations_of(
        tmp_path, "aiaomr/score/staff/heads.py", "import numpy\nimport cv2\n"
    )
    assert problems == []
