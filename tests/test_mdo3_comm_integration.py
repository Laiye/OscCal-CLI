"""MDO3 指令集与 comm.py 端到端集成测试。

使用 FakeInstrument（pyvisa 模式）验证：
- scpi_write / scpi_query 正确驱动仪器并记录指令
- scpi_setup_measurement（merge 模式）下发正确的 set_meas_source + set_meas_type
- read_measurement（merge 模式）下发测量源/类型后查询 VALue?，并按 return_value_index=1
  正确解析 ":MEASUREMENT:IMMED:VALUE <val>" 响应
- 各通道（1-4）、各测量类型（AMPlitude/PERIod/MAXimum/MINimum/RISe 等）均工作正常
- 无效响应（包括 9.91E+37）抛出 ScpiError，禁止参与校准计算
"""

import time

import pytest

from osccal.core import scpi_trace
from osccal.core.comm import (
    ScpiError,
    read_measurement,
    scpi_query,
    scpi_setup_measurement,
    scpi_write,
)

# ===========================================================================
# scpi_write / scpi_query 与 FakeInstrument 接口契约
# ===========================================================================


class TestScpiWriteQuery:
    def test_scpi_write_records_command(self, fake_osc):
        scpi_write(fake_osc, "CH1:SCAle 0.001", "pyvisa")
        assert fake_osc.written == ["CH1:SCAle 0.001"]

    def test_scpi_query_returns_response(self, fake_osc):
        fake_osc.query_responses = {"MEASUrement:IMMed:VALue?": ":MEASUREMENT:IMMED:VALUE 2.5E+0"}
        res = scpi_query(fake_osc, "MEASUrement:IMMed:VALue?", "pyvisa")
        assert res == ":MEASUREMENT:IMMED:VALUE 2.5E+0"
        assert "MEASUrement:IMMed:VALue?" in fake_osc.written


# ===========================================================================
# scpi_setup_measurement（merge 模式）
# ===========================================================================


class TestSetupMeasurement:
    def test_merge_writes_source_then_type(self, mdo3_commands, fake_osc):
        scpi_setup_measurement(fake_osc, mdo3_commands, "1", "AMPlitude")
        # 应依次下发测量源与测量类型两条指令
        assert fake_osc.written == [
            "MEASUrement:IMMed:SOUrce1 CH1",
            "MEASUrement:IMMed:TYPe AMPlitude",
        ]

    @pytest.mark.parametrize("channel", ["1", "2", "3", "4"])
    def test_setup_all_channels(self, mdo3_commands, fake_osc, channel):
        scpi_setup_measurement(fake_osc, mdo3_commands, channel, "AMPlitude")
        assert f"MEASUrement:IMMed:SOUrce1 CH{channel}" in fake_osc.written
        assert "MEASUrement:IMMed:TYPe AMPlitude" in fake_osc.written

    @pytest.mark.parametrize(
        "meas_key,keyword_val",
        [
            ("meas_amp", "AMPlitude"),
            ("meas_period", "PERIod"),
            ("meas_mean", "MEAN"),
            ("meas_risetime", "RISe"),
            ("meas_max", "MAXimum"),
            ("meas_min", "MINimum"),
            ("meas_pos_overshoot", "POVershoot"),
        ],
    )
    def test_setup_all_meas_types(self, mdo3_commands, fake_osc, meas_key, keyword_val):
        scpi_setup_measurement(fake_osc, mdo3_commands, "1", keyword_val)
        assert f"MEASUrement:IMMed:TYPe {keyword_val}" in fake_osc.written


# ===========================================================================
# read_measurement（merge 模式）—— 完整链路
# ===========================================================================


