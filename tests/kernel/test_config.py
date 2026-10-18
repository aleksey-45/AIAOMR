"""配置加载的测试：默认值、三层合并、未知参数、预算四位小数（规格 §5）。"""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from aiaomr.kernel.config import ConfigError, StaffConfig, load_config


def test_default_values_from_toml():
    """默认值必须与规格 §5 参数表一致，预算读出来是 Decimal("0.0150")。"""
    cfg = load_config("deepseek_flash")

    # provider 组：name 来自 default.toml，其余来自 configs/providers/deepseek-flash.toml
    assert cfg.provider.name == "deepseek_flash"
    assert cfg.provider.model == "deepseek-flash"
    assert cfg.provider.max_concurrency == 16
    assert cfg.provider.retry_empty == 2
    assert cfg.provider.retry_http == 5
    assert cfg.provider.thinking is False
    assert cfg.provider.max_tokens_rule == "400*measures+800"
    assert cfg.provider.temperature == 0

    # crop 组（P0 实测把裁片统一到 1.6 MP，见 docs/p0-results.md）
    assert cfg.crop.target_mp_min == 1.6
    assert cfg.crop.target_mp_max == 1.6
    assert cfg.crop.max_side_px == 4096
    assert cfg.crop.max_measures_per_call == 8
    assert cfg.crop.header_strip_px == (40, 100)

    # read / budget
    assert cfg.read.min_deg_eff == 12
    assert cfg.budget.cny_per_8measures == Decimal("0.0150")
    assert cfg.budget.precision == Decimal("0.0001")

    # locate / skeleton / structure
    assert cfg.locate.line_frac_min == 0.60
    assert cfg.locate.max_line_thickness_px == 25
    assert cfg.locate.tab_pair_gap_px == (60, 400)
    assert cfg.skeleton.infer_ts_min_measures == 3
    assert cfg.skeleton.default_tempo == 120
    assert cfg.skeleton.default_key == "CMajor"
    assert cfg.skeleton.title_from_filename is True
    assert cfg.structure.change_min_run == 3

    # emit / adjudicate / retain / run
    assert cfg.emit.encoding == "cp936"
    assert cfg.adjudicate.max_rounds == 2
    assert cfg.retain.crops is True
    assert cfg.run.inflight_grace_ms == 30000

    # 预算字段必须是 Decimal，不能是 float（规格 §5、§12）
    assert isinstance(cfg.budget.cny_per_8measures, Decimal)
    assert isinstance(cfg.budget.precision, Decimal)

    # Config 不可变
    with pytest.raises(FrozenInstanceError):
        cfg.crop.target_mp_max = 2.0


def test_provider_file_overrides_default_and_cli_overrides_provider():
    """优先级从低到高：default.toml → providers/<name>.toml → overrides。"""
    cfg = load_config("deepseek_flash")
    # provider 专属参数由 provider 文件提供
    assert cfg.provider.max_concurrency == 16
    assert cfg.provider.model == "deepseek-flash"

    overridden = load_config(
        "deepseek_flash",
        overrides={
            "provider.max_concurrency": 4,
            "crop.target_mp_max": 1.2,
        },
    )
    # 命令行覆盖能压过 provider 文件
    assert overridden.provider.max_concurrency == 4
    # 也能压过 default.toml
    assert overridden.crop.target_mp_max == 1.2
    # 没被覆盖的仍是 provider 文件里的值
    assert overridden.provider.model == "deepseek-flash"

    # 嵌套写法的覆盖等价于点号写法
    nested = load_config("deepseek_flash", overrides={"crop": {"max_measures_per_call": 4}})
    assert nested.crop.max_measures_per_call == 4


def test_unknown_or_mistyped_parameter_rejected():
    """未知参数名要报错（不许静默忽略），类型不对也要报错。"""
    with pytest.raises(ValueError) as excinfo:
        load_config("deepseek_flash", overrides={"crop.targt_mp_max": 1.2})
    assert "crop.targt_mp_max" in str(excinfo.value)

    with pytest.raises(ValueError) as excinfo:
        load_config("deepseek_flash", overrides={"budget.cny_per_ymmetry": "0.0150"})
    assert "budget.cny_per_ymmetry" in str(excinfo.value)

    # 类型不对：字符串不是数字，布尔不是整数
    with pytest.raises(ValueError):
        load_config("deepseek_flash", overrides={"crop.max_side_px": "2500"})
    with pytest.raises(ValueError):
        load_config("deepseek_flash", overrides={"retain.crops": "yes"})
    with pytest.raises(ValueError):
        load_config("deepseek_flash", overrides={"crop.header_strip_px": [100, 40]})

    # 未登记的 provider 名启动即报错
    with pytest.raises(ValueError):
        load_config("no_such_provider")


