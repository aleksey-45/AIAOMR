"""读配置：`configs/default.toml` → `configs/providers/<name>.toml` → 命令行覆盖。

规格 §5 约定：与 provider 无关的参数进 `configs/default.toml`，provider 专属参数
（模型名、并发、重试、thinking、max_tokens、温度）进 `configs/providers/<name>.toml`。
本模块只做三件事：找到三个文件、按优先级合并、把值校验成不可变的 `Config`。

数值默认值只在 TOML 里写一份，代码里不重复（§5：代码里不许出现表外的魔数）。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping

try:  # Python 3.11 起 TOML 读在标准库里（§1.4）
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 走这里
    import tomli as tomllib


class ConfigError(ValueError):
    """配置不合法：未知参数、类型不对、缺项、provider 文件不存在。

    这是启动期错误。规格 §3.3 没有给配置错误分配错误码，所以这里不伪造错误码，
    继承 `ValueError` 让调用方既能只捕 `ValueError`，也能精确捕 `ConfigError`。
    """


# 钱的量化位数。规格 §5 的 `budget.precision` = 0.0001（四位小数），
# 这里是它唯一的实现常量：只用于预算闸与回归比较，不与 provider 对账（§5、§12）。
_MONEY_QUANT = Decimal("0.0001")

# provider 专属参数：只许写在 configs/providers/<name>.toml 里（§1.6、§5）。
# provider 文件里用扁平键（`model = "..."`），合并后落在 `provider.model` 上。
_PROVIDER_ONLY = frozenset(
    {
        "model",
        "max_concurrency",
        "retry_empty",
        "retry_http",
        "thinking",
        "max_tokens_rule",
        "temperature",
    }
)


@dataclass(frozen=True)
class ProviderConfig:
    """§5 provider 组。`name` 由 `--provider` 决定，其余来自 provider 文件。"""

    name: str
    model: str
    max_concurrency: int
    retry_empty: int
    retry_http: int
    thinking: bool
    max_tokens_rule: str
    temperature: float


@dataclass(frozen=True)
class CropConfig:
    """§5 crop 组：裁片像素预算、长边、单次调用小节数、引用条宽度。"""

    target_mp_min: float
    target_mp_max: float
    max_side_px: int
    max_measures_per_call: int
    header_strip_px: tuple[int, int]
    # 裁片上下各留的冗余，按"五线谱上沿到 TAB 下沿"的高度比例给（RD-11）。
    vertical_pad_ratio: float


@dataclass(frozen=True)
class ReadConfig:
    """§5 read 组。"""

    min_deg_eff: float


@dataclass(frozen=True)
class BudgetConfig:
    """§5 budget 组。两个字段都是 `Decimal`，量化到四位小数。"""

    cny_per_8measures: Decimal
    precision: Decimal


@dataclass(frozen=True)
class LocateConfig:
    """§5 locate 组。"""

    line_frac_min: float
    max_line_thickness_px: int
    tab_pair_gap_px: tuple[int, int]


@dataclass(frozen=True)
class EmitConfig:
    """§5 emit 组。"""

    encoding: str


@dataclass(frozen=True)
class AdjudicateConfig:
    """§5 adjudicate 组。"""

    max_rounds: int


@dataclass(frozen=True)
class RetainConfig:
    """§5 retain 组。"""

    crops: bool


@dataclass(frozen=True)
class SkeletonConfig:
    """§5 skeleton 组：各项读不出时的兜底口径（S-01）。"""

    infer_ts_min_measures: int
    default_tempo: int
    default_key: str
    title_from_filename: bool


@dataclass(frozen=True)
class StructureConfig:
    """§5 structure 组：A11/A12 聚类检测参数（§2.2.3）。"""

    change_min_run: int


@dataclass(frozen=True)
class RunConfig:
    """§5 run 组：阻断时等待在途请求的宽限（§7.1.3）。"""

    inflight_grace_ms: int


@dataclass(frozen=True)
class Config:
    """合并后的不可变配置。按 §5 的分组用属性访问，例如 `cfg.crop.target_mp_max`。"""

    provider: ProviderConfig
    crop: CropConfig
    read: ReadConfig
    budget: BudgetConfig
    locate: LocateConfig
    emit: EmitConfig
    adjudicate: AdjudicateConfig
    retain: RetainConfig
    skeleton: SkeletonConfig
    structure: StructureConfig
    run: RunConfig


# 值的形状标签。只描述类型，不带默认值：默认值只在 TOML 里写一份。
_STR = "str"
_INT = "int"
_FLOAT = "float"
_BOOL = "bool"
_DECIMAL = "decimal"
_INT_PAIR = "int_pair"

# 参数登记表。逐项对应规格 §5 的参数表：不在表里的名字一律报错，不许静默忽略。
_SCHEMA: dict[str, str] = {
    "provider.name": _STR,
    "provider.model": _STR,
    "provider.max_concurrency": _INT,
    "provider.retry_empty": _INT,
    "provider.retry_http": _INT,
    "provider.thinking": _BOOL,
    "provider.max_tokens_rule": _STR,
    "provider.temperature": _FLOAT,
    "crop.target_mp_min": _FLOAT,
    "crop.target_mp_max": _FLOAT,
    "crop.max_side_px": _INT,
    "crop.max_measures_per_call": _INT,
    "crop.header_strip_px": _INT_PAIR,
    "crop.vertical_pad_ratio": _FLOAT,
    "read.min_deg_eff": _FLOAT,
    "budget.cny_per_8measures": _DECIMAL,
    "budget.precision": _DECIMAL,
    "locate.line_frac_min": _FLOAT,
    "locate.max_line_thickness_px": _INT,
    "locate.tab_pair_gap_px": _INT_PAIR,
    "emit.encoding": _STR,
    "adjudicate.max_rounds": _INT,
    "retain.crops": _BOOL,
    "skeleton.infer_ts_min_measures": _INT,
    "skeleton.default_tempo": _INT,
    "skeleton.default_key": _STR,
    "skeleton.title_from_filename": _BOOL,
    "structure.change_min_run": _INT,
    "run.inflight_grace_ms": _INT,
}

_GROUPS: tuple[tuple[str, type], ...] = (
    ("provider", ProviderConfig),
    ("crop", CropConfig),
    ("read", ReadConfig),
    ("budget", BudgetConfig),
    ("locate", LocateConfig),
    ("emit", EmitConfig),
    ("adjudicate", AdjudicateConfig),
    ("retain", RetainConfig),
    ("skeleton", SkeletonConfig),
    ("structure", StructureConfig),
    ("run", RunConfig),
)


def repo_root() -> Path:
    """从本模块位置向上找含 `configs/default.toml` 的仓库根。

    不依赖当前工作目录：从任意 cwd 运行都能找到配置文件。
    """
    module = Path(__file__).resolve()
    for parent in module.parents:
        if (parent / "configs" / "default.toml").is_file():
            return parent
    raise ConfigError(f"从 {module} 向上找不到含 configs/default.toml 的仓库根")


def load_config(provider: str, overrides: Mapping[str, Any] | None = None) -> Config:
    """按 `default.toml` → `providers/<provider>.toml` → `overrides` 的顺序合并配置。

    `overrides` 是命令行覆盖，优先级最高；键用点号写法（`"crop.target_mp_max": 1.2`），
    也可以写成嵌套字典（`{"crop": {"target_mp_max": 1.2}}`）。
    未知参数名、类型不对、缺项、provider 文件不存在都抛 `ConfigError`。
    `--provider` 决定读哪份 provider 文件，并作为 `provider.name` 的取值；
    `default.toml` 里的 `provider.name` 只是缺省值。
    """
    if not isinstance(provider, str) or not provider:
        raise ConfigError(f"provider 必须是非空字符串，拿到 {provider!r}")
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, Mapping):
        raise ConfigError(f"overrides 必须是字典，拿到 {type(overrides).__name__}")

    configs_dir = repo_root() / "configs"
    default_path = configs_dir / "default.toml"
    provider_path = _provider_file(configs_dir, provider)

    merged: dict[str, Any] = {}
    origin: dict[str, str] = {}

    # 第一层：与 provider 无关的参数（§5 表）。
    default_data = _flatten(_read_toml(default_path))
    misplaced = sorted(
        key for key in default_data if key.startswith("provider.") and key[len("provider."):] in _PROVIDER_ONLY
    )
    if misplaced:
        raise ConfigError(
            f"provider 专属参数必须写在 configs/providers/<name>.toml 里，"
            f"不许写进 configs/default.toml：{', '.join(misplaced)}（规格 §5）"
        )
    for key, value in default_data.items():
        merged[key] = value
        origin[key] = str(default_path)

    # 第二层：provider 文件。扁平键映射到 provider 组。
    for key, value in _flatten(_read_toml(provider_path)).items():
        if key not in _PROVIDER_ONLY:
            raise ConfigError(
                f"{provider_path} 里有不该出现的参数：{key!r}；"
                f"provider 文件只允许 {', '.join(sorted(_PROVIDER_ONLY))}（规格 §5）"
            )
        merged[f"provider.{key}"] = value
        origin[f"provider.{key}"] = str(provider_path)

    # --provider 是当前 provider 的权威来源；命令行覆盖仍然可以再压过它。
    merged["provider.name"] = provider
    origin["provider.name"] = "--provider 参数"

    # 第三层：命令行覆盖，优先级最高。
    for key, value in _flatten(overrides).items():
        merged[key] = value
        origin[key] = "overrides"

    unknown = sorted(key for key in merged if key not in _SCHEMA)
    if unknown:
        detail = "；".join(f"{key}（来自 {origin[key]}）" for key in unknown)
        raise ConfigError(f"未知参数：{detail}。规格 §5 的参数表里没有这些名字，不许静默忽略")

    missing = [key for key in _SCHEMA if key not in merged]
    if missing:
        raise ConfigError(f"缺少参数：{', '.join(missing)}（规格 §5 的参数表要求全部存在）")

    values = {
        key: _coerce(kind, merged[key], f"{key}（来自 {origin[key]}）")
        for key, kind in _SCHEMA.items()
    }
    return _build(values)


def _provider_file(configs_dir: Path, provider: str) -> Path:
    """定位 `configs/providers/<provider>.toml`；不存在即启动报错（§5）。

    登记名用下划线（§2.3.2、§5），文件名用连字符（§1.5），两种写法都认。
    """
    if "/" in provider or "\\" in provider or provider in {".", ".."}:
        raise ConfigError(f"provider 名字不许带路径分隔符：{provider!r}")
    stems = [provider, provider.replace("_", "-")]
    for stem in dict.fromkeys(stems):  # 去重并保序
        path = configs_dir / "providers" / f"{stem}.toml"
        if path.is_file():
            return path
    tried = "、".join(str(configs_dir / "providers" / f"{stem}.toml") for stem in dict.fromkeys(stems))
    raise ConfigError(f"未登记的 provider：{provider!r}；找不到 {tried}（规格 §5：其余名字启动即报错）")


def _read_toml(path: Path) -> dict[str, Any]:
    """读一份 TOML。Python 3.10 用 tomli，3.11 起用标准库 tomllib。"""
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"找不到配置文件：{path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} 不是合法的 TOML：{exc}") from exc


def _flatten(data: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """把嵌套字典压成点号键；`overrides` 的两种写法由此统一。"""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            raise ConfigError(f"参数名必须是字符串，拿到 {key!r}")
        name = f"{prefix}{key}"
        if isinstance(value, Mapping):
            flat.update(_flatten(value, f"{name}."))
        else:
            flat[name] = value
    return flat


def _coerce(kind: str, value: Any, where: str) -> Any:
    """把 TOML 读出来的值校验成目标形状；类型不对一律报错，不做隐式转换。"""
    if kind is _STR:
        if type(value) is not str:
            raise ConfigError(f"{where} 必须是字符串，拿到 {value!r}")
        return value
    if kind is _INT:
        # bool 是 int 的子类，必须显式挡掉。
        if type(value) is not int:
            raise ConfigError(f"{where} 必须是整数，拿到 {value!r}")
        return value
    if kind is _FLOAT:
        if type(value) not in (int, float):
            raise ConfigError(f"{where} 必须是数字，拿到 {value!r}")
        return float(value)
    if kind is _BOOL:
        if type(value) is not bool:
            raise ConfigError(f"{where} 必须是布尔值，拿到 {value!r}")
        return value
    if kind is _DECIMAL:
        if type(value) not in (int, float, str, Decimal):
            raise ConfigError(f"{where} 必须是十进制数，拿到 {value!r}")
        try:
            # 走字符串，避免二进制浮点误差：Decimal(0.015) 不精确。
            return Decimal(str(value)).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
        except InvalidOperation:
            raise ConfigError(f"{where} 不是合法的十进制数：{value!r}") from None
    if kind is _INT_PAIR:
        if not isinstance(value, (list, tuple)) or len(value) != 2 or any(type(item) is not int for item in value):
            raise ConfigError(f"{where} 必须是两个整数组成的区间 [下限, 上限]，拿到 {value!r}")
        low, high = value
        if low > high:
            raise ConfigError(f"{where} 的下限 {low} 大于上限 {high}")
        return (low, high)
    raise ConfigError(f"内部错误：{where} 的形状 {kind!r} 未登记")


def _build(values: Mapping[str, Any]) -> Config:
    """把点号键的值装进分组数据类。"""
    grouped: dict[str, dict[str, Any]] = {name: {} for name, _ in _GROUPS}
    for key, value in values.items():
        group, _, field = key.partition(".")
        grouped[group][field] = value
    return Config(**{name: cls(**grouped[name]) for name, cls in _GROUPS})


__all__ = [
    "AdjudicateConfig",
    "BudgetConfig",
    "Config",
    "ConfigError",
    "CropConfig",
    "EmitConfig",
    "LocateConfig",
    "ProviderConfig",
    "ReadConfig",
    "RetainConfig",
    "RunConfig",
    "SkeletonConfig",
    "StructureConfig",
    "load_config",
    "repo_root",
]