class TestReadMeasurement:
    def test_merge_read_parses_value(self, mdo3_commands, fake_osc):
        """查询响应 ':MEASUREMENT:IMMED:VALUE <val>' 应按 index=1 解析。"""
        val = read_measurement(fake_osc, None, mdo3_commands, "1", "AMPlitude")
        assert val == pytest.approx(1.234)

    def test_merge_read_command_sequence(self, mdo3_commands, fake_osc):
        read_measurement(fake_osc, None, mdo3_commands, "2", "PERIod")
        # 完整指令序列：源 → 类型 → 查询
        assert fake_osc.written == [
            "MEASUrement:IMMed:SOUrce1 CH2",
            "MEASUrement:IMMed:TYPe PERIod",
            "MEASUrement:IMMed:VALue?",
        ]

    def test_merge_read_custom_response(self, mdo3_commands, fake_osc):
        fake_osc.query_responses = {"MEASUrement:IMMed:VALue?": ":MEASUREMENT:IMMED:VALUE 5.678E-3"}
        val = read_measurement(fake_osc, None, mdo3_commands, "1", "AMPlitude")
        assert val == pytest.approx(5.678e-3)

    def test_merge_read_nan_response(self, mdo3_commands, fake_osc):
        """超大数值（>1e30，如 ZDS 的 Invalid 标记）必须抛异常，禁止进入误差计算。"""
        fake_osc.query_responses = {"MEASUrement:IMMed:VALue?": ":MEASUREMENT:IMMED:VALUE 9.91E+37"}
        with pytest.raises(ScpiError):
            read_measurement(fake_osc, None, mdo3_commands, "1", "AMPlitude")

    def test_merge_read_negative_value(self, mdo3_commands, fake_osc):
        fake_osc.query_responses = {"MEASUrement:IMMed:VALue?": ":MEASUREMENT:IMMED:VALUE -1.5E+0"}
        val = read_measurement(fake_osc, None, mdo3_commands, "1", "MEAN")
        assert val == pytest.approx(-1.5)

    def test_setup_error_before_response_does_not_crash(self, mdo3_commands, fake_osc, monkeypatch):
        """P0 回归：测量设置阶段抛 ValueError 时，异常处理不应因 res 未绑定而崩溃。"""
        import osccal.core.comm as comm

        def boom(*args, **kwargs):
            raise ValueError("模拟设置失败")

        monkeypatch.setattr(comm, "scpi_setup_measurement", boom)
        with pytest.raises(ScpiError):
            read_measurement(fake_osc, None, mdo3_commands, "1", "AMPlitude")

    def test_parse_failure_records_failure(self, mdo3_commands, fake_osc):
        """P1 回归：解析失败必须计入 scpi_errors，而非静默返回 0.0。"""
        scpi_trace.reset()
        fake_osc.query_responses = {"MEASUrement:IMMed:VALue?": "not-a-number"}
        with pytest.raises(ScpiError):
            read_measurement(fake_osc, None, mdo3_commands, "1", "AMPlitude")
        assert scpi_trace.failure_count() >= 1

    def test_invalid_measurement_records_failure(self, mdo3_commands, fake_osc):
        """P1 回归：Invalid（>1e30）同样应计入失败。"""
        scpi_trace.reset()
        fake_osc.query_responses = {"MEASUrement:IMMed:VALue?": ":MEASUREMENT:IMMED:VALUE 9.91E+37"}
        with pytest.raises(ScpiError):
            read_measurement(fake_osc, None, mdo3_commands, "1", "AMPlitude")
        assert scpi_trace.failure_count() >= 1

    @pytest.mark.parametrize("channel", ["1", "2", "3", "4"])
    def test_read_all_channels(self, mdo3_commands, fake_osc, channel):
        val = read_measurement(fake_osc, None, mdo3_commands, channel, "AMPlitude")
        assert isinstance(val, float)
        assert f"MEASUrement:IMMed:SOUrce1 CH{channel}" in fake_osc.written


# ===========================================================================
# 通过 BaseCalibrator._read_meas 间接验证 keyword 解析链路
# ===========================================================================


