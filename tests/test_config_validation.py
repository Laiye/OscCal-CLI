"""config_validation 健壮性回归测试（P1）。

畸形 JSON（字段缺失、类型错误）必须返回错误消息列表，而不是抛
KeyError/TypeError 让加载流程崩溃。
"""

import json

import pytest

from osccal.core.config import _load_json
from osccal.core.config_validation import (
    validate_calibrator,
    validate_characteristics,
    validate_commands,
    validate_scheme,
    validate_spec,
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


def _valid_characteristics() -> dict:
    """v0.3.0 契约：特征文件只声明硬件事实，不含校准点、方法与限值。"""
    return {
        "name": "n",
        "description": "d",
        "factor": "f",
        "series": "S",
        "channels": 2,
        "imp_has_50": True,
        "bandwidth_hz": 5e8,
        "vertical_div": 8,
        "horizontal_div": 10,
        "vertical_scales": [0.01, 0.1, 1.0],
        "horizontal_scales": [1e-9, 1e-6],
        "probe_default": 1,
        "init_time": 2,
    }


def _valid_spec() -> dict:
    """v0.3.0 契约：规范只声明条款、记录表、参考指标与偏离，不含取点/方法。"""
    return {
        "name": "JJF 测试",
        "spec_code": "JJF-TEST",
        "deviations": ["测试偏离"],
        "items": {
            "dc_gain": {
                "clause": "7.4",
                "title": "直流增益",
                "automatable": True,
                "record_table": "A.3",
            }
        },
    }


def _valid_scheme() -> dict:
    """v0.3.0 契约：方案声明项目方法、刺激条件与取点参数。"""
    return {
        "name": "测试方案",
        "description": "测试",
        "spec": "jjf1057_2026",
        "items": {
            "dc_gain": {
                "methods": ["square_amplitude", "dc_two_point"],
                "primary": "square_amplitude",
                "stimulus": {"shape": "SQU"},
                "points": {
                    "strategy": "scale_list",
                    "scales_v_per_div": [0.1],
                    "impedances": ["1M"],
                },
            }
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


class TestMalformedCharacteristics:
    def test_vertical_div_string(self):
        data = _valid_characteristics()
        data["vertical_div"] = "8"
        errors = validate_characteristics(data)
        assert any("vertical_div" in e for e in errors)

    def test_deprecated_points_rejected(self):
        data = _valid_characteristics()
        data["points"] = {"delta_amp": [0.001]}
        errors = validate_characteristics(data)
        assert any("已废弃字段" in e and "points" in e for e in errors)

    def test_deprecated_limits_rejected(self):
        data = _valid_characteristics()
        data["calibration_limits"] = {"amp": {"lower": -2.0, "upper": 2.0}}
        errors = validate_characteristics(data)
        assert any("已废弃字段" in e and "calibration_limits" in e for e in errors)

    def test_scale_list_must_ascend(self):
        data = _valid_characteristics()
        data["vertical_scales"] = [1.0, 0.1]
        errors = validate_characteristics(data)
        assert any("未升序" in e for e in errors)

    def test_scale_list_rejects_non_positive(self):
        data = _valid_characteristics()
        data["horizontal_scales"] = [0, 1e-6]
        errors = validate_characteristics(data)
        assert any("含非正数" in e for e in errors)

    def test_scale_list_rejects_duplicates(self):
        data = _valid_characteristics()
        data["vertical_scales"] = [0.1, 0.1]
        errors = validate_characteristics(data)
        assert any("重复" in e for e in errors)

    def test_missing_bandwidth_hz(self):
        data = _valid_characteristics()
        del data["bandwidth_hz"]
        errors = validate_characteristics(data)
        assert any("bandwidth_hz" in e for e in errors)

    def test_channels_must_be_positive(self):
        data = _valid_characteristics()
        data["channels"] = 0
        errors = validate_characteristics(data)
        assert any("channels" in e for e in errors)

    def test_max_vertical_scale_50_must_be_a_known_scale(self):
        data = _valid_characteristics()
        data["max_vertical_scale_50"] = 2.0
        errors = validate_characteristics(data)
        assert any("max_vertical_scale_50" in e for e in errors)

    def test_max_vertical_scale_50_accepts_known_scale(self):
        data = _valid_characteristics()
        data["max_vertical_scale_50"] = 1.0
        assert validate_characteristics(data) == []


class TestMalformedSpec:
    def test_valid_spec(self):
        assert validate_spec(_valid_spec()) == []

    def test_rejects_scheme_fields(self):
        data = _valid_spec()
        data["items"]["dc_gain"]["points"] = {"strategy": "scale_list"}
        errors = validate_spec(data)
        assert any("方案字段" in e and "points" in e for e in errors)

    def test_manual_item_requires_note(self):
        data = _valid_spec()
        data["items"]["visual_check"] = {
            "clause": "7.2",
            "title": "外观检查",
            "automatable": False,
            "record_table": "A.1",
        }
        errors = validate_spec(data)
        assert any("note" in e for e in errors)

    def test_bad_formula_type(self):
        data = _valid_spec()
        data["items"]["dc_gain"]["formula"] = {"gain": 1.0}
        errors = validate_spec(data)
        assert any("formula" in e for e in errors)

    def test_bad_record_fields_type(self):
        data = _valid_spec()
        data["items"]["dc_gain"]["record_fields"] = "通道"
        errors = validate_spec(data)
        assert any("record_fields" in e for e in errors)


class TestMalformedScheme:
    def test_valid_scheme(self):
        assert validate_scheme(_valid_scheme()) == []

    def test_rejects_manual_item(self):
        data = _valid_scheme()
        data["items"]["visual_check"] = {
            "methods": ["x"],
            "points": {"strategy": "fixed"},
        }
        errors = validate_scheme(data)
        assert any("未知或不可自动化" in e for e in errors)

    def test_rejects_unimplemented_method(self):
        data = _valid_scheme()
        data["items"]["dc_gain"]["methods"] = ["rms_readout"]
        data["items"]["dc_gain"]["primary"] = "rms_readout"
        errors = validate_scheme(data)
        assert any("未实现方法" in e for e in errors)

    def test_requires_primary_for_multi_method_item(self):
        data = _valid_scheme()
        del data["items"]["dc_gain"]["primary"]
        errors = validate_scheme(data)
        assert any("primary" in e for e in errors)

    def test_primary_must_be_in_methods(self):
        data = _valid_scheme()
        data["items"]["dc_gain"]["primary"] = "multi_point_lsq"
        errors = validate_scheme(data)
        assert any("primary" in e for e in errors)

    def test_accepts_method_selection(self):
        data = _valid_scheme()
        del data["items"]["dc_gain"]["primary"]
        data["items"]["dc_gain"]["method"] = "square_amplitude"
        assert validate_scheme(data) == []

    def test_method_must_be_in_methods(self):
        data = _valid_scheme()
        del data["items"]["dc_gain"]["primary"]
        data["items"]["dc_gain"]["method"] = "multi_point_lsq"
        errors = validate_scheme(data)
        assert any("method" in e for e in errors)

    def test_method_and_primary_conflict(self):
        data = _valid_scheme()
        data["items"]["dc_gain"]["method"] = "square_amplitude"
        errors = validate_scheme(data)
        assert any("不能同时声明" in e for e in errors)

    def test_method_on_single_method_item_rejected(self):
        data = _valid_scheme()
        data["items"]["input_impedance"] = {
            "methods": ["calibrator_load_measure"],
            "method": "calibrator_load_measure",
            "points": {"strategy": "channel_x_impedance"},
        }
        errors = validate_scheme(data)
        assert any("只有一个方法" in e for e in errors)

    def test_scale_list_requires_stimulus_shape(self):
        data = _valid_scheme()
        del data["items"]["dc_gain"]["stimulus"]
        errors = validate_scheme(data)
        assert any("stimulus.shape" in e for e in errors)

    def test_scale_list_must_ascend(self):
        data = _valid_scheme()
        data["items"]["dc_gain"]["points"]["scales_v_per_div"] = [0.2, 0.1]
        errors = validate_scheme(data)
        assert any("未升序" in e for e in errors)

    def test_by_impedance_is_valid_alternative(self):
        data = _valid_scheme()
        points = data["items"]["dc_gain"]["points"]
        points.pop("scales_v_per_div")
        points.pop("impedances")
        points["by_impedance"] = {
            "1M": {"scales_v_per_div": [0.1, 1.0]},
            "50": {"scales_v_per_div": [0.1]},
        }
        assert validate_scheme(data) == []

    def test_by_impedance_and_impedances_conflict(self):
        data = _valid_scheme()
        points = data["items"]["dc_gain"]["points"]
        points["by_impedance"] = {"1M": {"scales_v_per_div": [0.1]}}
        errors = validate_scheme(data)
        assert any("不能同时声明" in e for e in errors)

    def test_by_impedance_rejects_unknown_impedance(self):
        data = _valid_scheme()
        points = data["items"]["dc_gain"]["points"]
        points.pop("scales_v_per_div")
        points.pop("impedances")
        points["by_impedance"] = {"75": {"scales_v_per_div": [0.1]}}
        errors = validate_scheme(data)
        assert any("阻抗非法" in e for e in errors)

    def test_by_impedance_block_needs_scales(self):
        data = _valid_scheme()
        points = data["items"]["dc_gain"]["points"]
        points.pop("scales_v_per_div")
        points.pop("impedances")
        points["by_impedance"] = {"1M": {"screen_fraction": 0.8}}
        errors = validate_scheme(data)
        assert any("缺少 scales_v_per_div" in e for e in errors)

    def test_by_impedance_rejected_for_fixed_strategy(self):
        data = _valid_scheme()
        points = data["items"]["dc_gain"]["points"]
        points["strategy"] = "fixed"
        points["by_impedance"] = {"1M": {"scales_v_per_div": [0.1]}}
        errors = validate_scheme(data)
        assert any("不支持策略" in e for e in errors)

    def test_edge_speeds_must_be_positive_list(self):
        data = _valid_scheme()
        data["items"] = {
            "rise_time": {
                "methods": ["fast_edge"],
                "stimulus": {"shape": "EDGE"},
                "points": {"strategy": "channel_x_edge_speed", "edge_speeds_s": []},
            }
        }
        errors = validate_scheme(data)
        assert any("edge_speeds_s" in e for e in errors)

    def test_derived_samples_must_be_coprime(self):
        data = _valid_scheme()
        data["items"] = {
            "enob": {
                "methods": ["time_domain_lsq"],
                "stimulus": {"shape": "SIN"},
                "points": {
                    "strategy": "derived",
                    "samples_n": 1000,
                    "integer_cycles_n": 10,
                    "require_coprime": True,
                },
            }
        }
        errors = validate_scheme(data)
        assert any("不互质" in e for e in errors)

    def test_timebase_has_no_primary(self):
        data = _valid_scheme()
        data["items"] = {
            "timebase_error": {
                "methods": ["frequency_readout", "waveform_fit"],
                "primary": "frequency_readout",
                "stimulus": {"shape": "SIN"},
                "points": {
                    "strategy": "scale_list",
                    "horizontal_scales_s_per_div": [1e-6],
                },
            }
        }
        errors = validate_scheme(data)
        assert any("并列方法" in e for e in errors)

    def test_spec_reference_must_be_file_stem(self):
        data = _valid_scheme()
        data["spec"] = "jjf1057_2026.json"
        errors = validate_scheme(data)
        assert any("不含 .json" in e for e in errors)

    def test_notes_must_not_be_empty(self):
        data = _valid_scheme()
        data["items"]["dc_gain"]["notes"] = []
        errors = validate_scheme(data)
        assert any("notes" in e for e in errors)

    def test_user_action_prompt_must_not_be_blank(self):
        data = _valid_scheme()
        data["items"]["dc_gain"]["requires_user_action"] = {"pause": True, "prompt": " "}
        errors = validate_scheme(data)
        assert any("prompt" in e for e in errors)

    def test_unknown_item_field_is_rejected(self):
        data = _valid_scheme()
        data["items"]["dc_gain"]["unknown"] = 1
        errors = validate_scheme(data)
        assert any("未知字段" in e for e in errors)


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


@pytest.mark.parametrize(
    "validator",
    [
        validate_commands,
        validate_characteristics,
        validate_spec,
        validate_scheme,
        validate_calibrator,
    ],
)
def test_validators_never_raise_on_arbitrary_input(validator):
    for bad in ({}, [], "x", None, 1, {"actions": None}):
        assert isinstance(validator(bad), list)
