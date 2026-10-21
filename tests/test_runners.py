"""M3' 三个复用型校准项目的行为用例（dc_gain / dc_offset / freq_response）。

用打桩的示波器/校准仪对象验证"指令序列 + 计算口径"，不连接任何仪器。
"""

import json
from pathlib import Path

import pytest

from osccal.measure.dc_gain import DcGainCalibrator
from osccal.measure.dc_offset import DcOffsetCalibrator
from osccal.measure.freq_response import FreqResponseCalibrator
from osccal.measure.registry import ITEM_ORDER, RUNNERS

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StubInstrument:
    """最小仪器桩：记录写入，查询返回空串（测量由测试打桩覆盖）。"""

    def __init__(self):
        self.written: list[str] = []

    def write(self, cmd: str):
        self.written.append(cmd)

    def query(self, cmd: str) -> str:
        self.written.append(cmd)
        return ""


def _load(name: str, sub: str) -> dict:
    with open(PROJECT_ROOT / sub / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """跳过各处稳定延时，只验证指令序列与计算。"""
    import time as time_module

    monkeypatch.setattr(time_module, "sleep", lambda *_args, **_kwargs: None)


@pytest.fixture(scope="module")
def configs() -> tuple[dict, dict, dict]:
    return (
        _load("tektronix_mdo.json", "commands"),
        _load("fluke_9500b.json", "calibrators"),
        _load("tektronix_mdo3052.json", "profiles"),
    )


def build(cls, configs, points, reader):
    """构造项目实例并打桩：跳过设备初始化，测量值由 reader 提供。"""
    cmd_osc, cmd_cal, profile = configs
    osc, cal = StubInstrument(), StubInstrument()
    instance = cls(osc, cal, cmd_osc, cmd_cal, profile, "1", "9530", points)
    instance.init_devices = lambda: None
    instance.setup_channel = lambda: None
    instance.setup_measurement = lambda key, trigger=True: None
    instance._read_meas = reader
    return instance, osc, cal


class TestDcGainMethodTwo:
    def test_gain_is_measured_over_standard(self, configs):
        points = [{"channel": "1", "scale": 0.1, "impedance": "1M", "std_value_vpp": 0.64}]
        instance, _, cal = build(DcGainCalibrator, configs, points, lambda key, trigger=True: 0.64)
        instance.run()

        record = instance.results[0]
        assert record["gain"] == pytest.approx(1.0)
        assert record["error_pct"] == pytest.approx(0.0)
        assert any("SHAP SQU" in cmd for cmd in cal.written), "方法二必须用方波激励"
        assert any("1000" in cmd for cmd in cal.written), "推荐频率 1 kHz"

    def test_error_sign_follows_gain(self, configs):
        points = [{"channel": "1", "scale": 0.1, "impedance": "1M", "std_value_vpp": 0.64}]
        instance, _, _ = build(DcGainCalibrator, configs, points, lambda key, trigger=True: 0.6464)
        instance.run()
        assert instance.results[0]["error_pct"] == pytest.approx(1.0, abs=1e-6)

    def test_50_ohm_point_switches_impedance(self, configs):
        points = [{"channel": "1", "scale": 0.01, "impedance": "50", "std_value_vpp": 0.064}]
        instance, osc, cal = build(
            DcGainCalibrator, configs, points, lambda key, trigger=True: 0.064
        )
        instance.run()
        assert any("FIF" in cmd for cmd in osc.written), "应写入示波器 50 Ω（FIFty）"
        assert any("ROUT:SIGN:IMP 50" in cmd for cmd in cal.written), "应写入校准仪 50 Ω"

    def test_no_points_is_reported_not_crashed(self, configs):
        instance, _, _ = build(DcGainCalibrator, configs, [], lambda key, trigger=True: 0.0)
        instance.run()
        assert instance.results == []


class TestDcOffset:
    def test_zero_and_offset_reading(self, configs):
        points = [{"channel": "1", "scale": 0.1, "impedance": "1M"}]
        readings = iter([0.0, 0.2])  # 零点读数、偏置实测（标称 2 格 = 0.2 V）
        instance, _, _ = build(
            DcOffsetCalibrator, configs, points, lambda key, trigger=True: next(readings)
        )
        instance.run()

        record = instance.results[0]
        assert record["offset_nominal_v"] == pytest.approx(0.2)
        assert record["offset_error_v"] == pytest.approx(0.0)
        assert record["gain"] == pytest.approx(1.0)
        assert record["full_scale_v"] == pytest.approx(0.8)

    def test_offset_error_normalised_to_full_scale(self, configs):
        points = [{"channel": "1", "scale": 0.1, "impedance": "1M"}]
        readings = iter([0.0, 0.208])  # 偏置偏高 8 mV，满量程 0.8 V → 1 %
        instance, _, _ = build(
            DcOffsetCalibrator, configs, points, lambda key, trigger=True: next(readings)
        )
        instance.run()
        assert instance.results[0]["error_pct"] == pytest.approx(-1.0)


class TestFreqResponse:
    ATTENUATION = {50000: 0.5, 1e6: 0.5, 1e8: 0.5, 2.5e8: 0.45, 5e8: 0.3}

    def _reader_factory(self):
        state = {"frequency": 0.0}

        def reader(key, trigger=True):
            return self.ATTENUATION[state["frequency"]]

        return state, reader

    def test_bandwidth_interpolates_between_points(self):
        frequencies = [5e4, 2.5e8, 5e8]
        responses = [1.0, 0.9, 0.6]
        bandwidth = FreqResponseCalibrator.bandwidth_from_response(frequencies, responses)
        assert bandwidth is not None
        assert 2.5e8 < bandwidth < 5e8

    def test_bandwidth_none_when_never_crosses(self):
        assert FreqResponseCalibrator.bandwidth_from_response([1e6, 1e7], [1.0, 0.9]) is None

    def test_response_relative_to_reference(self, configs):
        points = [
            {"channel": "1", "frequency_hz": 50000},
            {"channel": "1", "frequency_hz": 2.5e8},
        ]
        state, reader = self._reader_factory()
        instance, _, _ = build(FreqResponseCalibrator, configs, points, None)
        # 用 set_freq 记录当前频率，让 reader 按频率取值
        instance._write_calibrator = lambda name, *args: state.update(
            frequency=args[0] if name == "set_freq" else state["frequency"]
        )
        instance._read_meas = reader
        instance.run()

        rows = [r for r in instance.results if "response" in r]
        assert rows[0]["response"] == pytest.approx(1.0), "基准点自身响应应为 1"
        assert rows[1]["response"] == pytest.approx(0.9)

    def test_summary_recorded(self, configs):
        points = [
            {"channel": "1", "frequency_hz": 50000},
            {"channel": "1", "frequency_hz": 5e8},
        ]
        state, reader = self._reader_factory()
        instance, _, _ = build(FreqResponseCalibrator, configs, points, None)
        instance._write_calibrator = lambda name, *args: state.update(
            frequency=args[0] if name == "set_freq" else state["frequency"]
        )
        instance._read_meas = reader
        instance.run()
        summary = [r for r in instance.results if r.get("summary") == "bandwidth"]
        assert summary, "应写入一条频带宽度汇总记录"
        assert summary[0]["bandwidth_hz"] is not None


class TestRegistryWiring:
    @pytest.mark.parametrize(
        "name",
        ["dc_gain", "dc_offset", "freq_response_bandwidth"],
    )
    def test_items_registered(self, name):
        assert name in RUNNERS

    def test_all_registered_items_belong_to_order(self):
        assert set(RUNNERS) <= set(ITEM_ORDER)

    def test_all_spec_items_registered(self):
        """清单是规范要求，RUNNERS 是已实现：M5' 之后 10 项应全部就位。"""
        assert set(ITEM_ORDER) == set(RUNNERS)
