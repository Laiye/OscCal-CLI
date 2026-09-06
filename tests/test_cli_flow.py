"""CLI 校准流程测试：用 mock 仪器走通 cli.py 的手动/自动模式完整流程。

覆盖项6重构后的关键路径：配置加载 → 连接（VISA 资源选择）→ 通道/项目选择
→ 校准执行 → 数据保存 → 连接释放，以及 --log-scpi 的 SCPI 日志输出。
"""

import sys
import time
import types

import pytest
from click.testing import CliRunner

from osccal.cli import cli


class FakeInst:
    """模拟 pyvisa 仪器：按预设返回 *IDN? 与测量值，记录指令。"""

    def __init__(
        self,
        idn: str = "TEKTRONIX,MDO34,SIM001,v1.0",
        default_response: str = ":MEASUREMENT:IMMED:VALUE 1.0E+0",
    ):
        self.idn = idn
        self.default_response = default_response
        self.timeout = None
        self.written: list[str] = []

    def write(self, cmd: str):
        self.written.append(cmd)
        return None

    def query(self, cmd: str) -> str:
        self.written.append(cmd)
        c = cmd.strip()
        if c == "*IDN?":
            return self.idn + "\n"
        if "ROUT:FITT?" in c.upper():
            return "9560\n"
        return self.default_response

    def close(self):
        pass


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda x: None)


@pytest.fixture
def fake_connections(monkeypatch):
    """把 cli 模块的连接函数替换为 FakeInst。"""
    import osccal.cli as cli_mod

    def fake_connect_visa(resource):
        idn = "TEKTRONIX,MDO34,SIM001,v1.0"
        return FakeInst(idn), {
            "manufacturer": "TEKTRONIX",
            "model": "MDO34",
            "serial": "SIM001",
            "firmware": "v1.0",
        }

    monkeypatch.setattr(cli_mod, "connect_visa", fake_connect_visa)
    monkeypatch.setattr(
        cli_mod, "list_visa_resources", lambda: ["GPIB0::19::INSTR", "GPIB0::10::INSTR"]
    )
    return cli_mod


@pytest.fixture
def no_save(monkeypatch):
    """拦截数据保存，避免测试写入 data/ 目录。"""
    saved: dict = {}

    def fake_save(results, metadata):
        saved["results"] = results
        saved["metadata"] = metadata
        return ""

    import osccal.core.storage as storage_mod

    monkeypatch.setattr(storage_mod, "save_calibration_data", fake_save)
    return saved


def test_calibrate_manual_flow(fake_connections, no_sleep, no_save):
    """手动模式：配置选择 → 连接 → 幅度校准 → 保存 → 退出。"""
    runner = CliRunner()
    # 输入: 探头(0) 指令集(0) 特征(0) 通道(0) 项目(1=amp) 校准仪资源(0) 示波器资源(1) 是否继续(n)
    result = runner.invoke(cli, ["calibrate", "--log-scpi"], input="0\n0\n0\n0\n1\n0\n1\nn\n")
    assert result.exit_code == 0, result.output
    assert "校准完成" in result.output
    assert "amp" in no_save["results"], "应保存 amp 校准结果"
    # --log-scpi 应输出指令日志
    assert "SCPI 指令日志" in result.output


def test_calibrate_manual_flags(fake_connections, no_sleep, no_save):
    """手动模式全命令行参数：无需任何交互输入。"""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "calibrate",
            "--osc",
            "commands/tektronix_mdo3.json",
            "--profile",
            "profiles/tektronix_mdo34.json",
            "--calibrator",
            "calibrators/fluke_9500b.json",
            "--probe",
            "9560",
            "--channel",
            "1",
            "--items",
            "transient",
            "--resource-cal",
            "GPIB0::19::INSTR",
            "--resource-osc",
            "GPIB0::10::INSTR",
        ],
        input="n\n",
    )
    assert result.exit_code == 0, result.output
    assert "transient" in no_save["results"]
    assert no_save["metadata"]["probe"] == "9560"
    assert no_save["metadata"]["channel"] == "1"


def test_calibrate_auto_flow(fake_connections, no_sleep, no_save, monkeypatch):
    """自动模式：模拟 VISA 扫描识别 FLUKE 校准仪 + 泰克示波器。"""
    # 注入假的 pyvisa 模块
    fake_pyvisa = types.ModuleType("pyvisa")

    class FakeRM:
        def __init__(self):
            pass

        def list_resources(self):
            return ["GPIB0::19::INSTR", "GPIB0::10::INSTR"]

        def open_resource(self, resource):
            if "19" in resource:
                return FakeInst(idn="FLUKE,9500B,471475627,4.12")
            return FakeInst(idn="TEKTRONIX,MDO34,C020687,CF:91.1CT")

        def close(self):
            pass

    fake_pyvisa.ResourceManager = FakeRM
    monkeypatch.setitem(sys.modules, "pyvisa", fake_pyvisa)

    runner = CliRunner()
    # 输入: 确认执行(y) 通道(0) 项目(1=amp) 是否继续(n)
    result = runner.invoke(cli, ["calibrate", "--auto"], input="y\n0\n1\nn\n")
    assert result.exit_code == 0, result.output
    assert "自动识别探头" in result.output
    assert "amp" in no_save["results"]


def test_calibrate_failure_counted(fake_connections, no_sleep, no_save, monkeypatch):
    """SCPI 失败统计：仪器抛异常时应累计失败并在元数据中记录。"""
    import osccal.cli as cli_mod
    from osccal.core import scpi_trace

    scpi_trace.reset()

    def broken_connect_visa(resource):
        inst = FakeInst()

        def bad_query(cmd):
            raise ConnectionError("模拟通信故障")

        inst.query = bad_query
        return inst, {"manufacturer": "TEKTRONIX", "model": "MDO34", "serial": "S", "firmware": "v"}

    monkeypatch.setattr(cli_mod, "connect_visa", broken_connect_visa)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "calibrate",
            "--osc",
            "commands/tektronix_mdo3.json",
            "--profile",
            "profiles/tektronix_mdo34.json",
            "--calibrator",
            "calibrators/fluke_9500b.json",
            "--probe",
            "9560",
            "--channel",
            "1",
            "--items",
            "amp",
            "--resource-cal",
            "GPIB0::19::INSTR",
            "--resource-osc",
            "GPIB0::10::INSTR",
        ],
        input="n\n",
    )
    assert result.exit_code == 0
    assert scpi_trace.failure_count() > 0, "通信失败应被统计"
    assert no_save["metadata"]["scpi_errors"] > 0, "元数据应记录 scpi_errors"
