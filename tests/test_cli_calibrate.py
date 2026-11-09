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

    def fake_save(results, metadata, *, filepath=None, quiet=False):
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
        "--characteristics",
        str(PROJECT_ROOT / "characteristics" / "tektronix_mdo3052.json"),
        "--calibrator",
        str(PROJECT_ROOT / "calibrators" / "fluke_9500b.json"),
        "--scheme",
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
        result = CliRunner().invoke(
            cli, _args("--channel", "1", "--items", "not_an_item"), input="n\n"
        )
        assert result.exit_code == 2
        assert "尚未实现" in result.output

    def test_records_skipped_points(self, fake_env, tmp_path):
        """显式点表默认不再产生跳过；若显式写了硬件不支持的 50 Ω 10 V/div，仍要记录。"""
        scheme = json.loads(
            (PROJECT_ROOT / "schemes" / "jjf1057_2026.json").read_text(encoding="utf-8")
        )
        scheme["items"]["dc_gain"]["points"]["by_impedance"]["50"]["scales_v_per_div"].append(10.0)
        scheme_path = tmp_path / "dc_gain_skip.json"
        scheme_path.write_text(json.dumps(scheme, ensure_ascii=False), encoding="utf-8")

        args = _args("--channel", "1", "--items", "dc_gain")
        index = args.index("--scheme")
        del args[index : index + 2]
        args.extend(["--scheme", str(scheme_path)])

        result = CliRunner().invoke(cli, args, input="n\n")
        assert result.exit_code == 0, result.output
        skipped = fake_env["metadata"]["skipped_points"]
        assert skipped, "显式写入的 50 Ω 10 V/div 应写入 skipped_points"
        assert any("50" in note["reason"] and "垂直挡位上限" in note["reason"] for note in skipped)

    def test_two_items_share_one_round(self, fake_env):
        result = CliRunner().invoke(
            cli,
            _args("--channel", "1", "--items", "dc_gain,delta_v"),
            input="n\n",
        )
        assert result.exit_code == 0, result.output
        assert set(fake_env["results"]) == {"dc_gain", "delta_v"}
        plan = fake_env["metadata"]["points_plan"]["1"]
        assert plan["dc_gain"] == 6
        assert plan["delta_v"] == 6

    def test_json_record_is_serialisable(self, fake_env):
        result = CliRunner().invoke(cli, _args("--channel", "1", "--items", "dc_gain"), input="n\n")
        assert result.exit_code == 0, result.output
        json.dumps(fake_env["metadata"], ensure_ascii=False)
        json.dumps(fake_env["results"], ensure_ascii=False)

    def test_runs_waveform_free_item(self, fake_env):
        """Δt 只用标量周期测量，走通即可（MARK 时标三档均已在点表中）。"""
        result = CliRunner().invoke(cli, _args("--channel", "1", "--items", "delta_t"), input="n\n")
        assert result.exit_code == 0, result.output
        assert fake_env["metadata"]["points_plan"]["1"]["delta_t"] == 4
        assert len(fake_env["results"]["delta_t"]) == 4

    def test_scheme_defaults_to_shipped_scheme(self, fake_env):
        """省略 --scheme 时必须按内置方案执行，而不是解析出空点表空跑。"""
        args = _args("--channel", "1", "--items", "dc_gain")
        index = args.index("--scheme")
        del args[index : index + 2]
        result = CliRunner().invoke(cli, args, input="n\n")
        assert result.exit_code == 0, result.output
        assert fake_env["metadata"]["spec"]["spec_code"] == "JJF 1057-2026"
        assert fake_env["metadata"]["scheme"]["name"] == "JJF 1057-2026 单方法校准方案"
        # 单方法方案用直流两点法：4 档 1 MΩ + 3 档 50 Ω（1 V/div 可测）= 7 点
        assert fake_env["metadata"]["points_plan"]["1"]["dc_gain"] == 7

    def test_rejects_item_missing_from_scheme(self, fake_env, tmp_path):
        """所选项目不在方案里时必须中止，不能静默跑 0 个点。"""
        scheme = json.loads(
            (PROJECT_ROOT / "schemes" / "jjf1057_2026.json").read_text(encoding="utf-8")
        )
        del scheme["items"]["enob"]
        scheme_path = tmp_path / "without_enob.json"
        scheme_path.write_text(json.dumps(scheme, ensure_ascii=False), encoding="utf-8")

        args = _args("--channel", "1", "--items", "enob")
        index = args.index("--scheme")
        del args[index : index + 2]
        args.extend(["--scheme", str(scheme_path)])

        result = CliRunner().invoke(cli, args, input="n\n")
        assert result.exit_code == 2
        assert "不在所选方案中" in result.output

    def test_one_failed_item_does_not_stop_the_round(self, fake_env, monkeypatch):
        """单项失败只记录该项，后续项目继续执行，本轮状态为 completed_with_errors。"""
        from osccal.core.comm import ScpiError
        from osccal.measure import registry

        class BoomRunner:
            def __init__(self, *args, **kwargs):
                self.rows: list = []

            def run(self):
                raise ScpiError("模拟项目失败")

            def get_results(self):
                return self.rows

        monkeypatch.setitem(registry.RUNNERS, "dc_gain", BoomRunner)
        result = CliRunner().invoke(
            cli,
            _args("--channel", "1", "--items", "dc_gain,delta_v"),
            input="n\n",
        )
        assert result.exit_code == 1, result.output
        metadata = fake_env["metadata"]
        assert metadata["status"] == "completed_with_errors"
        assert metadata["item_status"]["dc_gain"] == "failed"
        assert metadata["failures"]["dc_gain"]["type"] == "ScpiError"
        assert len(fake_env["results"]["delta_v"]) == 6, "后续项目必须继续执行"
