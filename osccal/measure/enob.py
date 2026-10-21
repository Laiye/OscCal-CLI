"""动态有效位数（JJF 1057-2026 7.7 + 附录 E）。

规范方法：通道采集速率取最高，采样间隔 τ = 1/f_s，采集点数 N ≥ 1000；
输入频率 f = f_s × n / N（n 为记录内所含整周期数，**N 与 n 不能有公因子**）；
正弦峰值约覆盖量程 95%（90%~100%）；采集两个以上周期后按附录 E 做四参数
最小二乘拟合，用拟合残差（噪声与失真均方根 E_r）按式 (15) 计算

    ENOB = log2( V₀ / (√12 · E_r) )，V₀ 为通道量程。

采样率在运行期用 `ACQuire:SRATe?` 读回，不在配置里写死：同一份点表在不同
时基/记录长度下都能用。若算出的频率超出标准器能力，按"无效"记录并写明原因。
"""

import math
import time

from rich.progress import Progress

from osccal.core.fitting import FitError, fit_sine
from osccal.measure.base import BaseCalibrator, console, ensure_output_off

#: 峰值占量程的比例（规范：90%~100%，取 95%）。
PEAK_FRACTION = 0.95
#: 采集点数与整数周期数（必须互质，保证记录正好覆盖 n 个周期）。
DEFAULT_SAMPLES = 1000
#: 记录长度固定值：采样率由它与时基共同决定，固定才能保证结果可复现。
RECORD_LENGTH = 10000
DEFAULT_CYCLES = 7
#: ENOB 测量使用的垂直档位：0.2 V/div × 8 格 = 1.6 V 量程，峰值约 1.52 Vpp。
VERTICAL_SCALE = 0.2


