"""MDO3 指令集与 comm.py 端到端集成测试。

使用 FakeInstrument（pyvisa 模式）验证：
- scpi_write / scpi_query 正确驱动仪器并记录指令
- scpi_setup_measurement（merge 模式）下发正确的 set_meas_source + set_meas_type
- read_measurement（merge 模式）下发测量源/类型后查询 VALue?，并按 return_value_index=1
  正确解析 ":MEASUREMENT:IMMED:VALUE <val>" 响应
- 各通道（1-4）、各测量类型（AMPlitude/PERIod/MAXimum/MINimum/RISe 等）均工作正常
- NaN 响应（9.91E+37）可被解析为浮点数（不抛异常）
"""
import pytest

from osccal.core.comm import (
    scpi_write,
    scpi_query,
    scpi_setup_measurement,
    read_measurement,
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

    @pytest.mark.parametrize("meas_key,keyword_val", [
        ("meas_amp", "AMPlitude"),
        ("meas_period", "PERIod"),
        ("meas_mean", "MEAN"),
        ("meas_risetime", "RISe"),
        ("meas_max", "MAXimum"),
        ("meas_min", "MINimum"),
        ("meas_pos_overshoot", "POVershoot"),
    ])
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
        fake_osc.query_responses = {
            "MEASUrement:IMMed:VALue?": ":MEASUREMENT:IMMED:VALUE 5.678E-3"
        }
        val = read_measurement(fake_osc, None, mdo3_commands, "1", "AMPlitude")
        assert val == pytest.approx(5.678e-3)

    def test_merge_read_nan_response(self, mdo3_commands, fake_osc):
        """9.91E+37 表示 NaN，应被解析为大浮点数而不抛异常。"""
        fake_osc.query_responses = {
            "MEASUrement:IMMed:VALue?": ":MEASUREMENT:IMMED:VALUE 9.91E+37"
        }
        val = read_measurement(fake_osc, None, mdo3_commands, "1", "AMPlitude")
        assert val == pytest.approx(9.91e37)

    def test_merge_read_negative_value(self, mdo3_commands, fake_osc):
        fake_osc.query_responses = {
            "MEASUrement:IMMed:VALue?": ":MEASUREMENT:IMMED:VALUE -1.5E+0"
        }
        val = read_measurement(fake_osc, None, mdo3_commands, "1", "MEAN")
        assert val == pytest.approx(-1.5)

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
