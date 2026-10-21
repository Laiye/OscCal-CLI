"""Δt（时间）测量（JJF 1057-2026 7.12）。

规范方法：输入适当幅度和频率的**方波**信号，调节直流偏置和触发，使 M（≥2）个
完整周期稳定居中显示、水平方向覆盖约 80% 屏幕，读出 M 个信号周期的实测值。

取点按屏占比给出信号周期：T = screen_fraction × 水平格数 × 时基挡位 / M。
示波器用周期测量功能读单个周期，再乘 M 与标准值比较。
"""

import time

from rich.progress import Progress

from osccal.measure.base import BaseCalibrator, console, ensure_output_off

#: 规范要求 M ≥ 2 个完整周期。
PERIODS_M = 2
VERTICAL_SCALE = 0.1
AMPLITUDE_VPP = 0.5


class DeltaTimeCalibrator(BaseCalibrator):
    """Δt（时间）：M 个周期的实测值与标准值比较。"""

    title = "Δt（时间）测量（7.12）"

    def _measure_point(self, point: dict) -> dict:
        scale = float(point["timebase_s_per_div"])
        period_std = float(point["period_on_screen_s"])
        freq_std = float(point["signal_freq_hz"])

        self._write_osc("set_horizontal_scale", scale)
        self._write_osc("set_vertical_scale", self.channel, VERTICAL_SCALE)
        self._write_osc("set_coupling", self.channel, "DC")
        if "set_vertical_position" in self.cmd_osc["actions"]:
            self._write_osc("set_vertical_position", self.channel, 0.0)
        self._nudge_trigger_level(VERTICAL_SCALE)

        self._write_calibrator("set_shap", "SQU")
        self._write_calibrator("set_freq", freq_std)
        self._write_calibrator("set_volt", AMPLITUDE_VPP)
        self._write_calibrator("set_output", "ON")
        time.sleep(1.0)

        period_measured = self._read_meas("meas_period")
        time_measured = PERIODS_M * period_measured
        time_standard = PERIODS_M * period_std
        error_pct = (
            100.0 * (time_measured - time_standard) / time_standard
            if time_standard
            else float("nan")
        )
        return {
            "channel": self.channel,
            "timebase_s_per_div": scale,
            "periods_m": PERIODS_M,
            "period_standard_s": period_std,
            "period_measured_s": period_measured,
            "time_standard_s": time_standard,
            "time_measured_s": time_measured,
            "error_pct": error_pct,
        }

    @ensure_output_off
    def run(self):
        self.print_title(self.title)
        self.init_devices()
        self.setup_channel()
        self.setup_measurement("meas_period")

        if not self.points:
            console.print("[yellow]⚠ 本轮没有可执行的校准点（方波激励能力不足时会被跳过）[/yellow]")
            return

        table = self.make_table(
            "Δt（时间）校准结果",
            [
                {"name": "序号"},
                {"name": "通道", "justify": "center"},
                {"name": "时基挡位", "justify": "left"},
                {"name": "周期数 M", "justify": "center"},
                {"name": "标准值", "justify": "left"},
                {"name": "被测值", "justify": "left"},
                {"name": "相对误差(%)"},
            ],
        )

        with Progress() as progress:
            task = progress.add_task("Δt 时间", total=len(self.points))
            for index, point in enumerate(self.points, start=1):
                record = self._measure_point(point)
                self.results.append({"index": index, **record})
                self.add_result_row(
                    table,
                    [
                        index,
                        f"CH{self.channel}",
                        self._format_time(record["timebase_s_per_div"]) + "/div",
                        record["periods_m"],
                        self._format_time(record["time_standard_s"]),
                        self._format_time(record["time_measured_s"]),
                        f"{record['error_pct']:.3f}",
                    ],
                )
                progress.update(task, advance=1)
        console.print(table)

    @staticmethod
    def _format_time(value: float) -> str:
        if value >= 1:
            return f"{value:.4g} s"
        if value >= 1e-3:
            return f"{value * 1e3:.4g} ms"
        if value >= 1e-6:
            return f"{value * 1e6:.4g} µs"
        return f"{value * 1e9:.4g} ns"
