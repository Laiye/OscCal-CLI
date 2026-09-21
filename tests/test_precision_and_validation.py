"""原始误差判定与严格配置校验的回归测试。"""

import copy
import time

import pytest
from openpyxl import Workbook
from rich.table import Table

from osccal.core.config_validation import validate_calibrator, validate_commands, validate_profile
from osccal.core.export import _create_data_sheet
from osccal.core.table_configs import EXCEL_ITEM_CONFIGS
from osccal.measure.amp import AmpCalibrator
from osccal.measure.delta_time import DeltaTimeCalibrator


@pytest.mark.parametrize(
    "cal_class,point,scale",
    [(AmpCalibrator, "delta_amp", 0.1), (DeltaTimeCalibrator, "delta_time", 1e-6)],
)
@pytest.mark.parametrize("expected_error", [2.004, -2.004])
def test_original_error_drives_calculation_and_report(
    mdo3_commands,
    mdo34_profile,
    fluke_calibrator,
    fake_osc,
    monkeypatch,
    cal_class,
    point,
    scale,
    expected_error,
):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    profile = copy.deepcopy(mdo34_profile)
    profile["points"][point] = [scale]
    profile["skip_vertical_adjust"] = True
    cal = cal_class(fake_osc, fake_osc, mdo3_commands, fluke_calibrator, profile, "1", "9560")
    raw_standard = scale * (profile.get("vertical_div", 8) - 2) if point == "delta_amp" else scale
    cal._read_meas = lambda _: raw_standard * (1 + expected_error / 100)
    cal.run()
    error = cal.get_results()[0]["error"]
    assert error == pytest.approx(expected_error)
    assert abs(error) > 2
    table = Table("误差")
    cal.add_result_row(table, [round(error, 2)], (-2, 2), check_col=0, check_value=error)
    assert "[red]" in table.columns[0]._cells[0]
    name = "amp" if point == "delta_amp" else "delta_time"
    wb = Workbook()
    config = EXCEL_ITEM_CONFIGS[name]
    _create_data_sheet(wb, name, config, cal.get_results())
    cell = wb[config["title"]].cell(2, config["error_col"] + 1)
    # 单元格数值按显示精度整理（与终端表格一致），超差判定与标红仍用未舍入的原始误差
    assert cell.value == round(error, 2)
    assert cell.number_format == "0.00"
    assert cell.fill.fgColor.rgb == "00FF0000"


@pytest.mark.parametrize(
    "path,value",
    [
        (("actions",), {}),
        (("actions", "get_value"), None),
        (("actions", "set_channel", "args_num"), True),
        (("actions", "set_channel", "commands"), [{}]),
        (("actions", "set_channel", "args"), [[1], ["ON"]]),
        (("feature", "return_value_index"), -1),
        (("feature", "return_value_index"), "1"),
        (("feature", "meas"), []),
        (("feature", "meas_amp_scale"), 0),
        (("feature", "meas_amp_scale"), "2"),
        (("keyword", "meas_amp"), None),
        (("series",), [None]),
        (("models",), "MDO34"),
        (("type",), {}),
    ],
)
def test_command_contract_rejects_malformed_values(mdo3_commands, path, value):
    data = copy.deepcopy(mdo3_commands)
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert validate_commands(data)


@pytest.mark.parametrize(
    "path,value",
    [
        (("points", "delta_amp"), [0.001, "bad"]),
        (("points", "delta_amp"), [0.001, {}]),
        (("vertical_div",), float("inf")),
        (("vertical_div",), float("nan")),
        (("horizontal_div",), 2),
        (("channels",), True),
        (("channels",), 0),
        (("init_time",), -1),
        (("averages",), 1),  # 平均值至少 2，且必须为整数
        (("averages",), 64.0),
        (("averages",), 8192),
        (("calibration_limits", "amp", "upper"), float("nan")),
        (("calibration_limits", "bandwidth", "min_mhz"), float("inf")),
    ],
)
def test_profile_contract_rejects_malformed_values(mdo34_profile, path, value):
    data = copy.deepcopy(mdo34_profile)
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert validate_profile(data)


@pytest.mark.parametrize(
    "path,value",
    [
        (("actions",), {}),
        (("type",), []),
        (("impedance_rules", "9560", "DC"), [{}]),
        (("probes", "9530", "max_frequency_hz"), float("nan")),
        (("probes", "9530", "edge_rise_times"), [float("inf")]),
    ],
)
def test_calibrator_contract_rejects_malformed_values(fluke_calibrator, path, value):
    data = copy.deepcopy(fluke_calibrator)
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert validate_calibrator(data)


# ── 平均值与触发电平微调（噪声抬升峰峰值、平均粘滞） ────────────────────


