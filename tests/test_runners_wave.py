"""M4' 三个波形型项目的行为用例（timebase_error / delta_t / random_noise）。

波形与标量测量全部打桩，只验证指令序列、两种时基算法与噪声统计。
"""

import math
from pathlib import Path

import pytest

import osccal.measure.random_noise as rn_module
from osccal.core.waveform import Waveform, WaveformPreamble
from osccal.measure.delta_t import DeltaTimeCalibrator
from osccal.measure.random_noise import RandomNoiseCalibrator
from osccal.measure.timebase import TimebaseErrorCalibrator

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
    import json

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


def build(cls, configs, points, options=None):
    cmd_osc, cmd_cal, characteristics = configs
    instance = cls(
        StubInstrument(),
        StubInstrument(),
        cmd_osc,
        cmd_cal,
        characteristics,
        "1",
        "9530",
        points,
        options,
    )
    instance.init_devices = lambda: None
    instance.setup_channel = lambda: None
    instance.setup_measurement = lambda key, trigger=True: None
    return instance


def sine_wave(freq_hz, x_increment, samples=300, amplitude=0.5, true_increment=None):
    """构造一段与示波器标称时间轴可能不一致的正弦波形。"""
    true_inc = true_increment if true_increment is not None else x_increment
    volts = [
        amplitude * math.sin(2 * math.pi * freq_hz * (index * true_inc)) for index in range(samples)
    ]
    seconds = [index * x_increment for index in range(samples)]
    return Waveform(
        codes=[],
        volts=volts,
        seconds=seconds,
        preamble=WaveformPreamble(x_increment=x_increment, nr_pt=samples),
    )


class TestTimebaseConsistency:
    """采集时间轴自检：数据推算频率与示波器读数不一致时，拟合法必须判为不适用。"""

    def _point(self):
        return [
            {
                "channel": "1",
                "timebase_s_per_div": 8e-7,
                "period_on_screen_s": 3.33e-4,
                "signal_freq_hz": 300e3,
            }
        ]

    def test_implied_frequency_uses_declared_time_axis(self):
        wave = sine_wave(300e3, 0.8e-9, samples=4000)
        implied = TimebaseErrorCalibrator.implied_frequency(wave)
        # 过零计数受量化影响，只做粗估；精确判定由拟合频率与读数比对完成
        assert implied == pytest.approx(300e3, rel=0.05)

    def test_inconsistent_axis_marks_fit_not_applicable(self, configs):
        # 实机现象：实际采样间隔约为标称的 8.5 倍（抽点后仍按屏幕标称给 XINcr）
        instance = build(TimebaseErrorCalibrator, configs, self._point())
        instance._read_meas = lambda key, trigger=True: 300e3
        instance._read_waveform = lambda samples, fresh=True: sine_wave(
            300e3, 0.8e-9, samples=4000, true_increment=6.8e-9
        )
        instance.run()

        record = instance.results[0]
        assert record["fit_note"] is not None
        assert "不一致" in record["fit_note"]
        assert record["rel_error_fit"] is None
        assert record["fit_ppm"] is None
        assert record["fit_implied_freq_hz"] is not None

    def test_consistent_axis_still_produces_fit(self, configs):
        instance = build(TimebaseErrorCalibrator, configs, self._point())
        instance._read_meas = lambda key, trigger=True: 300e3
        instance._read_waveform = lambda samples, fresh=True: sine_wave(300e3, 0.8e-9, samples=4000)
        instance.run()

        record = instance.results[0]
        assert record["fit_note"] is None
        assert record["rel_error_fit"] is not None


class TestTimebaseOrder:
    def test_record_length_pinned_before_timebase(self, configs):
        """记录长度必须在采集/时基设置之前固定，否则波形与新 XINcr 不匹配。"""
        points = [{"channel": "1", "timebase_s_per_div": 1e-4, "signal_freq_hz": 3000.0}]
        instance = build(TimebaseErrorCalibrator, configs, points)
        instance._read_meas = lambda key, trigger=True: 3000.0
        instance._read_waveform = lambda samples, fresh=True: sine_wave(3000.0, 1e-6)
        instance.run()

        written = instance.inst_osc.written
        record_index = next(i for i, cmd in enumerate(written) if "RECORDLENGTH" in cmd)
        scale_index = next(i for i, cmd in enumerate(written) if "HOR:SCALE" in cmd)
        assert record_index < scale_index


