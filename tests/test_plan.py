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


def _by_name(plan: dict) -> dict[str, dict]:
    return {item["name"]: item for item in plan["items"]}


class TestPlanContent:
    def test_total_points(self, plan):
        # 4 + 12 + 14 + 36 + 4 + 4 + 8 + 12 + 4 + 2 = 100
        # Δt 只有 2 点/通道：方波激励受 9500B 10 Hz~10 kHz 限制，快时基不可行
        # 时基挡位按实机能力收敛到 10 ms/div（去掉 100 ms/div）
        assert plan["total_points"] == 100

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
            ("delta_t", 4),
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

    def test_delta_t_skips_fast_timebases(self, plan):
        """Δt 用方波激励，9500B 方波只到 10 kHz，最快的两个时基挡位会被跳过。"""
        item = _by_name(plan)["delta_t"]
        assert len(item["points"]) == 4
        reasons = " ".join(skip["reason"] for skip in item["skipped"])
        assert "超出输出上限" in reasons

    def test_timebase_error_keeps_all_points(self, plan):
        """时基误差用正弦激励，0.1 Hz~600 MHz 覆盖全部 4 个时基挡位。"""
        assert len(_by_name(plan)["timebase_error"]["points"]) == 8
        assert _by_name(plan)["timebase_error"]["skipped"] == []

    def test_unknown_probe_marks_rise_time_skipped(self, configs):
        plan = _build(configs, probe="9999", channels=["1"])
        item = _by_name(plan)["rise_time"]
        assert item["points"] == []
        assert any("edge_rise_times" in s["reason"] for s in item["skipped"])


class TestSchemeSelection:
    def test_method_subset_does_not_change_points(self, configs):
        scheme = copy.deepcopy(configs[1])
        scheme["items"]["dc_gain"]["methods"] = ["square_amplitude"]
        scheme["items"]["dc_gain"]["primary"] = "square_amplitude"
        plan = _build(configs, scheme=scheme)
        item = _by_name(plan)["dc_gain"]
        assert item["methods"] == ["square_amplitude"]
        assert len(item["points"]) == 12

    def test_item_not_in_scheme_is_reported(self, configs):
        scheme = copy.deepcopy(configs[1])
        del scheme["items"]["dc_offset"]
        plan = _build(configs, scheme=scheme)
        item = _by_name(plan)["dc_offset"]
        assert item["status"] == "not_in_scheme"
        assert item["points"] == []
        assert any("方案未列入" in s["reason"] for s in item["skipped"])

    def test_plan_reports_scheme_name(self, plan):
        assert plan["scheme_name"] == "JJF 1057-2026 默认校准方案"
        assert plan["scheme_spec"] == "jjf1057_2026"


class TestPlanCommand:
    def test_plan_runs_offline(self):
        result = CliRunner().invoke(cli, ["plan"])
        assert result.exit_code == 0, result.output
        assert "100" in result.output
        assert "JJF 1057-2026" in result.output
        assert "MDO3052" in result.output

    def test_plan_shows_methods(self):
        result = CliRunner().invoke(cli, ["plan"])
        assert result.exit_code == 0, result.output
        assert "3法" in result.output
        assert "方波" in result.output

    def test_plan_writes_json(self, tmp_path):
        out = tmp_path / "plan.json"
        result = CliRunner().invoke(cli, ["plan", "--json", str(out)])
        assert result.exit_code == 0, result.output
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["total_points"] == 100
        assert len(data["items"]) == 12
        assert data["scheme_name"] == "JJF 1057-2026 默认校准方案"

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
