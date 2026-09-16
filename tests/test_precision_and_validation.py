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
    assert cell.value == error
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
