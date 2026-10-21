"""校准流程编排（cli.calibrate）的端到端用例：假仪器 + 打桩测量。

守护三件事：规范点表被真正使用、记录写入 points_plan/spec、已实现项目能跑完。
"""

import json
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

import osccal.cli as cli_mod
import osccal.core.storage as storage_mod
import osccal.measure.base as base_mod
from osccal.cli import cli

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeInst:
    """模拟 pyvisa 仪器。"""

    def __init__(self, idn: str):
        self.idn = idn
        self.written: list[str] = []

    def write(self, cmd: str):
        self.written.append(cmd)

    def query(self, cmd: str) -> str:
        self.written.append(cmd)
        if cmd.strip() == "*IDN?":
            return self.idn + "\n"
        return "0"


@pytest.fixture
def fake_env(monkeypatch) -> dict:
    saved: dict = {}

    def fake_connect(resource: str):
        if "19" in resource:
            idn = {"manufacturer": "FLUKE", "model": "9500B", "serial": "S1", "firmware": "1.0"}
        else:
            idn = {
                "manufacturer": "TEKTRONIX",
                "model": "MDO3052",
                "serial": "S2",
                "firmware": "1.0",
            }
        text = ",".join([idn["manufacturer"], idn["model"], idn["serial"], idn["firmware"]])
        return FakeInst(text), idn

    def fake_save(results, metadata, *, filepath=None):
        saved["results"] = results
        saved["metadata"] = metadata
        return ""

    monkeypatch.setattr(cli_mod, "connect_visa", fake_connect)
    monkeypatch.setattr(
        cli_mod, "list_visa_resources", lambda: ["GPIB0::19::INSTR", "GPIB0::10::INSTR"]
    )
    # 测量值统一返回 0.64 V：dc_gain 的标准值也是 0.64 Vpp → G = 1
    monkeypatch.setattr(base_mod, "read_measurement", lambda *args, **kwargs: 0.64)
    monkeypatch.setattr(storage_mod, "save_calibration_data", fake_save)
    monkeypatch.setattr(time, "sleep", lambda *_args, **_kwargs: None)
    return saved


def _args(*extra: str) -> list[str]:
    return [
        "calibrate",
        "--osc",
        str(PROJECT_ROOT / "commands" / "tektronix_mdo.json"),
        "--profile",
        str(PROJECT_ROOT / "profiles" / "tektronix_mdo3052.json"),
        "--calibrator",
        str(PROJECT_ROOT / "calibrators" / "fluke_9500b.json"),
        "--spec",
        "jjf1057_2026",
        "--probe",
        "9530",
        "--resource-osc",
        "GPIB0::10::INSTR",
        "--resource-cal",
        "GPIB0::19::INSTR",
        *extra,
    ]


class TestCalibrateFlow:
    def test_runs_implemented_item_with_spec_points(self, fake_env):
        result = CliRunner().invoke(cli, _args("--channel", "1", "--items", "dc_gain"), input="n\n")
        assert result.exit_code == 0, result.output

        metadata = fake_env["metadata"]
        assert metadata["spec"]["spec_code"] == "JJF 1057-2026"
        assert metadata["spec"]["deviations"], "记录应包含偏离声明"
        # 4 档 × 1 MΩ + 2 档（≤100 mV） × 50 Ω = 6 点/通道
        assert metadata["points_plan"]["1"]["dc_gain"] == 6
        assert metadata["bandwidth_hz"] == pytest.approx(5e8)
        assert "dc_gain" in fake_env["results"]
        assert len(fake_env["results"]["dc_gain"]) == 6
        assert metadata["status"] == "completed"

    def test_rejects_unimplemented_item(self, fake_env):
        result = CliRunner().invoke(cli, _args("--channel", "1", "--items", "enob"), input="n\n")
        assert result.exit_code == 2
        assert "尚未实现" in result.output

    def test_records_skipped_points(self, fake_env):
        result = CliRunner().invoke(cli, _args("--channel", "1", "--items", "dc_gain"), input="n\n")
        assert result.exit_code == 0, result.output
        skipped = fake_env["metadata"]["skipped_points"]
        assert skipped, "50 Ω 超限的点应写入 skipped_points"
        assert all("50" in note["reason"] for note in skipped)

    def test_two_items_share_one_round(self, fake_env):
        result = CliRunner().invoke(
            cli,
            _args("--channel", "1", "--items", "dc_gain,dc_offset"),
            input="n\n",
        )
        assert result.exit_code == 0, result.output
        assert set(fake_env["results"]) == {"dc_gain", "dc_offset"}
        plan = fake_env["metadata"]["points_plan"]["1"]
        assert plan["dc_gain"] == 6
        assert plan["dc_offset"] == 4

    def test_json_record_is_serialisable(self, fake_env):
        result = CliRunner().invoke(cli, _args("--channel", "1", "--items", "dc_gain"), input="n\n")
        assert result.exit_code == 0, result.output
        json.dumps(fake_env["metadata"], ensure_ascii=False)
        json.dumps(fake_env["results"], ensure_ascii=False)

    def test_runs_waveform_free_item(self, fake_env):
        """Δt 只用标量周期测量，走通即可（方波激励限幅已在点表里体现）。"""
        result = CliRunner().invoke(cli, _args("--channel", "1", "--items", "delta_t"), input="n\n")
        assert result.exit_code == 0, result.output
        assert fake_env["metadata"]["points_plan"]["1"]["delta_t"] == 2
        assert len(fake_env["results"]["delta_t"]) == 2
