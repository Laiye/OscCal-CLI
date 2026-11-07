"""校准点解析器（core/points.py）与 `osccal plan` 的守护用例。"""

import copy
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from osccal.cli import cli
from osccal.core.points import build_plan

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, sub: str) -> dict:
    with open(PROJECT_ROOT / sub / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def configs() -> tuple[dict, dict, dict, dict]:
    return (
        _load("jjf1057_2026.json", "specs"),
        _load("jjf1057_2026.json", "schemes"),
        _load("tektronix_mdo3052.json", "characteristics"),
        _load("fluke_9500b.json", "calibrators"),
    )


def _build(configs, spec=None, scheme=None, probe="9530", channels=None) -> dict:
    spec = spec if spec is not None else configs[0]
    scheme = scheme if scheme is not None else configs[1]
    return build_plan(spec, scheme, configs[2], configs[3], probe, channels or ["1", "2"])


@pytest.fixture(scope="module")
def plan(configs) -> dict:
    return _build(configs)


@pytest.fixture(scope="module")
def single_plan(configs) -> dict:
    return _build(configs, scheme=_load("jjf1057_2026_single.json", "schemes"))


def _by_name(plan: dict) -> dict[str, dict]:
    return {item["name"]: item for item in plan["items"]}


class TestPlanContent:
    def test_total_points(self, plan):
        # 4 + 12 + 14 + 36 + 4 + 4 + 8 + 12 + 8 + 2 = 104
        # 试验方案 Δt 保留 4 个水平挡位；MARK 时标使 800 ns~10 ms 均可测
        assert plan["total_points"] == 104

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("input_impedance", 4),
            ("dc_gain", 12),
            ("dc_offset", 14),
            ("freq_response_bandwidth", 36),
            ("enob", 4),
            ("rise_time", 4),
            ("timebase_error", 8),
            ("delta_v", 12),
            ("delta_t", 8),
            ("random_noise", 2),
        ],
    )
    def test_points_per_item(self, plan, name, expected):
        assert len(_by_name(plan)[name]["points"]) == expected

    def test_manual_items_have_no_points(self, plan):
        items = _by_name(plan)
        for name in ("visual_check", "self_cal_signal"):
            assert items[name]["status"] == "manual"
            assert items[name]["points"] == []

    def test_default_scheme_methods_reach_plan(self, plan):
        items = _by_name(plan)
        assert items["dc_gain"]["methods"] == [
            "square_amplitude",
            "dc_two_point",
            "multi_point_lsq",
        ]
        assert items["dc_gain"]["primary"] == "square_amplitude"
        assert items["dc_offset"]["methods"] == ["raw_lsq", "mean_readout"]
        assert items["dc_offset"]["primary"] == "raw_lsq"
        assert items["timebase_error"]["methods"] == [
            "frequency_readout",
            "waveform_fit",
        ]
        assert items["timebase_error"]["primary"] is None
        assert items["random_noise"]["methods"] == ["sample_stddev"]

    def test_impedance_tolerance_comes_from_spec(self, plan):
        points = _by_name(plan)["input_impedance"]["points"]
        tolerances = {p["impedance"]: p["tolerance_pct"] for p in points if p["channel"] == "1"}
        assert tolerances == {"1M": 0.5, "50": 1.0}

    def test_dc_gain_skips_50_ohm_above_limit(self, plan):
        skipped = _by_name(plan)["dc_gain"]["skipped"]
        assert len(skipped) == 4
        assert all(item["impedance"] == "50" for item in skipped)
        assert all("上限" in item["reason"] for item in skipped)

    def test_dc_offset_includes_50_ohm_except_high_scale(self, plan):
        points = [p for p in _by_name(plan)["dc_offset"]["points"] if p["channel"] == "1"]
        assert {p["impedance"] for p in points} == {"1M", "50"}
        fifty = {p["scale"] for p in points if p["impedance"] == "50"}
        assert fifty == {0.01, 0.1, 1.0}
        skipped = _by_name(plan)["dc_offset"]["skipped"]
        assert len(skipped) == 2
        assert all(item["impedance"] == "50" and item["scale"] == 10.0 for item in skipped)

    def test_delta_v_includes_50_ohm_below_limit(self, plan):
        points = [p for p in _by_name(plan)["delta_v"]["points"] if p["channel"] == "1"]
        assert {p["impedance"] for p in points} == {"1M", "50"}
        fifty = {p["scale"] for p in points if p["impedance"] == "50"}
        assert fifty == {0.01, 0.1}
        skipped = _by_name(plan)["delta_v"]["skipped"]
        assert len(skipped) == 4
        assert all(item["impedance"] == "50" for item in skipped)

    def test_enob_covers_both_impedances(self, plan):
        points = [p for p in _by_name(plan)["enob"]["points"] if p["channel"] == "1"]
        assert {p["impedance"] for p in points} == {"1M", "50"}
        assert len(points) == 2

    def test_dc_gain_standard_value_uses_screen_fraction(self, plan):
        point = next(
            p
            for p in _by_name(plan)["dc_gain"]["points"]
            if p["channel"] == "1" and p["scale"] == 0.01 and p["impedance"] == "1M"
        )
        assert point["std_value_vpp"] == pytest.approx(0.8 * 8 * 0.01)

    def test_bandwidth_uses_reference_and_ratios(self, plan):
        freqs = [
            p["frequency_hz"]
            for p in _by_name(plan)["freq_response_bandwidth"]["points"]
            if p["channel"] == "1" and p["impedance"] == "1M"
        ]
        assert freqs[0] == pytest.approx(50000)
        assert freqs[-1] == pytest.approx(5e8)
        assert len(freqs) == 9

    def test_bandwidth_covers_both_impedances(self, plan):
        points = [
            p for p in _by_name(plan)["freq_response_bandwidth"]["points"] if p["channel"] == "1"
        ]
        assert {p["impedance"] for p in points} == {"1M", "50"}
        assert len(points) == 18

    def test_enob_points_are_runtime(self, plan):
        points = _by_name(plan)["enob"]["points"]
        assert all(p["runtime"] is True for p in points)
        assert all(p["samples_n"] == 1000 for p in points)

    def test_random_noise_uses_smallest_scale(self, plan):
        points = _by_name(plan)["random_noise"]["points"]
        assert {p["vertical_scale"] for p in points} == {0.001}

    def test_rise_time_covers_each_edge_speed(self, plan):
        speeds = {p["edge_rise_time_s"] for p in _by_name(plan)["rise_time"]["points"]}
        assert speeds == {150e-12, 500e-12}

    def test_timebase_points_match_spec(self, plan):
        scales = [
            p["timebase_s_per_div"]
            for p in _by_name(plan)["timebase_error"]["points"]
            if p["channel"] == "1"
        ]
        # 1 µs/div 在 MDO3052 上不存在（1-2-4-8 序列），用 800 ns/div
        assert scales == [1e-8, 8e-7, 1e-4, 1e-2]

    def test_delta_t_uses_time_marker_for_all_scales(self, plan):
        """试验方案 Δt 改 MARK 后，4 个水平挡位都不再受 10 kHz 方波幅度档限制。"""
        item = _by_name(plan)["delta_t"]
        assert len(item["points"]) == 8
        assert item["skipped"] == []
        scales = {p["timebase_s_per_div"] for p in item["points"]}
        assert scales == {1e-8, 8e-7, 1e-4, 1e-2}

    def test_timebase_error_keeps_all_points(self, plan):
        """时基误差用正弦激励，0.1 Hz~600 MHz 覆盖全部 4 个时基挡位。"""
        assert len(_by_name(plan)["timebase_error"]["points"]) == 8
        assert _by_name(plan)["timebase_error"]["skipped"] == []

    def test_unknown_probe_marks_rise_time_skipped(self, configs):
        plan = _build(configs, probe="9999", channels=["1"])
        item = _by_name(plan)["rise_time"]
        assert item["points"] == []
        assert any("edge_rise_times" in s["reason"] for s in item["skipped"])


