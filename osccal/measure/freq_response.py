"""频率响应、频带宽度（JJF 1057-2026 7.6）。

规范方法：正弦源、直流耦合、偏置零；以 **50 kHz** 为基准读 V₀（居中覆盖约
80% 屏幕）；保持输出幅度不变，改变频率读 V_k，频率响应 G_k = V_k / V₀；
在标称带宽频率处 G ≥ 0.707 则带宽不小于标称值，否则下调频率至 G = 0.707，
对应频率即为带宽。

注意：9500B 稳幅正弦的**可用幅度随频率下降**，本实现统一用 0.5 Vpp 的固定幅度
并在记录里写明，避免高频点因幅度过大而超出标准器能力（实机验证时按 9530 头
的实际幅度/频率曲线再调这个常量）。
"""

import math
import time

from rich.progress import Progress

from osccal.measure.base import BaseCalibrator, console, ensure_output_off

#: 测试幅度（峰峰值）。高频段 9500B 的可用幅度远低于低频，统一取小值更稳。
AMPLITUDE_VPP = 0.5
#: 目标屏占比：规范要求"居中覆盖约 80% 屏幕"，幅值固定时由挡位反推。
TARGET_SCREEN_FRACTION = 0.8
#: 半功率判据。
HALF_POWER = 0.707


class FreqResponseCalibrator(BaseCalibrator):
    """频率响应曲线 + 频带宽度。"""

    title = "频率响应、频带宽度（7.6）"

    def _pick_vertical_scale(self) -> float:
        """按固定幅度挑一个让波形占约 80% 屏幕的垂直档位。"""
        vertical_div = float(self.profile.get("vertical_div", 8))
        scales = self.profile.get("vertical_scales") or [0.1]
        want = AMPLITUDE_VPP / (TARGET_SCREEN_FRACTION * vertical_div)
        return min(scales, key=lambda scale: abs(scale - want))

    def _measure_amplitude(self, frequency_hz: float) -> float:
        self._write_calibrator("set_freq", frequency_hz)
        time.sleep(0.5)
        return self._read_meas("meas_amp") * self._get_meas_amp_scale()

    @staticmethod
    def bandwidth_from_response(
        frequencies: list[float], responses: list[float], target: float = HALF_POWER
    ) -> float | None:
        """在相邻频点间按对数频率插值求半功率点；未出现则返回 None。"""
        for index in range(1, len(frequencies)):
            high, low = responses[index - 1], responses[index]
            if high >= target > low:
                f_high, f_low = frequencies[index - 1], frequencies[index]
                if high == low:  # pragma: no cover - 防御
                    return f_low
                share = (high - target) / (high - low)
                log_high = math.log10(f_high)
                log_low = math.log10(f_low)
                return 10 ** (log_high + share * (log_low - log_high))
        return None

    @ensure_output_off
    def run(self):
        self.print_title(self.title)
        self.init_devices()
        self.setup_channel()
        self.setup_measurement("meas_amp")

        if not self.points:
            console.print("[yellow]⚠ 本轮没有可执行的校准点[/yellow]")
            return

        scale = self._pick_vertical_scale()
        self._apply_impedance("1M")
        self._write_osc("set_vertical_scale", self.channel, scale)
        self._write_osc("set_coupling", self.channel, "DC")
        if "set_vertical_position" in self.cmd_osc["actions"]:
            self._write_osc("set_vertical_position", self.channel, 0.0)
        self._nudge_trigger_level(scale)

        self._write_calibrator("set_shap", "SIN")
        self._write_calibrator("set_volt", AMPLITUDE_VPP)
        self._write_calibrator("set_output", "ON")
        time.sleep(1.0)

        table = self.make_table(
            "频率响应 / 频带宽度校准结果",
            [
                {"name": "序号"},
                {"name": "通道", "justify": "center"},
                {"name": "频率", "justify": "left"},
                {"name": "幅值(Vpp)"},
                {"name": "相对响应 G"},
                {"name": "备注", "justify": "left"},
            ],
        )

        frequencies: list[float] = []
        responses: list[float] = []
        reference: float | None = None

        with Progress() as progress:
            task = progress.add_task("频率响应", total=len(self.points))
            for index, point in enumerate(self.points, start=1):
                frequency = float(point["frequency_hz"])
                measured = self._measure_amplitude(frequency)
                if reference is None:
                    reference = measured
                response = measured / reference if reference else float("nan")
                frequency_hz = frequency
                frequencies.append(frequency_hz)
                responses.append(response)

                note = "基准" if index == 1 else ""
                if response < HALF_POWER and not note:
                    note = "低于 −3 dB"
                self.results.append(
                    {
                        "index": index,
                        "channel": self.channel,
                        "frequency_hz": frequency_hz,
                        "amplitude_vpp": measured,
                        "response": response,
                        "vertical_scale": scale,
                        "test_amplitude_vpp": AMPLITUDE_VPP,
                    }
                )
                self.add_result_row(
                    table,
                    [
                        index,
                        f"CH{self.channel}",
                        self._format_frequency(frequency_hz),
                        f"{measured:.6g}",
                        f"{response:.4f}",
                        note,
                    ],
                )
                progress.update(task, advance=1)

        console.print(table)
        self._report_bandwidth(frequencies, responses)

    def _report_bandwidth(self, frequencies: list[float], responses: list[float]) -> None:
        bandwidth = self.bandwidth_from_response(frequencies, responses)
        if bandwidth is None:
            top = max(frequencies) if frequencies else 0.0
            console.print(
                f"[cyan]频带宽度[/cyan] ≥ {self._format_frequency(top)}"
                "（测试范围内未出现 −3 dB 点）"
            )
        else:
            console.print(f"[cyan]频带宽度[/cyan] ≈ {self._format_frequency(bandwidth)}")
        self.results.append(
            {
                "channel": self.channel,
                "summary": "bandwidth",
                "bandwidth_hz": bandwidth,
                "max_frequency_hz": max(frequencies) if frequencies else None,
            }
        )

    @staticmethod
    def _format_frequency(value: float) -> str:
        if value >= 1e9:
            return f"{value / 1e9:.4g} GHz"
        if value >= 1e6:
            return f"{value / 1e6:.4g} MHz"
        if value >= 1e3:
            return f"{value / 1e3:.4g} kHz"
        return f"{value:.4g} Hz"