class TestBaseCalibratorReadMeas:
    """构造一个最小 BaseCalibrator，验证 _read_meas 经 keyword 映射后调用 read_measurement。"""

    def _make_calibrator(self, mdo3_commands, fake_osc):
        from osccal.measure.base import BaseCalibrator

        # 仅需要 cmd_osc / inst_osc / channel，其余参数传 None
        return BaseCalibrator(
            inst_osc=fake_osc,
            inst_calibrator=None,
            cmd_osc=mdo3_commands,
            cmd_calibrator={},
            profile={},
            channel="1",
            probe=None,
        )

    def test_read_meas_resolves_keyword(self, mdo3_commands, fake_osc):
        cal = self._make_calibrator(mdo3_commands, fake_osc)
        val = cal._read_meas("meas_amp")
        assert val == pytest.approx(1.234)
        # 验证 keyword 被正确解析为 AMPlitude
        assert "MEASUrement:IMMed:TYPe AMPlitude" in fake_osc.written

    def test_read_meas_max_for_vertical_adjust(self, mdo3_commands, fake_osc):
        """_adjust_vertical_position 依赖的 meas_max/meas_min keyword 可用。"""
        cal = self._make_calibrator(mdo3_commands, fake_osc)
        # 应不抛 KeyError
        cal._read_meas("meas_max")
        cal._read_meas("meas_min")
        assert "MEASUrement:IMMed:TYPe MAXimum" in fake_osc.written
        assert "MEASUrement:IMMed:TYPe MINimum" in fake_osc.written


# ===========================================================================
# 阻抗设置链路（base.setup_impedance）
# ===========================================================================


class TestImpedanceSetup:
    def _make_calibrator(self, mdo3_commands, fake_osc):
        from osccal.measure.base import BaseCalibrator

        return BaseCalibrator(
            inst_osc=fake_osc,
            inst_calibrator=None,
            cmd_osc=mdo3_commands,
            cmd_calibrator={},
            profile={"imp_has_50": True},
            channel="1",
            probe=None,
        )

    def test_setup_impedance_fifty(self, mdo3_commands, fake_osc):
        cal = self._make_calibrator(mdo3_commands, fake_osc)
        cal.setup_impedance("imp_fif")
        assert "CH1:TERmination FIFty" in fake_osc.written

    def test_setup_impedance_meg(self, mdo3_commands, fake_osc):
        cal = self._make_calibrator(mdo3_commands, fake_osc)
        cal.setup_impedance("imp_meg")
        assert "CH1:TERmination MEG" in fake_osc.written


# ===========================================================================
# 通信重试（socket 超时不再被吞掉）
# ===========================================================================


class FakeSocket:
    """模拟 socket：sendall 记录指令，recv 按脚本返回数据或抛异常。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.sent: list[bytes] = []

    def sendall(self, data: bytes):
        self.sent.append(data)

    def recv(self, n: int) -> bytes:
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class TestSocketRetry:
    def test_query_retries_after_timeout(self, monkeypatch):
        """P1 回归：socket 读取超时应触发重试，而非当作空响应直接返回。"""
        monkeypatch.setattr(time, "sleep", lambda _x: None)
        scpi_trace.reset()
        sock = FakeSocket([TimeoutError("模拟超时"), b"1.0\n"])

        res = scpi_query(sock, "X?", "socket")

        assert res == "1.0\n"
        assert len(sock.sent) == 2, "超时后应重发指令"
        assert scpi_trace.failure_count() == 0

    def test_query_timeout_exhausted_counts_failure(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda _x: None)
        scpi_trace.reset()
        sock = FakeSocket([TimeoutError("超时1"), TimeoutError("超时2")])

        with pytest.raises(ScpiError):
            scpi_query(sock, "X?", "socket")
        assert scpi_trace.failure_count() == 1

    def test_pyvisa_timeout_message_retried(self, monkeypatch):
        """pyvisa 的 VI_ERROR_TMO 不是 TimeoutError，也应被识别并重试。"""
        monkeypatch.setattr(time, "sleep", lambda _x: None)
        scpi_trace.reset()

        class FlakyInst:
            def __init__(self):
                self.calls = 0

            def query(self, cmd):
                self.calls += 1
                if self.calls == 1:
                    raise Exception("VI_ERROR_TMO: Timeout expired before operation completed.")
                return "2.0\n"

        inst = FlakyInst()
        res = scpi_query(inst, "X?", "pyvisa")

        assert res == "2.0\n"
        assert inst.calls == 2
        assert scpi_trace.failure_count() == 0
