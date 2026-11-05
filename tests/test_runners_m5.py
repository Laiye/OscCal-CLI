"""M5' 两个项目的行为用例（input_impedance / enob）。"""

import json
import math
from pathlib import Path

import pytest

from osccal.core.waveform import Waveform, WaveformPreamble
from osccal.measure.enob import EnobCalibrator
from osccal.measure.input_impedance import InputImpedanceCalibrator

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StubInstrument:
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


@pytest.fixture(scope="module")
def configs() -> tuple[dict, dict, dict]:
    return (
        _load("tektronix_mdo.json", "commands"),
        _load("fluke_9500b.json", "calibrators"),
        _load("tektronix_mdo3052.json", "characteristics"),
    )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    import time as time_module

    monkeypatch.setattr(time_module, "sleep", lambda *_args, **_kwargs: None)


def build(cls, configs, points):
    cmd_osc, cmd_cal, profile = configs
    instance = cls(
        StubInstrument(), StubInstrument(), cmd_osc, cmd_cal, profile, "1", "9530", points
    )
    instance.init_devices = lambda: None
    instance.setup_channel = lambda: None
    instance.setup_measurement = lambda key, trigger=True: None
    return instance


def load_query(responses, state):
    """模拟校准仪查询：RES/CAP 读数走 responses，阻抗回读固定为高阻。"""

    def query(action, *args):
        if action == "query_impedance":
            return "10000"
        return responses[state["func"]]

    return query


class TestInputImpedance:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("1.000500E+06\n", 1.0005e6),
            ("50.12\n", 50.12),
            ("2E+35\n", None),
            ("2.0E+35", None),
            ("\n", None),
            ("READ? 1.0E+06", 1e6),
        ],
    )
    def test_parse_reading(self, text, expected):
        result = InputImpedanceCalibrator.parse_reading(text)
        if expected is None:
            assert result is None
        else:
            assert result == pytest.approx(expected)

    def test_measures_resistance_and_capacitance(self, configs):
        responses = {"RES": "1.0005E+06\n", "CAP": "1.2E-11\n"}
        points = [{"channel": "1", "impedance": "1M"}]
        instance = build(InputImpedanceCalibrator, configs, points)
        state = {"func": None}

        def write(action, *args):
            if action == "set_load_func":
                state["func"] = args[0]
            instance.inst_calibrator.written.append(action)

        instance._write_calibrator = write
        instance._query_calibrator = load_query(responses, state)
        instance.run()

        record = instance.results[0]
        assert record["resistance_ohm"] == pytest.approx(1.0005e6)
        assert record["capacitance_f"] == pytest.approx(1.2e-11)
        assert record["error_pct"] == pytest.approx(0.05, abs=1e-9)
        assert record["tolerance_pct"] == pytest.approx(0.5)

    def test_50_ohm_tolerance_is_one_percent(self, configs):
        responses = {"RES": "50.2\n", "CAP": "9.0E-12\n"}
        points = [{"channel": "1", "impedance": "50"}]
        instance = build(InputImpedanceCalibrator, configs, points)
        state = {"func": None}
        instance._write_calibrator = lambda action, *args: state.update(
            func=args[0] if action == "set_load_func" else state["func"]
        )
        instance._query_calibrator = load_query(responses, state)
        instance.run()
        record = instance.results[0]
        assert record["tolerance_pct"] == pytest.approx(1.0)
        assert record["error_pct"] == pytest.approx(0.4, abs=1e-9)

    def test_sentinel_marks_reading_invalid(self, configs):
        responses = {"RES": "2E+35\n", "CAP": "2E+35\n"}
        points = [{"channel": "1", "impedance": "1M"}]
        instance = build(InputImpedanceCalibrator, configs, points)
        state = {"func": None}
        instance._write_calibrator = lambda action, *args: state.update(
            func=args[0] if action == "set_load_func" else state["func"]
        )
        instance._query_calibrator = load_query(responses, state)
        instance.run()
        record = instance.results[0]
        assert record["resistance_ohm"] is None
        assert record["error_pct"] is None

    def test_restores_waveform_function_after_measurement(self, configs):
        responses = {"RES": "1.0E+06\n", "CAP": "1.0E-11\n"}
        points = [{"channel": "1", "impedance": "1M"}]
        instance = build(InputImpedanceCalibrator, configs, points)
        calls: list[str] = []
        state = {"func": None}

        def write(action, *args):
            calls.append(action)
            if action == "set_load_func":
                state["func"] = args[0]

        instance._write_calibrator = write
        instance._query_calibrator = load_query(responses, state)
        instance.run()
        assert "set_shap" in calls, "测量后必须退出负载测量功能、恢复波形输出"

    def test_exits_measure_function_before_changing_impedance(self, configs):
        """实机约束：在负载测量功能下改 ROUT:SIGN:IMP 会被拒绝，必须先 set_shap 退出。"""
        responses = {"RES": "1.0E+06\n", "CAP": "1.0E-11\n"}
        points = [{"channel": "1", "impedance": "1M"}]
        instance = build(InputImpedanceCalibrator, configs, points)
        calls: list[str] = []
        state = {"func": None}

        def write(action, *args):
            calls.append(action)
            if action == "set_load_func":
                state["func"] = args[0]

        instance._write_calibrator = write
        instance._query_calibrator = load_query(responses, state)
        instance.run()

        first_load = calls.index("set_load_func")
        assert "set_shap" in calls[:first_load], "首次进入测量功能前应先恢复波形输出"

    def test_reopens_output_after_entering_measure_function(self, configs):
        """实机约束：CONF:RES/CAP 会关掉输出，必须先重新开输出再读，否则读到 2E35。"""
        responses = {"RES": "1.0E+06\n", "CAP": "1.0E-11\n"}
        points = [{"channel": "1", "impedance": "1M"}]
        instance = build(InputImpedanceCalibrator, configs, points)
        calls: list[str] = []
        state = {"func": None}

        def write(action, *args):
            calls.append(action)
            if action == "set_load_func":
                state["func"] = args[0]

        instance._write_calibrator = write
        instance._query_calibrator = load_query(responses, state)
        instance.run()

        load_index = calls.index("set_load_func")
        assert calls[load_index + 1] == "set_output", "切入测量功能后应立即重新打开输出"


