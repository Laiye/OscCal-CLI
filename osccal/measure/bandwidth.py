import math
import time

from rich.progress import Progress

from osccal.measure.base import BaseCalibrator, console

# -3dB 判决系数（幅度降至参考值的 0.707 倍即视为通过）
_THRESHOLD_RATIO = 0.707


class BandwidthCalibrator(BaseCalibrator):
    def run(self):
        self.print_title("频带宽度")
        self.init_devices()
        self.setup_channel()

        self._write_osc("set_vertical_scale", self.channel, 0.1)
        self._write_osc("set_trigger_source", self.channel)
        self.setup_measurement("meas_amp")
        self._write_osc("set_horizontal_scale", 1e-5)
        self._write_osc("set_acquisition_mode", self.cmd_osc["keyword"]["acquisition_mode_average"])
        self._write_osc("set_number_of_acquisitions", 16)

        self._write_calibrator("set_shap", "SIN")

        if self.profile.get("imp_has_50", False):
            self._setup_signal_impedance("SIN", "50")
        else:
            self._setup_signal_impedance("SIN", "1M")

        self._write_calibrator("set_volt", 0.003)
        self._write_calibrator("set_freq", 50e3)
        self._write_calibrator("set_output", "ON")

        time.sleep(2)

        vertical_div = self.profile.get("vertical_div", 8)
        points = self.profile.get("points", {}).get("bandwidth", [])
        start_bd = int(self.profile.get("bandwidth", 100e6))
        bd_step = int(self.profile.get("bd_step", 10e6))
        max_bd = self._get_probe_max_frequency_hz()
        min_mhz = self.profile.get("calibration_limits", {}).get("bandwidth", {}).get("min_mhz", 0)
        scan_mode = self.profile.get("bd_scan", "bisect")

        columns = [
            {"name": "序号"},
            {"name": "通道"},
            {"name": "挡位(V/div)"},
            {"name": "实测值(MHz)"},
        ]
        table = self.make_table("频带宽度校准结果", columns)

        with Progress() as progress:
            task = progress.add_task("频带宽度校准", total=len(points))
            for i, val in enumerate(points):
                self._write_osc("set_horizontal_scale", 1e-5)
                self._write_osc("set_vertical_scale", self.channel, val)
                self._write_calibrator("set_freq", 50e3)
                self._write_calibrator("set_volt", val * (vertical_div - 2))

                time.sleep(5)

                ref_amp = self._read_meas("meas_amp")

                # 先测起始带宽点，决定向上还是向下搜索（两种扫描模式共用）
                self._write_calibrator("set_freq", start_bd)
                self._write_osc("set_horizontal_scale", 0.5 / start_bd)
                time.sleep(5)
                current_amp = self._read_meas("meas_amp")
                time.sleep(5)

                if scan_mode == "linear":
                    bandwidth_hz = self._scan_linear(
                        ref_amp, start_bd, bd_step, max_bd, current_amp
                    )
                else:
                    bandwidth_hz = self._scan_bisect(
                        ref_amp, start_bd, bd_step, max_bd, current_amp
                    )
                bandwidth_mhz = bandwidth_hz * 1e-6

                bandwidth_display = round(bandwidth_mhz, 2)
                if min_mhz and bandwidth_mhz < min_mhz:
                    bandwidth_display = f"[red bold]{bandwidth_display}[/red bold]"

                row_data = [i + 1, f"CH{self.channel}", val, bandwidth_display]
                table.add_row(*[str(v) for v in row_data])

                self.results.append(
                    {
                        "index": i + 1,
                        "channel": self.channel,
                        "scale": val,
                        "bandwidth_mhz": bandwidth_mhz,
                    }
                )

                progress.update(task, advance=1)

        console.print(table)
        self._write_calibrator("set_output", "OFF")

    # ── 单步测量（延时结构与原线性扫描完全一致，不允许改动） ─────────────

    def _measure_amp_at(self, freq_hz: float) -> float:
        """切换到指定频率并测量幅度。

        保持原方案的稳定流程不变：set_freq + set_scale → sleep(5) → read → sleep(5)，
        以防校准仪与示波器之间出现状态错位。
        """
        self._write_calibrator("set_freq", freq_hz)
        self._write_osc("set_horizontal_scale", 0.5 / freq_hz)
        time.sleep(5)
        amp = self._read_meas("meas_amp")
        time.sleep(5)
        return amp

    # ── 线性扫描（原方案，profile.bd_scan="linear" 时启用） ─────────────

    def _scan_linear(self, ref_amp, start_bd, bd_step, max_bd, current_amp) -> int:
        threshold = ref_amp * _THRESHOLD_RATIO
        if current_amp >= threshold:
            current_bd = start_bd
            while current_amp >= threshold:
                current_bd = current_bd + bd_step
                if current_bd > max_bd:
                    break
                current_amp = self._measure_amp_at(current_bd)
            return int(current_bd - bd_step)
        # 起始带宽处已低于 -3dB：向下线性扫描找通过点
        console.print(
            f"[yellow]⚠[/yellow] 起始带宽 {start_bd * 1e-6:.0f} MHz 处幅度已低于 -3dB，"
            f"向下扫描定位带宽点..."
        )
        current_bd = start_bd
        while current_amp < threshold and current_bd > 50e3:
            current_bd = current_bd - bd_step
            if current_bd <= 50e3:
                break
            current_amp = self._measure_amp_at(current_bd)
        if current_amp < threshold:
            console.print(
                f"[red]⚠[/red] 在 {50e3 * 1e-6:.0f} MHz 以上未找到 -3dB 通过点，"
                f"实测带宽可能低于 {current_bd * 1e-6:.1f} MHz"
            )
        return int(current_bd)

    # ── 二分扫描（默认，profile.bd_scan="bisect"） ──────────────────────
    #
    # 频响随频率单调递减，-3dB 交叉点可用"指数粗定位 + 栅格二分"快速求根：
    # 测量次数从 范围/步长 降为 O(log2(范围/步长))；每一步的延时结构不变。

    def _scan_bisect(self, ref_amp, start_bd, bd_step, max_bd, current_amp) -> int:
        threshold = ref_amp * _THRESHOLD_RATIO
        floor_freq = 50e3

        if max_bd <= start_bd:
            # 校准仪探头最高频率不高于起始带宽：无法向上探测，报告起始带宽
            return int(start_bd)

        if current_amp >= threshold:
            # 起始点通过：向上指数粗定位（索引 1,2,4,8... 倍步进）
            max_idx = max(1, (max_bd - start_bd) // bd_step)
            lo_idx = 0  # start_bd 已测得通过
            hi_idx = None
            probe_idx = 1
            while probe_idx <= max_idx:
                amp = self._measure_amp_at(start_bd + probe_idx * bd_step)
                if amp >= threshold:
                    lo_idx = probe_idx
                    probe_idx *= 2
                else:
                    hi_idx = probe_idx
                    break
            if hi_idx is None:
                # 步进探测越过上限仍未失败：在上限点确认一次
                amp = self._measure_amp_at(start_bd + max_idx * bd_step)
                lo_idx = max_idx if amp >= threshold else lo_idx
                hi_idx = None if amp >= threshold else max_idx
            if hi_idx is None:
                # 直至探头最高频率仍通过：报告最后一次通过的频率（下界）
                return int(start_bd + lo_idx * bd_step)
        else:
            # 起始点已衰减：向下指数粗定位（索引 -1,-2,-4... 倍步进）
            console.print(
                f"[yellow]⚠[/yellow] 起始带宽 {start_bd * 1e-6:.0f} MHz 处幅度已低于 -3dB，"
                f"向下搜索定位带宽点..."
            )
            min_idx = math.ceil((floor_freq - start_bd) / bd_step)  # 允许的最低索引（可为负）
            hi_idx = 0  # start_bd 已测得失败
            lo_idx = None
            probe_idx = -1
            while True:
                if probe_idx < min_idx:
                    probe_idx = min_idx
                if start_bd + probe_idx * bd_step < floor_freq:
                    break
                amp = self._measure_amp_at(start_bd + probe_idx * bd_step)
                if amp >= threshold:
                    lo_idx = probe_idx
                    break
                hi_idx = probe_idx
                probe_idx *= 2
            if lo_idx is None:
                # 下限以上未找到通过点
                console.print(
                    f"[red]⚠[/red] 在 {floor_freq * 1e-6:.0f} MHz 以上未找到 -3dB 通过点，"
                    f"实测带宽可能低于 {(start_bd + min_idx * bd_step) * 1e-6:.1f} MHz"
                )
                return int(start_bd + min_idx * bd_step)

        # 栅格二分精化：区间 [lo_idx, hi_idx]（索引单位），分辨率 = bd_step
        while hi_idx - lo_idx > 1:
            mid_idx = (lo_idx + hi_idx) // 2
            amp = self._measure_amp_at(start_bd + mid_idx * bd_step)
            if amp >= threshold:
                lo_idx = mid_idx
            else:
                hi_idx = mid_idx
        return int(start_bd + lo_idx * bd_step)