class TestTimebaseMethodSelection:
    """方案只选一种时基方法时，另一方法不得执行，报告列置空并注明。"""

    def _point(self):
        return [
            {
                "channel": "1",
                "timebase_s_per_div": 1e-4,
                "period_on_screen_s": 3.33e-4,
                "signal_freq_hz": 3000.0,
            }
        ]

    def test_frequency_only_skips_waveform(self, configs):
        options = {"methods": ["frequency_readout"]}
        instance = build(TimebaseErrorCalibrator, configs, self._point(), options)
        instance._read_meas = lambda key, trigger=True: 3000.0
        instance._read_waveform = lambda *args, **kwargs: pytest.fail("未选拟合法时不得读波形")
        instance.run()

        record = instance.results[0]
        assert record["rel_ppm"] == pytest.approx(0.0, abs=1e-9)
        assert record["fit_ppm"] is None
        assert record["fit_note"] == "方案未选拟合法"
        assert record["methods_selected"] == ["frequency_readout"]

    def test_fit_only_marks_frequency_not_applicable(self, configs):
        options = {"methods": ["waveform_fit"]}
        instance = build(TimebaseErrorCalibrator, configs, self._point(), options)
        instance._read_meas = lambda key, trigger=True: 3000.0
        instance._read_waveform = lambda samples, fresh=True: sine_wave(3000.0, 1e-6)
        instance.run()

        record = instance.results[0]
        assert record["rel_ppm"] is None
        assert record["rel_error_fit"] is not None
        assert record["fit_note"] is None
        assert record["methods_selected"] == ["waveform_fit"]


class TestTimebaseError:
    def test_frequency_method_sign_and_scale(self, configs):
        points = [
            {
                "channel": "1",
                "timebase_s_per_div": 1e-4,
                "period_on_screen_s": 3.33e-4,
                "signal_freq_hz": 3000.0,
            }
        ]
        instance = build(TimebaseErrorCalibrator, configs, points)
        instance._read_meas = lambda key, trigger=True: 3000.0 * (1 - 2e-6)  # 时基偏慢 2 ppm
        instance._read_waveform = lambda samples, fresh=True: sine_wave(3000.0, 1e-6)
        instance.run()

        record = instance.results[0]
        assert record["rel_ppm"] == pytest.approx(2.0, abs=1e-6)
        assert record["rel_error_fit"] == pytest.approx(0.0, abs=1e-6)

    def test_fit_detects_timebase_skew(self, configs):
        points = [
            {
                "channel": "1",
                "timebase_s_per_div": 1e-4,
                "period_on_screen_s": 3.33e-4,
                "signal_freq_hz": 3000.0,
            }
        ]
        instance = build(TimebaseErrorCalibrator, configs, points)
        instance._read_meas = lambda key, trigger=True: 3000.0
        # 实际采样间隔比标称快 0.1% → 拟合频率偏高 → δT ≈ −1e-3
        instance._read_waveform = lambda samples, fresh=True: sine_wave(
            3000.0, 1e-6, true_increment=1.001e-6
        )
        instance.run()

        record = instance.results[0]
        assert record["rel_ppm"] == pytest.approx(0.0, abs=1e-9)
        assert record["rel_error_fit"] == pytest.approx(-0.001, rel=1e-3)
        assert record["fit_frequency_hz"] == pytest.approx(3003.0, rel=1e-3)

    def test_both_methods_always_recorded_when_waveform_available(self, configs):
        points = [{"channel": "1", "timebase_s_per_div": 1e-4, "signal_freq_hz": 3000.0}]
        instance = build(TimebaseErrorCalibrator, configs, points)
        instance._read_meas = lambda key, trigger=True: 3000.0
        instance._read_waveform = lambda samples, fresh=True: sine_wave(3000.0, 1e-6)
        instance.run()
        record = instance.results[0]
        assert record["rel_error_fit"] is not None
        assert record["fit_frequency_hz"] is not None

    def test_without_waveform_capability_only_frequency_method(self, configs):
        cmd_osc, cmd_cal, profile = configs
        trimmed = dict(cmd_osc)
        trimmed["actions"] = {
            name: act
            for name, act in cmd_osc["actions"].items()
            if not name.startswith("query_wave")
        }
        instance = TimebaseErrorCalibrator(
            StubInstrument(),
            StubInstrument(),
            trimmed,
            cmd_cal,
            profile,
            "1",
            "9530",
            [{"channel": "1", "timebase_s_per_div": 1e-4, "signal_freq_hz": 3000.0}],
        )
        instance.init_devices = lambda: None
        instance.setup_channel = lambda: None
        instance.setup_measurement = lambda key, trigger=True: None
        instance._read_meas = lambda key, trigger=True: 3000.0
        instance.run()
        assert instance.results[0]["fit_frequency_hz"] is None


