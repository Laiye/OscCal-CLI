"""上升时间（JJF 1057-2026 7.8）。

规范方法：快沿脉冲输入，直流耦合，调节直流偏置与信号幅度，使脉冲底值与顶值之间
的部分**居中覆盖屏幕 60%~80%**；读 10%~90% 上升时间，同时读取过冲 S_b。

本实现取脉冲幅度 1 Vpp、垂直挡位 0.2 V/div（1/(0.2×8) = 62.5% 屏），
每通道 × 探头可用的边沿速度各一点。跳变幅度与顶部不平度需要波形数据才有意义，
留待后续补充（当前只记录上升时间与过冲，不虚报未测量的量）。
"""

import time

from rich.progress import Progress

from osccal.measure.base import BaseCalibrator, console, ensure_output_off

#: 脉冲幅度与垂直档位：1 Vpp 在 0.2 V/div、8 格下占 62.5% 屏。
AMPLITUDE_VPP = 1.0
VERTICAL_SCALE = 0.2


class RiseTimeCalibrator(BaseCalibrator):
    """上升时间：快沿脉冲下的 10%~90% 上升时间与正过冲。"""

    title = "上升时间（7.8）"

    def _measure_point(self, point: dict) -> dict:
        edge_speed = float(point["edge_rise_time_s"])

        self._apply_impedance("1M")
        self._write_osc("set_vertical_scale", self.channel, VERTICAL_SCALE)
        self._write_osc("set_coupling", self.channel, "DC")
        if "set_vertical_position" in self.cmd_osc["actions"]:
            self._write_osc("set_vertical_position", self.channel, 0.0)
        self._nudge_trigger_level(VERTICAL_SCALE)

        self._write_calibrator("set_shap", "EDGE")
        self._write_calibrator("set_edge_speed", edge_speed)
        self._write_calibrator("set_volt", AMPLITUDE_VPP)
        self._write_calibrator("set_output", "ON")
        time.sleep(1.0)

        rise_time = self._read_meas("meas_risetime")
        overshoot = None
        if "meas_pos_overshoot" in self.cmd_osc.get("keyword", {}):
            overshoot = self._read_meas("meas_pos_overshoot")

        return {
            "channel": self.channel,
            "edge_rise_time_s": edge_speed,
            "vertical_scale": VERTICAL_SCALE,
            "amplitude_vpp": AMPLITUDE_VPP,
            "rise_time_s": rise_time,
            "overshoot_pct": overshoot,
        }

    @ensure_output_off
    def run(self):
        self.print_title(self.title)
        self.init_devices()
        self.setup_channel()
        self.setup_measurement("meas_risetime")

        if not self.points:
            console.print("[yellow]⚠ 本轮没有可执行的校准点[/yellow]")
            return

        table = self.make_table(
            "上升时间校准结果",
            [
                {"name": "序号"},
                {"name": "通道", "justify": "center"},
                {"name": "探头边沿", "justify": "left"},
                {"name": "上升时间", "justify": "left"},
                {"name": "过冲(%)"},
                {"name": "脉冲幅度(Vpp)"},
            ],
        )

        with Progress() as progress:
            task = progress.add_task("上升时间", total=len(self.points))
            for index, point in enumerate(self.points, start=1):
                record = self._measure_point(point)
                self.results.append({"index": index, **record})
                overshoot = record["overshoot_pct"]
                self.add_result_row(
                    table,
                    [
                        index,
                        f"CH{self.channel}",
                        self._format_time(record["edge_rise_time_s"]),
                        self._format_time(record["rise_time_s"]),
                        "不适用" if overshoot is None else f"{overshoot:.2f}",
                        f"{record['amplitude_vpp']:.4g}",
                    ],
                )
                progress.update(task, advance=1)
        console.print(table)

    @staticmethod
    def _format_time(value: float) -> str:
        if value >= 1e-6:
            return f"{value * 1e6:.4g} µs"
        if value >= 1e-9:
            return f"{value * 1e9:.4g} ns"
        return f"{value * 1e12:.4g} ps"
