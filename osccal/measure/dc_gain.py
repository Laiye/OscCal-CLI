"""直流增益（JJF 1057-2026 7.4.2 方法二：方波幅度法）。

规范原文（第 5 页）：输入频率合适（推荐 1 kHz）、幅度值为 V 的方波电压，
使它们覆盖屏幕 80% 以上的垂直量程范围，用示波器幅度测量功能读取 V_r，
按式 (2) 计算直流增益 G = V_r / V。

标准值 V 由取点解析按屏占比给出：V = screen_fraction × 垂直格数 × 挡位；
不再使用 V0.1.0 的"两点 ±满格"口径。
"""

import time

from rich.progress import Progress

from osccal.measure.base import BaseCalibrator, console, ensure_output_off


class DcGainCalibrator(BaseCalibrator):
    """方法二：方波幅度法。"""

    title = "直流增益（方法二：方波幅度法）"

    def _zero_position(self) -> None:
        """规范 7.4 前置：直流耦合、直流偏置调零。"""
        self._write_osc("set_coupling", self.channel, "DC")
        if "set_vertical_position" in self.cmd_osc["actions"]:
            self._write_osc("set_vertical_position", self.channel, 0.0)

    def _measure_point(self, point: dict) -> dict:
        scale = float(point["scale"])
        impedance = point.get("impedance", "1M")
        std_value = float(point["std_value_vpp"])

        self._apply_impedance(impedance)
        self._write_osc("set_vertical_scale", self.channel, scale)
        self._zero_position()
        self._nudge_trigger_level(scale)

        self._write_calibrator("set_shap", "SQU")
        self._write_calibrator("set_freq", 1000.0)
        self._write_calibrator("set_volt", std_value)
        self._write_calibrator("set_output", "ON")
        time.sleep(1.0)

        measured = self._read_meas("meas_amp") * self._get_meas_amp_scale()
        gain = measured / std_value if std_value else float("nan")
        return {
            "channel": self.channel,
            "impedance": impedance,
            "scale": scale,
            "std_value_vpp": std_value,
            "measured_vpp": measured,
            "gain": gain,
            "error_pct": 100.0 * (gain - 1.0),
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
            "直流增益校准结果",
            [
                {"name": "序号"},
                {"name": "通道", "justify": "center"},
                {"name": "阻抗", "justify": "center"},
                {"name": "挡位(V/div)"},
                {"name": "标准值(Vpp)"},
                {"name": "被校示值(Vpp)"},
                {"name": "增益 G"},
                {"name": "增益误差(%)"},
            ],
        )

        with Progress() as progress:
            task = progress.add_task("直流增益", total=len(self.points))
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
                        f"{record['gain']:.6f}",
                        f"{record['error_pct']:.3f}",
                    ],
                )
                progress.update(task, advance=1)
        console.print(table)