def test_budget_rounded_half_up_to_four_places():
    """预算量化到四位小数，用 ROUND_HALF_UP（0.01225 → 0.0123，不是 0.0122）。"""
    cfg = load_config("deepseek_flash", overrides={"budget.cny_per_8measures": "0.01225"})
    assert cfg.budget.cny_per_8measures == Decimal("0.0123")
    assert str(cfg.budget.cny_per_8measures) == "0.0123"

    # float 也要按十进制字面值四舍五入，不能走二进制浮点误差
    cfg = load_config("deepseek_flash", overrides={"budget.cny_per_8measures": 0.01234})
    assert str(cfg.budget.cny_per_8measures) == "0.0123"

    # 默认值保留末尾的零，指数是 -4
    cfg = load_config("deepseek_flash")
    assert str(cfg.budget.cny_per_8measures) == "0.0150"
    assert cfg.budget.cny_per_8measures.as_tuple().exponent == -4


# ---- staff.* 参数（spec-staff.md §11、spec-v3.md §5 参数表） ----


def test_staff_defaults_match_the_spec_table():
    """14 个 staff.* 参数的初值，逐项按规格 §5 写死（数值不是"大约"）。"""
    cfg = load_config("deepseek_flash")
    staff = cfg.staff

    assert isinstance(staff, StaffConfig)

    assert staff.band_margin_deg == 4.0
    assert staff.line_erase_pad_px == 1
    assert staff.head_w_deg == (0.7, 1.9)
    assert staff.head_h_deg == (0.3, 1.2)
    assert staff.head_fill_hollow_max == 0.55
    assert staff.head_fill_filled_min == 0.75
    assert staff.template_ncc_min == 0.75
    assert staff.stem_len_deg == (2.0, 5.5)
    assert staff.beam_coverage == 0.85
    assert staff.beam_thickness_deg == (0.3, 0.9)
    assert staff.layer_gap_deg == 0.8
    # 规格 §5 里 dot 一行写成 "3–0.45·deg²"，按两个字段实现：
    # 面积下限是 3 平方像素，上限是 deg² 的 0.45 倍。
    assert staff.dot_min_area_px == 3.0
    assert staff.dot_max_area_deg2 == 0.45
    assert staff.pair_max_deg == 1.2

    # 区间字段读出来是 (float, float) 二元组，标量是 float/int
    for pair in (staff.head_w_deg, staff.head_h_deg, staff.stem_len_deg, staff.beam_thickness_deg):
        assert isinstance(pair, tuple) and len(pair) == 2
        assert all(isinstance(item, float) for item in pair)
    assert isinstance(staff.line_erase_pad_px, int)
    for scalar in (
        staff.band_margin_deg,
        staff.head_fill_hollow_max,
        staff.head_fill_filled_min,
        staff.template_ncc_min,
        staff.beam_coverage,
        staff.layer_gap_deg,
        staff.dot_min_area_px,
        staff.dot_max_area_deg2,
        staff.pair_max_deg,
    ):
        assert isinstance(scalar, float)

    # 冻结：staff 组不许在运行时被改
    with pytest.raises(FrozenInstanceError):
        cfg.staff.band_margin_deg = 6.0


def test_staff_float_pair_rejects_reversed_range():
    """float_pair 和 int_pair 一样：下限大于上限就是配置错误。"""
    with pytest.raises(ConfigError) as excinfo:
        load_config("deepseek_flash", overrides={"staff.head_w_deg": [1.9, 0.7]})
    assert "staff.head_w_deg" in str(excinfo.value)

    with pytest.raises(ConfigError):
        load_config("deepseek_flash", overrides={"staff.head_w_deg": 0.7})  # 不是区间

    # 合法的覆盖能生效，命令行优先级最高
    overridden = load_config("deepseek_flash", overrides={"staff.head_w_deg": [0.8, 2.0]})
    assert overridden.staff.head_w_deg == (0.8, 2.0)


def test_staff_unknown_key_is_rejected():
    """未登记到 §5 参数表的名字一律报错，不许静默忽略。"""
    with pytest.raises(ConfigError) as excinfo:
        load_config("deepseek_flash", overrides={"staff.bogus_key": 1})
    assert "staff.bogus_key" in str(excinfo.value)


def test_staff_mistyped_values_are_rejected():
    with pytest.raises(ConfigError):
        load_config("deepseek_flash", overrides={"staff.band_margin_deg": "4.0"})
    with pytest.raises(ConfigError):
        load_config("deepseek_flash", overrides={"staff.line_erase_pad_px": 1.5})
    with pytest.raises(ConfigError):
        load_config("deepseek_flash", overrides={"staff.head_w_deg": [0.7]})
    with pytest.raises(ConfigError):
        load_config("deepseek_flash", overrides={"staff.head_w_deg": "0.7-1.9"})
    with pytest.raises(ConfigError):
        load_config("deepseek_flash", overrides={"staff.line_erase_pad_px": True})
