"""CLI 校准流程测试：用 mock 仪器走通 cli.py 的手动/自动模式完整流程。

覆盖项6重构后的关键路径：配置加载 → 连接（VISA 资源选择）→ 通道/项目选择
→ 校准执行 → 数据保存 → 连接释放，以及 --log-scpi 的 SCPI 日志输出。
"""

import copy
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
        is_cal = "19" in resource
        mfr, model = ("FLUKE", "9500B") if is_cal else ("TEKTRONIX", "MDO34")
        idn = f"{mfr},{model},SIM001,v1.0"
        return FakeInst(idn), {
            "manufacturer": mfr,
            "model": model,
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

    def fake_save(results, metadata, *, filepath=None):
        saved["results"] = copy.deepcopy(results)
        saved["metadata"] = copy.deepcopy(metadata)
        return ""

    import osccal.core.storage as storage_mod

    monkeypatch.setattr(storage_mod, "save_calibration_data", fake_save)
    return saved


def test_calibrate_manual_flow(fake_connections, no_sleep, no_save):
    """手动模式：配置选择 → 连接 → 幅度校准 → 保存 → 退出。"""
    runner = CliRunner()
    # 输入: 探头、MDO3 指令集、MDO34 特征、通道、校准仪、示波器、幅度项目、退出。
    result = runner.invoke(cli, ["calibrate", "--log-scpi"], input="0\n3\n4\n0\n0\n1\n1\nn\n")
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
    # P1 回归：元数据应存配置文件名（basename），而非 name/series 字段
    assert no_save["metadata"]["commands_file"] == "tektronix_mdo3.json"
    assert no_save["metadata"]["profile_file"] == "tektronix_mdo34.json"
    assert no_save["metadata"]["calibrator_file"] == "fluke_9500b.json"


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
    result = runner.invoke(
        cli,
        ["calibrate", "--auto", "--calibrator", "calibrators/fluke_9500b.json"],
        input="y\n0\n1\nn\n",
    )
    assert result.exit_code == 0, result.output
    assert "自动识别探头" in result.output
    assert "amp" in no_save["results"]
    # P1 回归：auto 模式应透传 --calibrator 并记录其文件名
    assert no_save["metadata"]["calibrator_file"] == "fluke_9500b.json"


class TestParseSocketAddr:
    """P0 回归：socket 地址解析应对非法输入给出友好错误而非抛异常。"""

    @pytest.mark.parametrize(
        "addr,expected",
        [
            ("192.168.1.100:5025", ("192.168.1.100", 5025)),
            ("[::1]:5025", ("[::1]", 5025)),
        ],
    )
    def test_valid(self, addr, expected):
        from osccal.cli import _parse_socket_addr

        assert _parse_socket_addr(addr) == expected

    @pytest.mark.parametrize(
        "addr", ["192.168.1.100", "host:", ":5025", "host:abc", "host:0", "host:70000", ""]
    )
    def test_invalid_returns_none(self, addr):
        from osccal.cli import _parse_socket_addr

        assert _parse_socket_addr(addr) is None

    def test_connect_oscilloscope_invalid_socket(self, monkeypatch):
        import osccal.cli as cli_mod

        def fail_connect(*args, **kwargs):
            raise AssertionError("非法地址不应尝试连接")

        monkeypatch.setattr(cli_mod, "connect_socket", fail_connect)
        result = cli_mod._connect_oscilloscope({"type": "socket"}, None, "bad-addr", [])
        assert result == (None, {})


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
        return inst, {
            "manufacturer": "FLUKE" if "19" in resource else "TEKTRONIX",
            "model": "9500B" if "19" in resource else "MDO34",
            "serial": "S",
            "firmware": "v",
        }

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
    assert result.exit_code == 1
    assert scpi_trace.failure_count() > 0, "通信失败应被统计"
    assert no_save["metadata"]["scpi_errors"] > 0, "元数据应记录 scpi_errors"


@pytest.mark.parametrize("items", ["amp", "all"])
def test_interrupt_turns_output_off_before_close(
    fake_connections, no_sleep, no_save, monkeypatch, items
):
    """单项目和全项目中断后都应先关闭输出，再释放连接。"""
    from osccal.measure.amp import AmpCalibrator

    events = []

    class RecordingInst(FakeInst):
        def write(self, cmd):
            events.append(cmd)
            return super().write(cmd)

    monkeypatch.setattr(
        fake_connections,
        "connect_visa",
        lambda resource: (
            RecordingInst(),
            {
                "manufacturer": "FLUKE" if "19" in resource else "TEKTRONIX",
                "model": "9500B" if "19" in resource else "MDO34",
            },
        ),
    )
    monkeypatch.setattr(
        fake_connections, "close_all_connections", lambda: events.append("关闭连接")
    )

    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(AmpCalibrator, "_read_meas", interrupt)
    result = CliRunner().invoke(
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
            items,
            "--bandwidth",
            "100",
            "--bd-step",
            "20",
            "--resource-cal",
            "GPIB0::19::INSTR",
            "--resource-osc",
            "GPIB0::10::INSTR",
        ],
    )
    assert result.exit_code == 130
    assert any("ON" in event and "OUTP" in event.upper() for event in events)
    assert "OFF" in events[-2] and "OUTP" in events[-2].upper()
    assert events[-1] == "关闭连接"
    assert no_save["metadata"]["status"] == "interrupted"
    assert no_save["metadata"]["item_status"]["amp"] == "interrupted"