class TestSingleScheme:
    def test_same_point_count(self, single_plan):
        # 单方法用直流两点法：50 Ω 1 V/div 只需 ±3.2 V 直流，不再被方波 5 Vpp 上限误杀。
        assert single_plan["total_points"] == 102

    def test_multi_method_items_execute_one_method(self, single_plan):
        items = _by_name(single_plan)
        assert items["dc_gain"]["methods"] == ["dc_two_point"]
        assert items["dc_gain"]["method"] == "dc_two_point"
        assert items["dc_gain"]["primary"] == "dc_two_point"
        assert items["dc_offset"]["methods"] == ["raw_lsq"]
        assert items["dc_offset"]["method"] == "raw_lsq"
        assert items["dc_offset"]["primary"] == "raw_lsq"
        assert items["timebase_error"]["methods"] == ["waveform_fit"]
        assert items["timebase_error"]["method"] == "waveform_fit"
        assert items["timebase_error"]["primary"] is None

    def test_trial_scheme_keeps_all_methods(self, plan):
        items = _by_name(plan)
        assert len(items["dc_gain"]["methods"]) == 3
        assert items["dc_gain"]["method"] is None
        assert len(items["timebase_error"]["methods"]) == 2

    def test_timebase_and_delta_t_use_three_scales(self, single_plan):
        items = _by_name(single_plan)
        timebase = [
            p["timebase_s_per_div"]
            for p in items["timebase_error"]["points"]
            if p["channel"] == "1"
        ]
        delta_t = [
            p["timebase_s_per_div"] for p in items["delta_t"]["points"] if p["channel"] == "1"
        ]
        assert timebase == [1e-8, 1e-5, 1e-2]
        assert delta_t == [1e-8, 1e-5, 1e-2]
        assert items["delta_t"]["skipped"] == []

    def test_two_point_keeps_50_ohm_1v_per_div(self, single_plan):
        points = [p for p in _by_name(single_plan)["dc_gain"]["points"] if p["channel"] == "1"]
        fifty = {p["scale"] for p in points if p["impedance"] == "50"}
        assert fifty == {0.01, 0.1, 1.0}, "1 V/div 在 50 Ω 下应可测（±3.2 V 直流）"
        skipped = [s for s in _by_name(single_plan)["dc_gain"]["skipped"] if s["channel"] == "1"]
        assert len(skipped) == 1
        assert skipped[0]["scale"] == 10.0
        assert "垂直挡位上限" in skipped[0]["reason"], "50 Ω 10 V/div 应按硬件上限跳过"


