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
import statistics
import time

from rich.progress import Progress

from osccal.core.methods import describe_methods
from osccal.measure.base import BaseCalibrator, console, ensure_output_off

#: 测试幅度（峰峰值）。高频段 9500B 的可用幅度远低于低频，统一取小值更稳。
AMPLITUDE_VPP = 0.5
#: 目标屏占比：规范要求"居中覆盖约 80% 屏幕"，幅值固定时由挡位反推。
TARGET_SCREEN_FRACTION = 0.8
#: 半功率判据。
HALF_POWER = 0.707
#: 改频后的固定建立时间（秒）；9500B 高频幅度环需要时间建立。
SETTLE_SECONDS = 0.8
#: 每个频点的重复次数与读数收敛判据。
REPEATS = 3
STABLE_TOLERANCE = 0.005
STABLE_INTERVAL = 0.3
STABLE_MAX_WAIT = 6.0
#: 高频段重复性门限：超过该值时只报曲线，不以该频段支撑 CMC。
HIGH_FREQ_STABILITY_HZ = 150e6
STABILITY_LIMIT_PCT = 2.0


class FreqResponseCalibrator(BaseCalibrator):
    """频率响应曲线 + 频带宽度。"""

    title = "频率响应、频带宽度（7.6）"

    def _pick_vertical_scale(self) -> float:
        """按固定幅度挑一个让波形占约 80% 屏幕的垂直档位。"""
        vertical_div = float(self.characteristics.get("vertical_div", 8))
        scales = self.characteristics.get("vertical_scales") or [0.1]
        want = AMPLITUDE_VPP / (TARGET_SCREEN_FRACTION * vertical_div)
        return min(scales, key=lambda scale: abs(scale - want))

    def _timebase_for(self, frequency_hz: float) -> float:
        """让屏上至少显示约 2 个周期；不够就压到机型最低水平档位。"""
        scales = self.characteristics.get("horizontal_scales") or [1e-9]
        target = 0.2 / frequency_hz if frequency_hz > 0 else 1e-3
        return max(min(scales), min(max(scales), target))

    def _configure_trigger(self) -> None:
        """固定触发源/斜率/电平，避免 1 MΩ 高频段触发点漂移。

        实机：不设触发电平、只等 0.5 s 时，1 MΩ 在 350 MHz 附近单次读数可在
        0.42~1.02 之间跳；固定 CH1、上升沿、0 V 后重复性才稳定。
        """
        actions = self.cmd_osc.get("actions", {})
        if "set_trigger_source" in actions:
            self._write_osc("set_trigger_source", self.channel)
        if "set_trigger_slope" in actions:
            self._write_osc("set_trigger_slope", "RIS")
        if "set_trigger_level" in actions:
            action = actions["set_trigger_level"]
            if action.get("args_num", 0) >= 2:
                self._write_osc("set_trigger_level", self.channel, 0.0)
            else:
                self._write_osc("set_trigger_level", 0.0)

    def _measure_amplitude(self, frequency_hz: float) -> dict:
        """改频后等建立，重复多次读数并返回幅度与重复性。"""
        self._set_timebase(self._timebase_for(frequency_hz))
        self._write_calibrator("set_freq", frequency_hz)
        time.sleep(SETTLE_SECONDS)

        readings: list[float] = []
        read_spreads: list[float] = []
        waited_total = 0.0
        for _ in range(REPEATS):
            value, spread, waited = self._read_meas_stable(
                "meas_amp",
                tolerance=STABLE_TOLERANCE,
                interval=STABLE_INTERVAL,
                max_wait=STABLE_MAX_WAIT,
            )
            readings.append(value * self._get_meas_amp_scale())
            read_spreads.append(spread)
            waited_total += waited

        mean = sum(readings) / len(readings)
        stdev = statistics.stdev(readings) if len(readings) > 1 else 0.0
        s_rel = 100.0 * stdev / mean if mean else float("nan")
        return {
            "amplitude": mean,
            "s_rel_pct": s_rel,
            "read_spread_pct": max(read_spreads) if read_spreads else float("nan"),
            "settle_s": SETTLE_SECONDS + waited_total,
            "repeats": REPEATS,
        }

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
        self._configure_trigger()

        if not self.points:
            console.print("[yellow]⚠ 本轮没有可执行的校准点[/yellow]")
            return

        table = self.make_table(
            "频率响应 / 频带宽度校准结果",
            [
                {"name": "序号"},
                {"name": "通道", "justify": "center"},
                {"name": "阻抗", "justify": "center"},
                {"name": "挡位(V/div)"},
                {"name": "频率", "justify": "left"},
                {"name": "幅值(Vpp)"},
                {"name": "相对响应 G"},
                {"name": "重复性(%)"},
                {"name": "备注", "justify": "left"},
            ],
        )

        groups: dict[str, list[dict]] = {}
        for point in self.points:
            groups.setdefault(point.get("impedance", "1M"), []).append(point)

        index = 0
        summaries: list[tuple[list[float], list[float], list[float], str]] = []
        with Progress() as progress:
            task = progress.add_task("频率响应", total=len(self.points))
            for impedance, points in groups.items():
                self._apply_impedance(impedance)
                scale = self._pick_vertical_scale()
                self._write_osc("set_vertical_scale", self.channel, scale)
                self._write_osc("set_coupling", self.channel, "DC")
                if "set_vertical_position" in self.cmd_osc["actions"]:
                    self._write_osc("set_vertical_position", self.channel, 0.0)
                self._configure_trigger()

                self._write_calibrator("set_shap", "SIN")
                self._write_calibrator("set_volt", AMPLITUDE_VPP)
                self._write_calibrator("set_output", "ON")
                time.sleep(1.0)

                frequencies: list[float] = []
                responses: list[float] = []
                stabilities: list[float] = []
                reference: float | None = None
                for point in points:
                    index += 1
                    frequency = float(point["frequency_hz"])
                    measurement = self._measure_amplitude(frequency)
                    measured = float(measurement["amplitude"])
                    is_reference = reference is None
                    if is_reference:
                        reference = measured
                    response = measured / reference if reference else float("nan")
                    s_rel = float(measurement["s_rel_pct"])
                    frequencies.append(frequency)
                    responses.append(response)
                    stabilities.append(s_rel)

                    note = "基准" if is_reference else ""
                    if response < HALF_POWER and not note:
                        note = "低于 −3 dB"
                    self.results.append(
                        {
                            "index": index,
                            "channel": self.channel,
                            "impedance": impedance,
                            "frequency_hz": frequency,
                            "amplitude_vpp": measured,
                            "response": response,
                            "note": note,
                            "vertical_scale": scale,
                            "test_amplitude_vpp": AMPLITUDE_VPP,
                            "s_rel_pct": s_rel,
                            "read_spread_pct": float(measurement["read_spread_pct"]),
                            "settle_s": float(measurement["settle_s"]),
                            "repeats": int(measurement["repeats"]),
                        }
                    )
                    self.add_result_row(
                        table,
                        [
                            index,
                            f"CH{self.channel}",
                            "1 MΩ" if impedance == "1M" else "50 Ω",
                            f"{scale:g}",
                            self._format_frequency(frequency),
                            f"{measured:.6g}",
                            f"{response:.4f}",
                            f"{s_rel:.2f}" if math.isfinite(s_rel) else "—",
                            note,
                        ],
                    )
                    progress.update(task, advance=1)

                summaries.append((frequencies, responses, stabilities, impedance))
        console.print(table)
        console.print(
            f"[dim]执行方法：{describe_methods('freq_response_bandwidth', list(self.methods) or ['sine_sweep_half_power'])}[/dim]"
        )
        for frequencies, responses, stabilities, impedance in summaries:
            self._report_bandwidth(frequencies, responses, stabilities, impedance)

    def _report_bandwidth(
        self,
        frequencies: list[float],
        responses: list[float],
        stabilities: list[float],
        impedance: str,
    ) -> None:
        label = "1 MΩ" if impedance == "1M" else "50 Ω"
        bandwidth = self.bandwidth_from_response(frequencies, responses)
        high_freq_stability = [
            value
            for frequency, value in zip(frequencies, stabilities, strict=True)
            if frequency >= HIGH_FREQ_STABILITY_HZ and math.isfinite(value)
        ]
        max_high_stability = max(high_freq_stability) if high_freq_stability else 0.0
        stability_ok = max_high_stability <= STABILITY_LIMIT_PCT

        if bandwidth is None:
            top = max(frequencies) if frequencies else 0.0
            console.print(
                f"[cyan]频带宽度（{label}）[/cyan] ≥ {self._format_frequency(top)}"
                "（测试范围内未出现 −3 dB 点）"
            )
        else:
            console.print(f"[cyan]频带宽度（{label}）[/cyan] ≈ {self._format_frequency(bandwidth)}")
        if not stability_ok:
            console.print(
                f"[yellow]⚠ {label} ≥150 MHz 最大重复性 {max_high_stability:.1f}%，"
                "不足以支撑该频段的 CMC[/yellow]"
            )
        self.results.append(
            {
                "channel": self.channel,
                "impedance": impedance,
                "summary": "bandwidth",
                "bandwidth_hz": bandwidth,
                "max_frequency_hz": max(frequencies) if frequencies else None,
                "max_high_freq_stability_pct": max_high_stability,
                "stability_ok": stability_ok,
                "stability_limit_pct": STABILITY_LIMIT_PCT,
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
