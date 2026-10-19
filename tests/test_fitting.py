"""正弦最小二乘拟合（core/fitting.py）的守护用例。"""

import math

import pytest

from osccal.core.fitting import FitError, enob, estimate_frequency, fit_sine

SAMPLE_RATE = 50e6
SAMPLES = 1000


def _synth(amplitude, freq, phase, dc, noise_pp=0.0, noise_cycles=7):
    """构造正弦样本；噪声用确定性伪随机，避免测试随机失败。"""
    times = [index / SAMPLE_RATE for index in range(SAMPLES)]
    values = []
    state = 12345
    for t in times:
        value = amplitude * math.sin(2 * math.pi * freq * t + phase) + dc
        if noise_pp:
            state = (1103515245 * state + 12345) % (2**31)
            value += noise_pp * (state / 2**31 - 0.5)
        values.append(value)
    return times, values


class TestEstimateFrequency:
    def test_matches_known_frequency(self):
        times, values = _synth(1.0, 1e6, 0.0, 0.0)
        assert estimate_frequency(times, values) == pytest.approx(1e6, rel=1e-3)

    def test_rejects_flat_signal(self):
        times = [index / SAMPLE_RATE for index in range(100)]
        with pytest.raises(FitError, match="穿越"):
            estimate_frequency(times, [1.0] * 100)


class TestFitSine:
    @pytest.mark.parametrize("freq", [1e6, 5e6, 12.5e6])
    def test_noiseless_recovery(self, freq):
        times, values = _synth(0.5, freq, 0.3, 0.02)
        fit = fit_sine(times, values)
        assert fit.amplitude == pytest.approx(0.5, rel=1e-6)
        assert fit.frequency == pytest.approx(freq, rel=1e-6)
        assert fit.dc == pytest.approx(0.02, abs=1e-6)
        assert fit.rms_error < 1e-9

    def test_phase_recovery(self):
        times, values = _synth(0.5, 2e6, 0.7, 0.0)
        fit = fit_sine(times, values)
        assert fit.phase == pytest.approx(0.7, abs=1e-4)

    def test_noisy_recovery(self):
        times, values = _synth(0.5, 3e6, 0.1, 0.05, noise_pp=0.01)
        fit = fit_sine(times, values)
        assert fit.amplitude == pytest.approx(0.5, rel=1e-3)
        assert fit.frequency == pytest.approx(3e6, rel=1e-4)
        assert fit.dc == pytest.approx(0.05, abs=1e-3)
        # 噪声峰峰值 0.01 → 均方根约 0.01/√12 ≈ 0.0029
        assert 0.001 < fit.rms_error < 0.005

    def test_custom_freq_guess(self):
        times, values = _synth(1.0, 1e6, 0.0, 0.0)
        fit = fit_sine(times, values, freq_guess=1.05e6, search_span=0.2)
        assert fit.frequency == pytest.approx(1e6, rel=1e-5)

    def test_rejects_too_few_samples(self):
        with pytest.raises(FitError, match="数量不足"):
            fit_sine([0.0, 1e-6, 2e-6], [0.0, 1.0, 0.0])

    def test_rejects_length_mismatch(self):
        with pytest.raises(FitError, match="长度不一致"):
            fit_sine([index * 1e-9 for index in range(20)], [0.0] * 10)

    def test_rejects_non_finite(self):
        times, values = _synth(1.0, 1e6, 0.0, 0.0)
        values[5] = math.nan
        with pytest.raises(FitError, match="非有限值"):
            fit_sine(times, values)

    def test_rejects_unordered_time(self):
        times, values = _synth(1.0, 1e6, 0.0, 0.0)
        times[3], times[4] = times[4], times[3]
        with pytest.raises(FitError, match="严格递增"):
            fit_sine(times, values)

    def test_rejects_non_positive_guess(self):
        times, values = _synth(1.0, 1e6, 0.0, 0.0)
        with pytest.raises(FitError, match="频率初值"):
            fit_sine(times, values, freq_guess=-1.0)


class TestEnob:
    def test_enob_from_residual(self):
        times, values = _synth(1.0, 1e6, 0.0, 0.0, noise_pp=0.002)
        fit = fit_sine(times, values)
        bits = enob(fit, full_scale_volts=8.0)
        # 8 V 满量程、残差约 5.8e-4 V → ENOB ≈ log2(8/(3.46×5.8e-4)) ≈ 12
        assert 10 < bits < 14

    def test_rejects_zero_residual(self):
        times, values = _synth(1.0, 1e6, 0.0, 0.0)
        fit = fit_sine(times, values)
        with pytest.raises(FitError, match="残差为零"):
            enob(fit, full_scale_volts=8.0)

    def test_rejects_bad_full_scale(self):
        times, values = _synth(1.0, 1e6, 0.0, 0.0, noise_pp=0.002)
        fit = fit_sine(times, values)
        with pytest.raises(FitError, match="满量程"):
            enob(fit, full_scale_volts=0.0)
