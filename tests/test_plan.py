"""校准点解析器（core/points.py）与 `osccal plan` 的守护用例。"""

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
def configs() -> tuple[dict, dict, dict]:
    return (
        _load("jjf1057_2026.json", "specs"),
        _load("tektronix_mdo3052.json", "profiles"),
        _load("fluke_9500b.json", "calibrators"),
    )


@pytest.fixture(scope="module")
def plan(configs) -> dict:
    spec, profile, calibrator = configs
    return build_plan(spec, profile, calibrator, "9530", ["1", "2"])


def _by_name(plan: dict) -> dict[str, dict]:
    return {item["name"]: item for item in plan["items"]}


class TestPlanContent:
    def test_total_points(self, plan):
        # 4 + 12 + 8 + 18 + 2 + 4 + 8 + 8 + 4 + 2 = 70
        # Δt 只有 2 点/通道：方波激励受 9500B 10 Hz~10 kHz 限制，快时基不可行
        # 时基挡位按实机能力收敛到 10 ms/div（去掉 100 ms/div）
        assert plan["total_points"] == 70

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("input_impedance", 4),
            ("dc_gain", 12),
            ("dc_offset", 8),
            ("freq_response_bandwidth", 18),
            ("enob", 2),
            ("rise_time", 4),
            ("timebase_error", 8),
            ("delta_v", 8),
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

    def test_impedance_tolerance_comes_from_spec(self, plan):
        points = _by_name(plan)["input_impedance"]["points"]
        tolerances = {p["impedance"]: p["tolerance_pct"] for p in points if p["channel"] == "1"}
        assert tolerances == {"1M": 0.5, "50": 1.0}

    def test_dc_gain_skips_50_ohm_above_limit(self, plan):
        skipped = _by_name(plan)["dc_gain"]["skipped"]
        assert len(skipped) == 4
        assert all(item["impedance"] == "50" for item in skipped)
        assert all("上限" in item["reason"] for item in skipped)

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
            if p["channel"] == "1"
        ]
        assert freqs[0] == pytest.approx(50000)
        assert freqs[-1] == pytest.approx(5e8)
        assert len(freqs) == 9

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
        spec, profile, calibrator = configs
        plan = build_plan(spec, profile, calibrator, "9999", ["1"])
        item = _by_name(plan)["rise_time"]
        assert item["points"] == []
        assert any("edge_rise_times" in s["reason"] for s in item["skipped"])


class TestPlanCommand:
    def test_plan_runs_offline(self):
        result = CliRunner().invoke(cli, ["plan"])
        assert result.exit_code == 0, result.output
        assert "70" in result.output
        assert "JJF 1057-2026" in result.output

    def test_plan_writes_json(self, tmp_path):
        out = tmp_path / "plan.json"
        result = CliRunner().invoke(cli, ["plan", "--json", str(out)])
        assert result.exit_code == 0, result.output
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["total_points"] == 70
        assert len(data["items"]) == 12

    def test_plan_rejects_unknown_spec(self):
        result = CliRunner().invoke(cli, ["plan", "--spec", "no_such_spec"])
        assert result.exit_code == 2
        assert "找不到规范配置文件" in result.output


class TestRunnerAvailability:
    def test_pending_items_reports_unimplemented(self):
        from osccal.measure.all import pending_items

        assert pending_items(["dc_gain", "dc_offset"]) == []
        # 未知项目也会被列为"尚未实现"，不会静默忽略
        assert pending_items(["dc_gain", "not_an_item"]) == ["not_an_item"]

    def test_calibrate_help_drops_legacy_options(self):
        result = CliRunner().invoke(cli, ["calibrate", "--help"])
        assert result.exit_code == 0
        # 标称带宽与扫描步进改由 Profile 的 bandwidth_hz 与规范比值决定
        assert "--bandwidth" not in result.output
        assert "--bd-step" not in result.output
        assert "--items" in result.output
        assert "--spec" in result.output