class TestEnob:
    def _sine_wave(self, freq, sample_rate, samples=1000, amplitude=0.76, noise=0.0):
        seconds = [index / sample_rate for index in range(samples)]
        volts = []
        state = 12345
        for t in seconds:
            value = amplitude * math.sin(2 * math.pi * freq * t)
            if noise:
                state = (1103515245 * state + 12345) % (2**31)
                value += noise * (state / 2**31 - 0.5)
            volts.append(value)
        return Waveform(
            codes=[],
            volts=volts,
            seconds=seconds,
            preamble=WaveformPreamble(x_increment=1 / sample_rate, nr_pt=samples),
        )

    def test_frequency_derived_from_sample_rate(self, configs):
        points = [{"channel": "1", "runtime": True, "samples_n": 1000, "integer_cycles_n": 7}]
        instance = build(EnobCalibrator, configs, points)
        instance._query_osc = lambda action, *args: "5.0E+09"
        instance._read_waveform = lambda samples: self._sine_wave(35e6, 5e9, samples)
        instance.run()

        record = instance.results[0]
        assert record["sample_rate_sa_s"] == pytest.approx(5e9)
        assert record["signal_freq_hz"] == pytest.approx(35e6)
        assert record["full_scale_v"] == pytest.approx(0.2 * 8)
        assert record["signal_amplitude_vpp"] == pytest.approx(0.95 * 1.6)

    def test_enob_from_fit_residual(self, configs):
        points = [{"channel": "1", "runtime": True, "samples_n": 1000, "integer_cycles_n": 7}]
        instance = build(EnobCalibrator, configs, points)
        instance._query_osc = lambda action, *args: "5.0E+09"
        instance._read_waveform = lambda samples: self._sine_wave(35e6, 5e9, samples, noise=0.002)
        instance.run()
        record = instance.results[0]
        assert record["enob"] is not None
        # 1.6 V 量程、残差约 6e-4 V → ENOB ≈ log2(1.6/(3.46×6e-4)) ≈ 9.6
        assert 8.0 < record["enob"] < 11.0
        assert record["rms_error_v"] == pytest.approx(0.0006, rel=0.5)

    def test_rejects_non_coprime_counts(self, configs):
        points = [{"channel": "1", "samples_n": 1000, "integer_cycles_n": 5}]
        instance = build(EnobCalibrator, configs, points)
        instance._query_osc = lambda action, *args: "5.0E+09"
        with pytest.raises(ValueError, match="公因子"):
            instance._measure_point(points[0])

    def test_perfect_signal_gives_implausibly_high_enob(self, configs):
        """无噪声的理想数据残差趋近 0，ENOB 会远高于真实位数——说明该指标依赖真实噪声。"""
        points = [{"channel": "1", "samples_n": 1000, "integer_cycles_n": 7}]
        instance = build(EnobCalibrator, configs, points)
        instance._query_osc = lambda action, *args: "5.0E+09"
        instance._read_waveform = lambda samples: self._sine_wave(35e6, 5e9, samples)
        record = instance._measure_point(points[0])
        assert record["enob"] is not None and record["enob"] > 20


