"""时基（采集速率）误差（JJF 1057-2026 7.9）。

方法一（频率法，规范 7.9.1）：输入已知频率的正弦信号，用示波器的频率测量功能
读 f_read。时基偏慢时测得的频率偏低，故

    δT = (f_std − f_read) / f_std      （正值 = 时基偏慢）

方法二（拟合角频率法，规范 7.9.2）：读回波形并按附录 E 拟合，拟合以**标称时间轴**
（`WFMOutpre:XINcr`）为基准，得到表观频率 f_app，则

    δT = f_std / f_app − 1

指令集声明了波形能力时两种方法都记录，方法一为判定值，拟合值作为交叉核对。
"""

import time

from rich.progress import Progress

from osccal.core.fitting import FitError, fit_sine
from osccal.measure.base import BaseCalibrator, console, ensure_output_off

#: 垂直档位与激励幅度：0.5 Vpp 在 0.1 V/div 下约占 62% 屏，满足"覆盖 50% 以上"。
VERTICAL_SCALE = 0.1
AMPLITUDE_VPP = 0.5
#: 拟合法需要"屏上的完整波形"：只取前 1000 点会显著短于一屏（例如 1 µs/div 下
#: 记录 10000 点才铺满 10 格），拟合会因周期不足而完全失真。这里请求一个远大于
#: 记录长度的点数，示波器会自动截到实际记录长度（WFMOutpre:NR_Pt 回读）。
FIT_SAMPLES = 2_000_000


class TimebaseErrorCalibrator(BaseCalibrator):
    """时基（采集速率）误差：频率法为判定值，拟合角频率法为交叉核对。"""

    title = "时基（采集速率）误差（7.9）"

    def _has_waveform(self) -> bool:
        return "query_wave_data" in self.cmd_osc.get("actions", {})

    def _measure_point(self, point: dict) -> dict:
        scale = float(point["timebase_s_per_div"])
        freq_std = float(point["signal_freq_hz"])

        self._write_osc("set_horizontal_scale", scale)
        self._write_osc("set_vertical_scale", self.channel, VERTICAL_SCALE)
        self._write_osc("set_coupling", self.channel, "DC")
        if "set_vertical_position" in self.cmd_osc["actions"]:
            self._write_osc("set_vertical_position", self.channel, 0.0)
        self._nudge_trigger_level(VERTICAL_SCALE)

        self._write_calibrator("set_shap", "SIN")
        self._write_calibrator("set_freq", freq_std)
        self._write_calibrator("set_volt", AMPLITUDE_VPP)
        self._write_calibrator("set_output", "ON")
        time.sleep(1.0)

        freq_read = self._read_meas("meas_freq")
        rel_error = (freq_std - freq_read) / freq_std

        fit_frequency = None
        rel_error_fit = None
        if self._has_waveform():
            try:
                wave = self._read_waveform(FIT_SAMPLES)
                fit = fit_sine(wave.seconds, wave.volts)
                if fit.frequency > 0:
                    fit_frequency = fit.frequency
                    rel_error_fit = freq_std / fit.frequency - 1.0
            except (FitError, ValueError) as exc:
                console.print(f"[yellow]⚠ 波形拟合法核对跳过: {exc}[/yellow]")

        return {
            "channel": self.channel,
            "timebase_s_per_div": scale,
            "signal_freq_hz": freq_std,
            "measured_freq_hz": freq_read,
            "rel_error": rel_error,
            "rel_ppm": rel_error * 1e6,
            "fit_frequency_hz": fit_frequency,
            "rel_error_fit": rel_error_fit,
            "fit_ppm": None if rel_error_fit is None else rel_error_fit * 1e6,
        }

    @ensure_output_off
    def run(self):
        self.print_title(self.title)
        self.init_devices()
        self.setup_channel()
        self.setup_measurement("meas_freq")

        if not self.points:
            console.print("[yellow]⚠ 本轮没有可执行的校准点[/yellow]")
            return

        table = self.make_table(
            "时基（采集速率）误差校准结果",
            [
                {"name": "序号"},
                {"name": "通道", "justify": "center"},
                {"name": "时基挡位", "justify": "left"},
                {"name": "信号频率", "justify": "left"},
                {"name": "测得频率", "justify": "left"},
                {"name": "相对误差(ppm)"},
                {"name": "拟合法(ppm)"},
            ],
        )

        with Progress() as progress:
            task = progress.add_task("时基误差", total=len(self.points))
            for index, point in enumerate(self.points, start=1):
                record = self._measure_point(point)
                self.results.append({"index": index, **record})
                fit_text = (
                    f"{record['rel_error_fit'] * 1e6:.2f}"
                    if record["rel_error_fit"] is not None
                    else "—"
                )
                self.add_result_row(
                    table,
                    [
                        index,
                        f"CH{self.channel}",
                        self._format_time(record["timebase_s_per_div"]) + "/div",
                        self._format_frequency(record["signal_freq_hz"]),
                        self._format_frequency(record["measured_freq_hz"]),
                        f"{record['rel_ppm']:.2f}",
                        fit_text,
                    ],
                )
                progress.update(task, advance=1)
        console.print(table)

    @staticmethod
    def _format_time(value: float) -> str:
        if value >= 1:
            return f"{value:g} s"
        if value >= 1e-3:
            return f"{value * 1e3:g} ms"
        if value >= 1e-6:
            return f"{value * 1e6:g} µs"
        return f"{value * 1e9:g} ns"

    @staticmethod
    def _format_frequency(value: float) -> str:
        if value >= 1e6:
            return f"{value / 1e6:.4g} MHz"
        if value >= 1e3:
            return f"{value / 1e3:.4g} kHz"
        return f"{value:.4g} Hz"