def _recording_args(items, channel="1"):
    return [
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
        channel,
        "--items",
        items,
        "--bandwidth",
        "100",
        "--bd-step",
        "20",
        "--resource-cal",
        "GPIB0::19::INSTR",
        "--resource-osc",
        "GPIB0::10::INSTR",
    ]


@pytest.mark.parametrize("items", ["amp,dc_gain", "all"])
@pytest.mark.parametrize("termination", ["interrupt", "abort", "shutdown"])
def test_real_checkpoint_survives_later_interrupt(
    fake_connections, no_sleep, monkeypatch, tmp_path, items, termination
):
    """必须实际读写 JSON，不能只验证传给保存函数的参数。"""
    import click

    from osccal.core import scpi_trace, storage
    from osccal.measure.amp import AmpCalibrator
    from osccal.measure.base import OutputShutdownError
    from osccal.measure.dc_gain import DcGainCalibrator

    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    error_class = {
        "interrupt": KeyboardInterrupt,
        "abort": click.Abort,
        "shutdown": OutputShutdownError,
    }[termination]
    expected_status = "failed" if termination == "shutdown" else "interrupted"

    def complete(self):
        self.results = [{"index": 1, "measured": 0.6}]

    def interrupt(self):
        stage = storage.load_calibration_data(storage.get_latest_calibration_file())
        assert stage["results"]["amp"][0]["measured"] == 0.6
        assert stage["metadata"]["status"] == "in_progress"
        self.results = [{"index": 1, "error": 0.1}]
        scpi_trace.record_failure()
        raise error_class("模拟终止")

    monkeypatch.setattr(AmpCalibrator, "run", complete)
    monkeypatch.setattr(DcGainCalibrator, "run", interrupt)
    result = CliRunner().invoke(cli, _recording_args(items))
    assert result.exit_code == (1 if termination == "shutdown" else 130)
    assert len(storage.list_calibration_files()) == 1
    saved = storage.load_calibration_data(storage.get_latest_calibration_file())
    assert saved["results"]["amp"][0]["measured"] == 0.6
    assert saved["results"]["dc_gain"] == [{"index": 1, "error": 0.1}]
    metadata = saved["metadata"]
    assert metadata["status"] == expected_status
    assert metadata["scpi_errors"] == 1
    assert metadata["item_status"] == {"amp": "completed", "dc_gain": expected_status}
    assert metadata["failures"]["dc_gain"]["type"] == error_class.__name__
    assert metadata["failures"]["dc_gain"]["message"] == "模拟终止"
    snapshot = metadata["configurations"]["profile"]
    assert snapshot == storage.configuration_snapshot(snapshot["data"])
    assert snapshot["data"]["bandwidth"] == 100e6


