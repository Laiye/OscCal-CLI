"""config_validation 健壮性回归测试（P1）。

畸形 JSON（字段缺失、类型错误）必须返回错误消息列表，而不是抛
KeyError/TypeError 让加载流程崩溃。
"""

import json

import pytest

from osccal.core.config import _load_json
from osccal.core.config_validation import (
    validate_calibrator,
    validate_commands,
    validate_profile,
)


def _valid_commands() -> dict:
    return {
        "name": "n",
        "description": "d",
        "type": "pyvisa",
        "series": ["S"],
        "feature": {"meas": "merge"},
        "keyword": {
            "imp_fif": "FIF",
            "imp_meg": "MEG",
            "acquisition_mode_average": "AVER",
            "meas_amp": "AMP",
            "meas_period": "PERI",
            "meas_mean": "MEAN",
            "meas_risetime": "RIS",
            "meas_pos_overshoot": "POV",
            "meas_max": "MAX",
            "meas_min": "MIN",
            "acquire_stop_after_single": "SING",
        },
        "actions": {
            "preset": {
                "name": "preset",
                "type": "write",
                "commands_num": 1,
                "args_num": 0,
                "commands": ["*RST"],
                "args": [],
            }
        },
    }


def _valid_profile() -> dict:
    return {
        "name": "n",
        "description": "d",
        "factor": "f",
        "series": "S",
        "imp_has_50": True,
        "vertical_div": 8,
        "probe_default": 1,
        "init_time": 2,
        "calibration_limits": {
            "amp": {"lower": -2.0, "upper": 2.0},
            "dc_gain": {"lower": -2.0, "upper": 2.0},
            "delta_time": {"lower": -2.0, "upper": 2.0},
            "bandwidth": {"min_mhz": 100},
            "transient": {},
        },
        "points": {
            "delta_amp": [0.001],
            "dc_gain": [0.001],
            "delta_time": [1e-9],
            "bandwidth": [0.005],
        },
    }


def _valid_calibrator() -> dict:
    return {
        "name": "c",
        "description": "d",
        "type": "pyvisa",
        "keyword": {"imp_fif": "50", "imp_meg": "10000"},
        "probes": {"9560": {"edge_rise_times": [70e-12]}},
        "impedance_rules": {"9560": {"EDGE": ["50"]}},
        "actions": {},
    }


class TestMalformedCommands:
    def test_non_dict(self):
        assert validate_commands([]) == ["配置必须是 JSON 对象"]

    def test_missing_top_level(self):
        assert validate_commands({}) != []

    def test_action_missing_commands_num_does_not_crash(self):
        data = _valid_commands()
        del data["actions"]["preset"]["commands_num"]
        errors = validate_commands(data)
        assert any("commands_num" in e for e in errors)

    def test_action_commands_wrong_type(self):
        data = _valid_commands()
        data["actions"]["preset"]["commands"] = "not-a-list"
        errors = validate_commands(data)
        assert any("commands" in e for e in errors)

    def test_feature_wrong_type(self):
        data = _valid_commands()
        data["feature"] = "merge"
        errors = validate_commands(data)
        assert any("feature" in e for e in errors)


class TestMalformedProfile:
    def test_vertical_div_string(self):
        data = _valid_profile()
        data["vertical_div"] = "8"
        errors = validate_profile(data)
        assert "vertical_div 必须为正数" in errors

    def test_limits_missing_lower(self):
        data = _valid_profile()
        del data["calibration_limits"]["amp"]["lower"]
        errors = validate_profile(data)
        assert any("lower/upper" in e for e in errors)

    def test_limits_wrong_type(self):
        data = _valid_profile()
        data["calibration_limits"] = "nope"
        errors = validate_profile(data)
        assert any("calibration_limits" in e for e in errors)

    def test_points_contains_string(self):
        data = _valid_profile()
        data["points"]["delta_amp"] = ["0.001"]
        errors = validate_profile(data)
        assert any("含非正数" in e for e in errors)


class TestMalformedCalibrator:
    def test_rule_references_unknown_probe(self):
        data = _valid_calibrator()
        data["impedance_rules"]["9999"] = {"EDGE": ["50"]}
        errors = validate_calibrator(data)
        assert any("未定义的探头" in e for e in errors)

    def test_probe_missing_edge_rise_times(self):
        data = _valid_calibrator()
        del data["probes"]["9560"]["edge_rise_times"]
        errors = validate_calibrator(data)
        assert any("edge_rise_times" in e for e in errors)


def test_load_json_survives_validator_exception(tmp_path):
    """校验函数意外抛异常时 _load_json 应安全返回 {} 而非崩溃。"""
    fpath = tmp_path / "cmd.json"
    fpath.write_text(json.dumps({"a": 1}), encoding="utf-8")

    def boom(data):
        raise RuntimeError("模拟校验器缺陷")

    assert _load_json(str(fpath), validator=boom, label="指令集") == {}


def test_load_json_returns_errors_for_malformed(tmp_path):
    fpath = tmp_path / "cmd.json"
    fpath.write_text(json.dumps({"name": "x"}), encoding="utf-8")
    assert _load_json(str(fpath), validator=validate_commands, label="指令集") == {}


@pytest.mark.parametrize("validator", [validate_commands, validate_profile, validate_calibrator])
def test_validators_never_raise_on_arbitrary_input(validator):
    for bad in ({}, [], "x", None, 1, {"actions": None}):
        assert isinstance(validator(bad), list)