class EnobCalibrator(BaseCalibrator):
    """动态有效位数：正弦拟合残差 → ENOB。"""

    title = "动态有效位数（7.7）"

    @staticmethod
    def _parse_scalar(raw) -> float:
        """从 `:HOR:SAMPLER 250.0000E+6` 这类带前导助记符的响应里取出数值。"""
        for token in reversed(str(raw).replace("\n", " ").split()):
            try:
                return float(token)
            except ValueError:
                continue
        raise ValueError(f"无法解析数值: {raw!r}")

    def _pin_record_length(self, length: int) -> int:
        """固定记录长度：采样率 = 记录长度 ÷ (10 × 时基)，不固定就不可复现。"""
        if "set_record_length" in self.cmd_osc.get("actions", {}):
            self._write_osc("set_record_length", length)
        return length

    def _timebase_for_max_sample_rate(self, record_length: int) -> float:
        """反算让示波器跑到最高采样率的水平挡位（取不大于目标值的最近档位）。"""
        horizontal_div = float(self.profile.get("horizontal_div", 10))
        max_rate = float(self.profile.get("max_sample_rate_hz", 0) or 0)
        scales = sorted(self.profile.get("horizontal_scales") or [1e-9])
        if max_rate <= 0 or record_length <= 0:
            return min(scales)
        target = record_length / max_rate / horizontal_div
        lower = [scale for scale in scales if scale <= target]
        return max(lower) if lower else min(scales)

    def _measure_point(self, point: dict) -> dict:
        samples = int(point.get("samples_n") or DEFAULT_SAMPLES)
        cycles = int(point.get("integer_cycles_n") or DEFAULT_CYCLES)
        if math.gcd(samples, cycles) != 1:
            raise ValueError(f"N={samples} 与 n={cycles} 不能有公因子")

        vertical_div = float(self.profile.get("vertical_div", 8))
        full_scale = VERTICAL_SCALE * vertical_div
        amplitude = PEAK_FRACTION * full_scale

        # 规范 7.7 要求"采样速率最高"：先固定记录长度，再按
        # R ÷ f_max ÷ 水平格数 反算时基，最后回读采样率校验（不达标不照算）。
        record_length = self._pin_record_length(RECORD_LENGTH)
        timebase_used = self._set_timebase(
            self._timebase_for_max_sample_rate(record_length)
        ) or self._timebase_for_max_sample_rate(record_length)
        sample_rate = self._parse_scalar(self._query_osc("query_sample_rate"))
        max_sample_rate = float(self.profile.get("max_sample_rate_hz", 0) or 0)
        if sample_rate <= 0:
            raise ValueError("采样率无效")
        if max_sample_rate > 0 and sample_rate < 0.9 * max_sample_rate:
            console.print(
                f"[yellow]⚠ 采样率 {sample_rate / 1e9:.3g} GS/s 未达机型上限 "
                f"{max_sample_rate / 1e9:.3g} GS/s（记录 {record_length} 点）[/yellow]"
            )
        frequency = sample_rate * cycles / samples

        self._apply_impedance("1M")
        self._write_osc("set_vertical_scale", self.channel, VERTICAL_SCALE)
        self._write_osc("set_coupling", self.channel, "DC")
        if "set_vertical_position" in self.cmd_osc["actions"]:
            self._write_osc("set_vertical_position", self.channel, 0.0)
        self._nudge_trigger_level(VERTICAL_SCALE)
        if "set_acquisition_mode" in self.cmd_osc["actions"]:
            self._write_osc(
                "set_acquisition_mode", self.cmd_osc["keyword"]["acquisition_mode_sample"]
            )

        self._write_calibrator("set_shap", "SIN")
        self._write_calibrator("set_freq", frequency)
        self._write_calibrator("set_volt", amplitude)
        self._write_calibrator("set_output", "ON")
        time.sleep(1.0)

        record = {
            "channel": self.channel,
            "vertical_scale": VERTICAL_SCALE,
            "full_scale_v": full_scale,
            "sample_rate_sa_s": sample_rate,
            "record_length": record_length,
            "timebase_s_per_div": timebase_used,
            "samples_n": samples,
            "integer_cycles_n": cycles,
            "signal_freq_hz": frequency,
            "signal_amplitude_vpp": amplitude,
        }

        wave = self._read_waveform(samples)
        record["acquired_samples"] = wave.samples
        try:
            fit = fit_sine(wave.seconds, wave.volts)
        except FitError as exc:
            record.update({"enob": None, "rms_error_v": None, "note": f"拟合失败: {exc}"})
            return record

        rms_error = fit.rms_error
        if rms_error <= 0:
            record.update({"enob": None, "rms_error_v": rms_error, "note": "残差为零"})
            return record

        enob = math.log2(full_scale / (math.sqrt(12.0) * rms_error))
        record.update(
            {
                "enob": enob,
                "rms_error_v": rms_error,
                "fit_frequency_hz": fit.frequency,
                "fit_amplitude_v": fit.amplitude,
                "note": "",
            }
        )
        return record

    @ensure_output_off
    def run(self):
        self.print_title(self.title)
        self.init_devices()
        self.setup_channel()

        if not self.points:
            console.print("[yellow]⚠ 本轮没有可执行的校准点[/yellow]")
            return

        table = self.make_table(
            "动态有效位数校准结果",
            [
                {"name": "序号"},
                {"name": "通道", "justify": "center"},
                {"name": "量程(V)"},
                {"name": "信号频率", "justify": "left"},
                {"name": "信号幅度(Vpp)"},
                {"name": "残差均方根(V)"},
                {"name": "ENOB(bits)"},
                {"name": "备注", "justify": "left"},
            ],
        )

        with Progress() as progress:
            task = progress.add_task("动态有效位数", total=len(self.points))
            for index, point in enumerate(self.points, start=1):
                record = self._measure_point(point)
                self.results.append({"index": index, **record})
                enob = record["enob"]
                self.add_result_row(
                    table,
                    [
                        index,
                        f"CH{self.channel}",
                        f"{record['full_scale_v']:g}",
                        self._format_frequency(record["signal_freq_hz"]),
                        f"{record['signal_amplitude_vpp']:.4g}",
                        "—" if record["rms_error_v"] is None else f"{record['rms_error_v']:.4g}",
                        "无效" if enob is None else f"{enob:.2f}",
                        record["note"] or "",
                    ],
                )
                progress.update(task, advance=1)
        console.print(table)

    @staticmethod
    def _format_frequency(value: float) -> str:
        if value >= 1e6:
            return f"{value / 1e6:.4g} MHz"
        if value >= 1e3:
            return f"{value / 1e3:.4g} kHz"
        return f"{value:.4g} Hz"
