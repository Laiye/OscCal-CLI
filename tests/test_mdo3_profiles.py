"""3 Series MDO Profile（MDO34 / MDO32）单元测试。

校验两个特征配置文件满足 BaseCalibrator 与 measure 模块依赖的字段契约：
- factor / series / imp_has_50 / vertical_div / probe_default / init_time
- calibration_limits 各项上下限
- points 各校准点表（delta_amp / dc_gain / delta_time / bandwidth）合法
- MDO34=4 通道、MDO32=2 通道，均支持 50Ω
"""

import pytest

REQUIRED_PROFILE_KEYS = {
    "name",
    "description",
    "factor",
    "series",
    "imp_has_50",
    "vertical_div",
    "probe_default",
    "init_time",
    "calibration_limits",
    "points",
}

REQUIRED_POINT_TABLES = {"bandwidth", "delta_amp", "dc_gain", "delta_time"}

REQUIRED_LIMIT_ITEMS = {"amp", "dc_gain", "delta_time", "bandwidth", "transient"}


# ===========================================================================
# 共用 profile 校验逻辑（参数化覆盖 MDO34 / MDO32）
# ===========================================================================


@pytest.fixture(params=["mdo34_profile", "mdo32_profile"])
def any_profile(request):
    """依次对 MDO34 与 MDO32 profile 执行同一套校验。"""
    return request.getfixturevalue(request.param)


def test_profile_required_keys(any_profile):
    missing = REQUIRED_PROFILE_KEYS - set(any_profile.keys())
    assert not missing, f"缺少字段: {missing}"


def test_profile_factor_is_tektronix(any_profile):
    assert any_profile["factor"] == "tektronix"


def test_profile_series_in_mdo3_commands(any_profile, mdo3_commands):
    """profile 的 series 应被指令集 series 列表覆盖。"""
    assert any_profile["series"] in mdo3_commands["series"]


def test_profile_supports_50ohm(any_profile):
    """3 Series MDO 所有模拟通道均支持 50Ω 与 1MΩ。"""
    assert any_profile["imp_has_50"] is True


def test_profile_vertical_div(any_profile):
    assert any_profile["vertical_div"] == 8


def test_profile_probe_default(any_profile):
    assert any_profile["probe_default"] == 1


def test_profile_init_time_positive(any_profile):
    assert any_profile["init_time"] > 0


def test_profile_calibration_limits_items(any_profile):
    limits = any_profile["calibration_limits"]
    missing = REQUIRED_LIMIT_ITEMS - set(limits.keys())
    assert not missing, f"calibration_limits 缺少项: {missing}"


@pytest.mark.parametrize("item", ["amp", "dc_gain", "delta_time"])
def test_profile_error_limits_range(any_profile, item):
    """amp/dc_gain/delta_time 误差限上下限应为 ±2.0%。"""
    lim = any_profile["calibration_limits"][item]
    assert lim["upper"] == 2.0
    assert lim["lower"] == -2.0


def test_profile_bandwidth_min_mhz_positive(any_profile):
    bw = any_profile["calibration_limits"]["bandwidth"]
    assert bw.get("min_mhz", 0) > 0


def test_profile_point_tables_exist(any_profile):
    points = any_profile["points"]
    missing = REQUIRED_POINT_TABLES - set(points.keys())
    assert not missing, f"points 缺少点表: {missing}"


@pytest.mark.parametrize("table", sorted(REQUIRED_POINT_TABLES))
def test_profile_point_table_nonempty(any_profile, table):
    table_data = any_profile["points"][table]
    assert isinstance(table_data, list)
    assert len(table_data) > 0, f"{table} 点表为空"


@pytest.mark.parametrize("table", ["delta_amp", "dc_gain"])
def test_profile_voltage_points_sorted_positive(any_profile, table):
    """幅度/直流增益点表应升序且为正。"""
    pts = any_profile["points"][table]
    assert all(v > 0 for v in pts), f"{table} 含非正值"
    assert pts == sorted(pts), f"{table} 未升序"


def test_profile_delta_amp_equals_dc_gain(any_profile):
    """幅度与直流增益共用同一垂直挡位点表。"""
    assert any_profile["points"]["delta_amp"] == any_profile["points"]["dc_gain"]


def test_profile_delta_time_sorted_positive(any_profile):
    pts = any_profile["points"]["delta_time"]
    assert all(v > 0 for v in pts)
    assert pts == sorted(pts)


def test_profile_bandwidth_points_sorted_positive(any_profile):
    pts = any_profile["points"]["bandwidth"]
    assert all(v > 0 for v in pts)
    assert pts == sorted(pts)


# ===========================================================================
# MDO34 / MDO32 差异化校验
# ===========================================================================


def test_mdo34_is_4_channel(mdo34_profile):
    assert mdo34_profile.get("channels") == 4
    assert mdo34_profile["series"] == "MDO34"
    assert "4-channel" in mdo34_profile["description"]


def test_mdo32_is_2_channel(mdo32_profile):
    assert mdo32_profile.get("channels") == 2
    assert mdo32_profile["series"] == "MDO32"
    assert "2-channel" in mdo32_profile["description"]


def test_mdo32_bandwidth_min_lower_than_mdo34(mdo34_profile, mdo32_profile):
    """MDO32 最低带宽档（70MHz）低于 MDO34（100MHz）。"""
    mdo32_min = mdo32_profile["calibration_limits"]["bandwidth"]["min_mhz"]
    mdo34_min = mdo34_profile["calibration_limits"]["bandwidth"]["min_mhz"]
    assert mdo32_min < mdo34_min


# ===========================================================================
# 指令集通道参数应覆盖 MDO34 的 4 通道（超集）
# ===========================================================================


def test_commands_channel_args_cover_4_channels(mdo3_commands):
    """共享指令集的通道参数取 4 通道超集（MDO32 仅用 1、2）。"""
    actions = mdo3_commands["actions"]
    for action_name in (
        "set_channel",
        "set_vertical_scale",
        "set_vertical_position",
        "set_trigger_source",
        "set_trigger_level",
        "set_impedance",
    ):
        channel_choices = actions[action_name]["args"][0]
        assert channel_choices == ["1", "2", "3", "4"], (
            f"{action_name} 通道参数应为 1-4 超集，实际 {channel_choices}"
        )