def test_average_count_defaults_and_profile_override(
    mdo3_commands, mdo34_profile, fluke_calibrator, fake_osc
):
    """未声明 averages 的既有 Profile 仍用 16；声明后按声明值下发。"""
    cal = AmpCalibrator(
        fake_osc, fake_osc, mdo3_commands, fluke_calibrator, mdo34_profile, "1", "9560"
    )
    assert cal._get_measurement_averages() == 16

    profile = copy.deepcopy(mdo34_profile)
    profile["averages"] = 64
    cal = AmpCalibrator(fake_osc, fake_osc, mdo3_commands, fluke_calibrator, profile, "1", "9560")
    assert cal._get_measurement_averages() == 64

    # 畸形值（校验本应拦截）不应把非法数值下发到仪器
    profile["averages"] = 1
    cal = AmpCalibrator(fake_osc, fake_osc, mdo3_commands, fluke_calibrator, profile, "1", "9560")
    assert cal._get_measurement_averages() == 16


def test_trigger_level_nudge_scales_with_range_and_alternates(
    mdo3_commands, mdo34_profile, fluke_calibrator, fake_osc
):
    """微调量为挡位的 0.1 格、符号交替，并按指令集带/不带通道号。"""
    cal = AmpCalibrator(
        fake_osc, fake_osc, mdo3_commands, fluke_calibrator, mdo34_profile, "1", "9560"
    )
    cal._nudge_trigger_level(0.002)
    cal._nudge_trigger_level(0.005)
    cal._nudge_trigger_level(0.002)
    assert fake_osc.commands_matching("TRIGger:A:LEVel") == [
        "TRIGger:A:LEVel:CH1 0.0002",
        "TRIGger:A:LEVel:CH1 -0.0005",
        "TRIGger:A:LEVel:CH1 0.0002",
    ]


def test_trigger_level_nudge_is_noop_without_action(mdo3_commands, mdo34_profile, fake_osc):
    """指令集没有 set_trigger_level 时安全跳过，不产生任何写入。"""
    commands = copy.deepcopy(mdo3_commands)
    commands["actions"].pop("set_trigger_level")
    cal = AmpCalibrator(fake_osc, fake_osc, commands, {}, mdo34_profile, "1", "9560")
    cal._nudge_trigger_level(0.1)
    assert fake_osc.written == []


def test_meas_amp_scale_defaults_to_one_and_reads_config(
    mdo3_commands, mdo34_profile, fluke_calibrator, fake_osc
):
    """幅度换算系数：峰峰值类默认 1；有效值类（CRMs）由指令集声明 2；畸形值回退 1。"""
    cal = AmpCalibrator(
        fake_osc, fake_osc, mdo3_commands, fluke_calibrator, mdo34_profile, "1", "9560"
    )
    assert cal._get_meas_amp_scale() == 1.0

    commands = copy.deepcopy(mdo3_commands)
    commands["feature"] = {**commands.get("feature", {}), "meas_amp_scale": 2}
    cal = AmpCalibrator(fake_osc, fake_osc, commands, fluke_calibrator, mdo34_profile, "1", "9560")
    assert cal._get_meas_amp_scale() == 2.0

    for bad in (0, -1, "2", True):
        commands["feature"]["meas_amp_scale"] = bad
        cal = AmpCalibrator(
            fake_osc, fake_osc, commands, fluke_calibrator, mdo34_profile, "1", "9560"
        )
        assert cal._get_meas_amp_scale() == 1.0, f"{bad!r} 应回退为 1"


def test_crms_scale_is_applied_to_measured_value(
    mdo3_commands, mdo34_profile, fluke_calibrator, fake_osc, monkeypatch
):
    """有效值口径的读数应换算成峰峰值后再与标准值比较、再入报告。"""
    monkeypatch.setattr(time, "sleep", lambda _: None)
    commands = copy.deepcopy(mdo3_commands)
    commands["feature"] = {**commands.get("feature", {}), "meas_amp_scale": 2}
    profile = copy.deepcopy(mdo34_profile)
    profile["points"]["delta_amp"] = [0.1]
    profile["skip_vertical_adjust"] = True
    cal = AmpCalibrator(fake_osc, fake_osc, commands, fluke_calibrator, profile, "1", "9560")
    # 标准值 = 0.1 × (8-2) = 0.6 V（峰峰值口径）；CRMs 读到幅度 0.3 V → 换算后 0.6 V
    cal._read_meas = lambda _: 0.3
    cal.run()
    result = cal.get_results()[0]
    assert result["measured"] == pytest.approx(0.6)
    assert result["error"] == pytest.approx(0.0)