class TestDeltaV:
    def test_error_relative_to_standard(self, configs):
        from osccal.measure.delta_v import DeltaVCalibrator

        points = [{"channel": "1", "scale": 0.1, "impedance": "1M", "std_value_vpp": 0.64}]
        instance = build(DeltaVCalibrator, configs, points)
        instance._read_meas = lambda key, trigger=True: 0.6464
        instance.run()
        record = instance.results[0]
        assert record["error_pct"] == pytest.approx(1.0, abs=1e-6)
        assert record["method"] == "auto_measurement", "记录必须写明用自动测量代替光标"

    def test_square_wave_stimulus(self, configs):
        from osccal.measure.delta_v import DeltaVCalibrator

        points = [{"channel": "1", "scale": 0.1, "impedance": "1M", "std_value_vpp": 0.64}]
        instance = build(DeltaVCalibrator, configs, points)
        instance._read_meas = lambda key, trigger=True: 0.64
        instance.run()
        assert any("SHAP SQU" in cmd for cmd in instance.inst_calibrator.written)


class TestRiseTime:
    def test_reads_rise_time_and_overshoot(self, configs):
        from osccal.measure.rise_time import RiseTimeCalibrator

        points = [{"channel": "1", "edge_rise_time_s": 150e-12}]
        instance = build(RiseTimeCalibrator, configs, points)
        # 9500B 输出单极性快沿，示波器按上升沿（RIS）测量
        readings = {"meas_risetime": 700e-12, "meas_pos_overshoot": 2.5}
        instance._read_meas = lambda key, trigger=True: readings[key]
        instance.run()
        record = instance.results[0]
        assert record["rise_time_s"] == pytest.approx(700e-12)
        assert record["overshoot_pct"] == pytest.approx(2.5)
        assert record["edge_rise_time_s"] == pytest.approx(150e-12)
        assert record["impedance"] == "50", "快沿必须 50 Ω 端接"

    def test_uses_fast_edge_and_declared_speed(self, configs):
        from osccal.measure.rise_time import RiseTimeCalibrator

        points = [{"channel": "1", "edge_rise_time_s": 500e-12}]
        instance = build(RiseTimeCalibrator, configs, points)
        instance._read_meas = lambda key, trigger=True: 1e-9
        instance.run()
        written = instance.inst_calibrator.written
        assert any("SHAP EDGE" in cmd for cmd in written)
        assert any("EDGE:SPE" in cmd and "5e-10" in cmd for cmd in written)
        # 50 Ω 端接 + 上升沿触发
        assert any("IMP 50" in cmd for cmd in written)

    def test_falls_back_to_1m_without_50_ohm(self, configs):
        """机型没有 50 Ω 输入时退为 1 MΩ，并记录该偏离。"""
        from osccal.measure.rise_time import RiseTimeCalibrator

        cmd_osc, cmd_cal, profile = configs
        profile = {**profile, "imp_has_50": False}
        points = [{"channel": "1", "edge_rise_time_s": 150e-12}]
        instance = build(RiseTimeCalibrator, (cmd_osc, cmd_cal, profile), points)
        instance._read_meas = lambda key, trigger=True: 1e-9
        instance.run()
        record = instance.results[0]
        assert record["impedance"] == "1M"
        assert "impedance_note" in record


class TestRegistryM5:
    def test_new_items_registered(self):
        from osccal.measure.registry import RUNNERS

        assert "input_impedance" in RUNNERS
        assert "enob" in RUNNERS

    def test_every_spec_item_now_implemented_except_manual(self):
        from osccal.measure.registry import ITEM_ORDER, RUNNERS

        unimplemented = [name for name in ITEM_ORDER if name not in RUNNERS]
        assert unimplemented == [], f"仍有未实现项目: {unimplemented}"