def test_multi_channel_checkpoint_survives_interrupt(
    fake_connections, no_sleep, monkeypatch, tmp_path
):
    from osccal.core import storage
    from osccal.measure.amp import AmpCalibrator

    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))

    def run(self):
        if self.channel == "2":
            raise KeyboardInterrupt
        self.results = [{"channel": self.channel, "measured": 1}]

    monkeypatch.setattr(AmpCalibrator, "run", run)
    result = CliRunner().invoke(cli, _recording_args("amp", "1,2"), input="\n\n")
    assert result.exit_code != 0
    saved = storage.load_calibration_data(storage.get_latest_calibration_file())
    assert saved["results"]["amp_ch1"] == [{"channel": "1", "measured": 1}]
    assert saved["metadata"]["item_status"]["amp_ch2"] == "interrupted"


def test_disk_failure_stops_before_next_project(fake_connections, no_sleep, monkeypatch, tmp_path):
    from osccal.core import storage
    from osccal.measure.amp import AmpCalibrator
    from osccal.measure.dc_gain import DcGainCalibrator

    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    original_replace = storage.os.replace
    replacements = 0

    def fail_second_replace(source, target):
        nonlocal replacements
        replacements += 1
        if replacements > 1:
            raise OSError("模拟磁盘写入失败")
        original_replace(source, target)

    monkeypatch.setattr(storage.os, "replace", fail_second_replace)
    monkeypatch.setattr(AmpCalibrator, "run", lambda self: None)
    next_started = []
    monkeypatch.setattr(DcGainCalibrator, "run", lambda self: next_started.append(True))
    result = CliRunner().invoke(cli, _recording_args("amp,dc_gain"))
    assert result.exit_code == 1
    assert "模拟磁盘写入失败" in result.output
    assert not next_started
    assert replacements == 2
    saved = storage.load_calibration_data(storage.get_latest_calibration_file())
    assert saved["metadata"]["status"] == "in_progress"
    assert len(list(tmp_path.iterdir())) == 1


def test_repeated_round_has_own_file_and_error_count(
    fake_connections, no_sleep, monkeypatch, tmp_path
):
    from osccal.core import scpi_trace, storage
    from osccal.measure.amp import AmpCalibrator

    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    calls = 0

    def run(self):
        nonlocal calls
        calls += 1
        if calls == 1:
            scpi_trace.record_failure()
            raise ValueError("首轮失败")
        self.results = [{"measured": 1}]

    monkeypatch.setattr(AmpCalibrator, "run", run)
    result = CliRunner().invoke(cli, _recording_args("amp"), input="y\n0\n1\nn\n")
    assert result.exit_code == 1, result.output
    files = storage.list_calibration_files()
    assert len(files) == 2
    rounds = [storage.load_calibration_data(str(tmp_path / path))["metadata"] for path in files]
    assert rounds[0]["status"] == "completed"
    assert rounds[0]["scpi_errors"] == 0
    assert rounds[1]["status"] == "completed_with_errors"
    assert rounds[1]["scpi_errors"] == 1
    assert rounds[1]["failures"]["amp"]["message"] == "首轮失败"


