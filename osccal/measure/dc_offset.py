"""直流偏置（JJF 1057-2026 7.5.1 方法一）。

规范方法：设定直流偏置为 0、激励为 0，读电压平均值为**零点偏置误差**；
再设偏置 d₀、激励 v₀，读 d_r，则偏置误差 δd = d₀ − d_r，
偏置增益 G_d = d_r / d₀。参考指标：δd 不超过满量程的 ±1%。

取点策略为按垂直档位逐档扫描（1 MΩ），d₀ 取 2 格对应的电压。
"""

import time

from rich.progress import Progress

from osccal.measure.base import BaseCalibrator, console, ensure_output_off

#: 偏置标称值取 2 格（规范未固定具体值，按屏格的固定比例便于复现）。
OFFSET_DIVISIONS = 2.0


class DcOffsetCalibrator(BaseCalibrator):
    """直流偏置：零点误差 + 偏置增益。"""

    title = "直流偏置（7.5.1 方法一）"

    def _measure_point(self, point: dict) -> dict:
        scale = float(point["scale"])
        impedance = point.get("impedance", "1M")
        vertical_div = float(self.profile.get("vertical_div", 8))
        full_scale = scale * vertical_div

        self._apply_impedance(impedance)
        self._write_osc("set_vertical_scale", self.channel, scale)
        self._write_osc("set_coupling", self.channel, "DC")
        if "set_vertical_position" in self.cmd_osc["actions"]:
            self._write_osc("set_vertical_position", self.channel, 0.0)

        # ① 零点：偏置 0、激励 0
        self._write_osc("set_offset", self.channel, 0.0)
        self._write_calibrator("set_shap", "DC")
        self._write_calibrator("set_volt", 0.0)
        self._write_calibrator("set_output", "ON")
        time.sleep(1.0)
        zero_reading = self._read_meas("meas_mean")

        # ② 偏移点：偏置 d₀、激励 0，读 d_r
        offset_nominal = OFFSET_DIVISIONS * scale
        self._write_osc("set_offset", self.channel, offset_nominal)
        self._nudge_trigger_level(scale)
        time.sleep(1.0)
        offset_measured = self._read_meas("meas_mean")

        offset_error = offset_nominal - offset_measured
        gain = offset_measured / offset_nominal if offset_nominal else float("nan")
        return {
            "channel": self.channel,
            "impedance": impedance,
            "scale": scale,
            "full_scale_v": full_scale,
            "zero_reading_v": zero_reading,
            "offset_nominal_v": offset_nominal,
            "offset_measured_v": offset_measured,
            "offset_error_v": offset_error,
            "error_pct": 100.0 * offset_error / full_scale if full_scale else float("nan"),
            "gain": gain,
        }

    @ensure_output_off
    def run(self):
        self.print_title(self.title)
        self.init_devices()
        self.setup_channel()
        self.setup_measurement("meas_mean")

        if not self.points:
            console.print("[yellow]⚠ 本轮没有可执行的校准点[/yellow]")
            return

        table = self.make_table(
            "直流偏置校准结果",
            [
                {"name": "序号"},
                {"name": "通道", "justify": "center"},
                {"name": "挡位(V/div)"},
                {"name": "满量程(V)"},
                {"name": "零点读数(V)"},
                {"name": "偏置标称(V)"},
                {"name": "偏置实测(V)"},
                {"name": "偏置误差(V)"},
                {"name": "误差(%FS)"},
                {"name": "偏置增益 G"},
            ],
        )

        with Progress() as progress:
            task = progress.add_task("直流偏置", total=len(self.points))
            for index, point in enumerate(self.points, start=1):
                record = self._measure_point(point)
                self.results.append({"index": index, **record})
                self.add_result_row(
                    table,
                    [
                        index,
                        f"CH{self.channel}",
                        f"{record['scale']:g}",
                        f"{record['full_scale_v']:.6g}",
                        f"{record['zero_reading_v']:.6g}",
                        f"{record['offset_nominal_v']:.6g}",
                        f"{record['offset_measured_v']:.6g}",
                        f"{record['offset_error_v']:.6g}",
                        f"{record['error_pct']:.3f}",
                        f"{record['gain']:.6f}",
                    ],
                )
                progress.update(task, advance=1)
        console.print(table)