class TestDeltaTime:
    def test_m_periods_compared_with_standard(self, configs):
        points = [
            {
                "channel": "1",
                "timebase_s_per_div": 1e-4,
                "period_on_screen_s": 4e-4,
                "signal_freq_hz": 2500.0,
            }
        ]
        instance = build(DeltaTimeCalibrator, configs, points)
        instance._read_meas = lambda key, trigger=True: 3.96e-4  # 单周期读数偏低 1%
        instance.run()

        record = instance.results[0]
        assert record["periods_m"] == 2
        assert record["time_standard_s"] == pytest.approx(8e-4)
        assert record["time_measured_s"] == pytest.approx(7.92e-4)
        assert record["error_pct"] == pytest.approx(-1.0)

    def test_uses_square_wave_per_spec(self, configs):
        points = [
            {
                "channel": "1",
                "timebase_s_per_div": 1e-4,
                "period_on_screen_s": 4e-4,
                "signal_freq_hz": 2500.0,
            }
        ]
        instance = build(DeltaTimeCalibrator, configs, points)
        instance._read_meas = lambda key, trigger=True: 4e-4
        instance.run()
        cal = instance.inst_calibrator
        assert any("SHAP SQU" in cmd for cmd in cal.written)

    def test_no_points_reports_gap(self, configs):
        instance = build(DeltaTimeCalibrator, configs, [])
        instance.run()
        assert instance.results == []


class TestRandomNoise:
    def test_std_matches_known_samples(self):
        values = [1.0, -1.0, 1.0, -1.0]
        assert RandomNoiseCalibrator.standard_deviation(values) == pytest.approx(
            1.1547005, rel=1e-6
        )

    def test_rejects_too_few_samples(self):
        with pytest.raises(ValueError, match="样本点不足"):
            RandomNoiseCalibrator.standard_deviation([1.0])

    def test_prompts_for_matched_load(self, configs, monkeypatch, capsys):
        prompts: list[str] = []
        monkeypatch.setattr(
            rn_module.click, "prompt", lambda *a, **k: prompts.append(a[0] if a else "") or ""
        )
        points = [{"channel": "1", "vertical_scale": 0.001}]
        instance = build(RandomNoiseCalibrator, configs, points)
        instance._read_waveform = lambda samples, fresh=True: Waveform(
            codes=[], volts=[0.001, -0.001, 0.001, -0.001], seconds=[], preamble=WaveformPreamble()
        )
        instance.run()
        assert prompts, "接入匹配负载前必须暂停并提示"
        assert "50 Ω 匹配负载" in capsys.readouterr().out

    def test_noise_normalised_to_full_scale(self, configs, monkeypatch):
        monkeypatch.setattr(rn_module.click, "prompt", lambda *a, **k: "")
        points = [{"channel": "1", "vertical_scale": 0.001}]
        instance = build(RandomNoiseCalibrator, configs, points)
        instance._read_waveform = lambda samples, fresh=True: Waveform(
            codes=[],
            volts=[0.001, -0.001] * 500,
            seconds=[],
            preamble=WaveformPreamble(),
        )
        instance.run()

        record = instance.results[0]
        assert record["full_scale_v"] == pytest.approx(0.008)  # 1 mV/div × 8 格
        # 样本标准差（分母 n−1）：±1 mV 交替 1000 点 → ≈1.0005 mV
        assert record["noise_v"] == pytest.approx(0.001, rel=1e-3)
        assert record["error_pct"] == pytest.approx(12.5, rel=1e-3)

    def test_sets_single_shot_sample_mode(self, configs, monkeypatch):
        monkeypatch.setattr(rn_module.click, "prompt", lambda *a, **k: "")
        points = [{"channel": "1", "vertical_scale": 0.001}]
        instance = build(RandomNoiseCalibrator, configs, points)
        instance._read_waveform = lambda samples, fresh=True: Waveform(
            codes=[], volts=[0.0, 0.001], seconds=[], preamble=WaveformPreamble()
        )
        instance.run()
        written = " ".join(instance.inst_osc.written)
        assert "ACQ:STOPA" in written, "应设为单次采集后停止"
