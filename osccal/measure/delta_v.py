"""ΔV（幅度）测量（JJF 1057-2026 7.11）。

规范方法：输入适当幅度和频率（推荐 1 kHz）的方波，调节直流偏置和触发，使两个
以上周期稳定居中显示、垂直方向覆盖 80% 屏幕，移动测量光标读取幅度。**

已确认的偏离**：本实现用示波器的自动幅度测量功能读数代替光标读数（记录中会写明）。

取点按垂直挡位逐档（1 MΩ），标准值 = 0.8 × 垂直格数 × 挡位（峰峰值口径）。
"""

import time

from rich.progress import Progress

from osccal.measure.base import BaseCalibrator, console, ensure_output_off


class DeltaVCalibrator(BaseCalibrator):
    """ΔV（幅度）：自动测量读数与标准方波幅度比较。"""

    title = "ΔV（幅度）测量（7.11）"

    def _measure_point(self, point: dict) -> dict:
        scale = float(point["scale"])
        impedance = point.get("impedance", "1M")
        std_value = float(point["std_value_vpp"])

        self._apply_impedance(impedance)
        self._write_osc("set_vertical_scale", self.channel, scale)
        self._write_osc("set_coupling", self.channel, "DC")
        # 1 kHz 方波：200 µs/div → 屏上约 2 个周期，幅度测量才有效
        self._set_timebase(200e-6)
        if "set_vertical_position" in self.cmd_osc["actions"]:
            self._write_osc("set_vertical_position", self.channel, 0.0)
        self._nudge_trigger_level(scale)

        self._write_calibrator("set_shap", "SQU")
        # 双极性对称波，避免单极性方波顶部超出屏幕被削顶
        self._write_calibrator("set_squ_polarity", "SYMM")
        self._write_calibrator("set_freq", 1000.0)
        self._write_calibrator("set_volt", std_value)
        self._write_calibrator("set_output", "ON")
        time.sleep(1.0)

        measured = self._read_meas_value("meas_amp") * self._get_meas_amp_scale()
        error_pct = 100.0 * (measured - std_value) / std_value if std_value else float("nan")
        return {
            "channel": self.channel,
            "impedance": impedance,
            "scale": scale,
            "std_value_vpp": std_value,
            "measured_vpp": measured,
            "error_pct": error_pct,
            "method": "auto_measurement",
        }

    @ensure_output_off
    def run(self):
        self.print_title(self.title)
        self.init_devices()
        self.setup_channel()
        self.setup_measurement("meas_amp")

        if not self.points:
            console.print("[yellow]⚠ 本轮没有可执行的校准点[/yellow]")
            return

        table = self.make_table(
            "ΔV（幅度）校准结果",
            [
                {"name": "序号"},
                {"name": "通道", "justify": "center"},
                {"name": "阻抗", "justify": "center"},
                {"name": "挡位(V/div)"},
                {"name": "标称值(Vpp)"},
                {"name": "实测值(Vpp)"},
                {"name": "相对误差(%)"},
            ],
        )

        with Progress() as progress:
            task = progress.add_task("ΔV 幅度", total=len(self.points))
            for index, point in enumerate(self.points, start=1):
                record = self._measure_point(point)
                self.results.append({"index": index, **record})
                self.add_result_row(
                    table,
                    [
                        index,
                        f"CH{self.channel}",
                        "1 MΩ" if record["impedance"] == "1M" else "50 Ω",
                        f"{record['scale']:g}",
                        f"{record['std_value_vpp']:.6g}",
                        f"{record['measured_vpp']:.6g}",
                        f"{record['error_pct']:+.3f}",
                    ],
                )
                progress.update(task, advance=1)
        console.print(table)