class TestSchemeSelection:
    def test_method_subset_does_not_change_points(self, configs):
        scheme = copy.deepcopy(configs[1])
        scheme["items"]["dc_gain"]["methods"] = ["square_amplitude"]
        scheme["items"]["dc_gain"]["primary"] = "square_amplitude"
        plan = _build(configs, scheme=scheme)
        item = _by_name(plan)["dc_gain"]
        assert item["methods"] == ["square_amplitude"]
        assert len(item["points"]) == 12

    def test_square_method_still_hits_50_ohm_vpp_limit(self, configs):
        """方波法在 50 Ω 1 V/div 需要 6.4 Vpp，超过 9500B 的 5 Vpp，应跳过。"""
        scheme = copy.deepcopy(_load("jjf1057_2026_single.json", "schemes"))
        scheme["items"]["dc_gain"]["method"] = "square_amplitude"
        plan = _build(configs, scheme=scheme)
        item = _by_name(plan)["dc_gain"]
        skipped = [s for s in item["skipped"] if s["channel"] == "1"]
        assert any(s["scale"] == 1.0 and "6.4 Vpp" in s["reason"] for s in skipped)
        fifty = {
            p["scale"] for p in item["points"] if p["channel"] == "1" and p["impedance"] == "50"
        }
        assert fifty == {0.01, 0.1}

    def test_item_not_in_scheme_is_reported(self, configs):
        scheme = copy.deepcopy(configs[1])
        del scheme["items"]["dc_offset"]
        plan = _build(configs, scheme=scheme)
        item = _by_name(plan)["dc_offset"]
        assert item["status"] == "not_in_scheme"
        assert item["points"] == []
        assert any("方案未列入" in s["reason"] for s in item["skipped"])

    def test_plan_reports_scheme_name(self, plan):
        assert plan["scheme_name"] == "JJF 1057-2026 试验校准方案"
        assert plan["scheme_spec"] == "jjf1057_2026"


class TestPlanCommand:
    def test_plan_runs_offline(self):
        result = CliRunner().invoke(cli, ["plan"])
        assert result.exit_code == 0, result.output
        assert "102" in result.output
        assert "JJF 1057-2026" in result.output
        assert "MDO3052" in result.output

    def test_plan_shows_methods(self):
        result = CliRunner().invoke(cli, ["plan"])
        assert result.exit_code == 0, result.output
        assert "直流两点" in result.output
        assert "波形拟合" in result.output
        assert "3法" not in result.output

    def test_plan_trial_shows_all_methods(self):
        result = CliRunner().invoke(cli, ["plan", "--scheme", "jjf1057_2026"])
        assert result.exit_code == 0, result.output
        assert "3法" in result.output

    def test_plan_writes_json(self, tmp_path):
        out = tmp_path / "plan.json"
        result = CliRunner().invoke(cli, ["plan", "--json", str(out)])
        assert result.exit_code == 0, result.output
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["total_points"] == 102
        assert len(data["items"]) == 12
        assert data["scheme_name"] == "JJF 1057-2026 单方法校准方案"

    def test_plan_accepts_characteristics_name(self):
        result = CliRunner().invoke(cli, ["plan", "--characteristics", "tektronix_mdo3032"])
        assert result.exit_code == 0, result.output
        assert "MDO3032" in result.output

    def test_plan_rejects_unknown_scheme(self):
        result = CliRunner().invoke(cli, ["plan", "--scheme", "no_such_scheme"])
        assert result.exit_code == 2
        assert "找不到方案配置文件" in result.output

    def test_plan_rejects_unknown_characteristics(self):
        result = CliRunner().invoke(cli, ["plan", "--characteristics", "no_such_model"])
        assert result.exit_code == 2
        assert "找不到特征文件" in result.output

    def test_old_spec_option_is_gone(self):
        result = CliRunner().invoke(cli, ["plan", "--spec", "jjf1057_2026"])
        assert result.exit_code != 0
        assert "No such option" in result.output or "no such option" in result.output


class TestRunnerAvailability:
    def test_pending_items_reports_unimplemented(self):
        from osccal.measure.all import pending_items

        assert pending_items(["dc_gain", "dc_offset"]) == []
        # 未知项目也会被列为"尚未实现"，不会静默忽略
        assert pending_items(["dc_gain", "not_an_item"]) == ["not_an_item"]

    def test_calibrate_help_drops_legacy_options(self):
        result = CliRunner().invoke(cli, ["calibrate", "--help"])
        assert result.exit_code == 0
        assert "--bandwidth" not in result.output
        assert "--bd-step" not in result.output
        assert "--items" in result.output
        assert "--scheme" in result.output
        assert "--characteristics" in result.output