@pytest.mark.parametrize(
    "options",
    [
        ["--channel", "0"],
        ["--channel", "5"],
        ["--channel", "abc"],
        ["--channel", "1,1"],
        ["--channel", "01,1"],
        ["--channel", ""],
        ["--items", "unknown"],
        ["--items", "amp,amp"],
        ["--items", "all,amp"],
        ["--items", ""],
        ["--probe", "unknown"],
        ["--probe", ""],
        ["--bandwidth", "nan"],
        ["--bd-step", "inf"],
        ["--probe", "9550"],
        ["--items", "bandwidth", "--probe", "9530", "--bandwidth", "700"],
        ["--items", "bandwidth", "--bd-step", "0"],
        ["--items", "bandwidth", "--bd-step", "nan"],
        ["--profile", "profiles/tektronix_mdo32.json"],
        ["--resource-osc", "GPIB0::19::INSTR"],
        ["--socket-osc", "invalid"],
    ],
)
def test_invalid_plan_sends_no_setup_commands(
    fake_connections, no_sleep, no_save, monkeypatch, options
):
    instruments = []
    original_connect = fake_connections.connect_visa

    def connect(resource):
        inst, idn = original_connect(resource)
        instruments.append(inst)
        return inst, idn

    monkeypatch.setattr(fake_connections, "connect_visa", connect)
    result = CliRunner().invoke(cli, _recording_args("amp") + options)
    assert result.exit_code == 2, result.output
    assert all(not inst.written for inst in instruments)
    assert not no_save


def test_mdo32_channel_limit_applies_before_setup(fake_connections, no_sleep, no_save, monkeypatch):
    original_connect = fake_connections.connect_visa
    instruments = []

    def connect(resource):
        inst, idn = original_connect(resource)
        if "19" not in resource:
            idn["model"] = "MDO32"
        instruments.append(inst)
        return inst, idn

    monkeypatch.setattr(fake_connections, "connect_visa", connect)
    result = CliRunner().invoke(
        cli, _recording_args("amp", "3") + ["--profile", "profiles/tektronix_mdo32.json"]
    )
    assert result.exit_code == 2
    assert "1 至 2" in result.output
    assert all(not inst.written for inst in instruments)


def test_calibrator_model_variant_9500_passes_preflight(
    fake_connections, no_sleep, no_save, monkeypatch
):
    """回归：FLUKE 9500B 上报型号为 "9500" 时不应被执行前校验中止。"""
    original_connect = fake_connections.connect_visa

    def connect(resource):
        inst, idn = original_connect(resource)
        if "19" in resource:  # 校准仪资源
            idn["model"] = "9500"
            inst.idn = "FLUKE,9500,471475627,4.12"
        return inst, idn

    monkeypatch.setattr(fake_connections, "connect_visa", connect)
    result = CliRunner().invoke(cli, _recording_args("amp"), input="n\n")
    assert result.exit_code == 0, result.output
    assert "执行前检查失败" not in result.output
    assert "amp" in no_save["results"]


def test_selection_menus_bound_indices_and_channels():
    import click

    from osccal.cli import _select_channel, _select_index

    @click.command()
    def select():
        click.echo(_select_index(2))
        click.echo(_select_channel(2))

    result = CliRunner().invoke(select, input="-1\n99\n1\n2\n")
    assert result.exit_code == 0
    assert "CH3" not in result.output and "CH4" not in result.output
    assert result.output.rstrip().endswith("1,2")


def test_connection_failure_exit_code(fake_connections, no_sleep, no_save, monkeypatch):
    monkeypatch.setattr(fake_connections, "connect_visa", lambda _: (None, {}))
    result = CliRunner().invoke(cli, _recording_args("amp"))
    assert result.exit_code == 1
    assert not no_save


def test_auto_multiple_devices_requires_selection(fake_connections, no_sleep, no_save, monkeypatch):
    class RM:
        def list_resources(self):
            return ["GPIB0::19::INSTR", "GPIB0::10::INSTR", "GPIB0::11::INSTR"]

        def open_resource(self, resource):
            return FakeInst(idn="FLUKE,9500B,S,1" if "19" in resource else "TEKTRONIX,MDO34,S,1")

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "pyvisa", types.SimpleNamespace(ResourceManager=RM))
    result = CliRunner().invoke(cli, ["calibrate", "--auto"])
    assert result.exit_code == 2
    assert "多台" in result.output
    assert not no_save
