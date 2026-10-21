"""上升时间（JJF 1057-2026 7.8）。

规范方法：快沿脉冲输入，直流耦合，调节直流偏置与信号幅度，使脉冲底值与顶值之间
的部分**居中覆盖屏幕 60%~80%**；读 10%~90% 上升时间，同时读取过冲 S_b。

实机约定（MDO3052 + 9500B 9530 头）：
- 9500B 输出的是**下沿**脉冲，示波器用 50 Ω 端接，触发沿选 FALL；
- 脉冲为单极性（高电平 ~V、低电平 0），用垂直偏置把高/低电平的中点抬到屏幕中心，
  即满足"底顶之间居中覆盖"；
- 占屏：1 Vpp 在 0.2 V/div、8 格下为 62.5%，落在规范要求的 60%~80% 内。

每个通道按探头可用的边沿速度各取一点。跳变幅度与顶部不平度需要波形数据才有
意义，留待后续补充（当前只记录过渡时间与过冲，不虚报未测量的量）。
"""

import time

from rich.progress import Progress

from osccal.measure.base import BaseCalibrator, console, ensure_output_off

#: 脉冲幅度与垂直档位：1 Vpp 在 0.2 V/div、8 格下占 62.5% 屏。
AMPLITUDE_VPP = 1.0
VERTICAL_SCALE = 0.2
#: 快沿很陡，水平挡位取最快档才能看清过渡过程。
TIMEBASE_S_PER_DIV = 1e-9


class RiseTimeCalibrator(BaseCalibrator):
    """上升时间：快沿脉冲下的 10%~90% 过渡时间与过冲。"""

    title = "上升时间（7.8）"

    def _measure_point(self, point: dict) -> dict:
        edge_speed = float(point["edge_rise_time_s"])

        self._apply_impedance("50")
        self._write_osc("set_vertical_scale", self.channel, VERTICAL_SCALE)
        self._write_osc("set_coupling", self.channel, "DC")
        self._set_timebase(TIMEBASE_S_PER_DIV)
        # 单极性下沿脉冲：把高低电平中点抬到屏幕中心
        # 脉冲高电平 0 V、低电平 −1 V：中点是 −0.5 V，用它做屏幕中心
        if "set_offset" in self.cmd_osc.get("actions", {}):
            self._write_osc("set_offset", self.channel, -AMPLITUDE_VPP / 2.0)
        if "set_trigger_slope" in self.cmd_osc.get("actions", {}):
            self._write_osc("set_trigger_slope", "RIS")
        # 触发电平放在过渡区中点（−0.5 V），否则会落在 0 V 或 −1 V 的平台上
        if "set_trigger_level" in self.cmd_osc.get("actions", {}):
            action = self.cmd_osc["actions"]["set_trigger_level"]
            if action.get("args_num", 0) >= 2:
                self._write_osc("set_trigger_level", self.channel, -AMPLITUDE_VPP / 2.0)
            else:
                self._write_osc("set_trigger_level", -AMPLITUDE_VPP / 2.0)

        self._write_calibrator("set_shap", "EDGE")
        self._write_calibrator("set_edge_speed", edge_speed)
        self._write_calibrator("set_volt", AMPLITUDE_VPP)
        self._write_calibrator("set_output", "ON")
        time.sleep(1.0)

        # 校准对象是**上升沿**（−1 V → 0 V 的过渡），用 RIS 测量项
        keyword = "meas_risetime"
        transition = self._read_meas(keyword)
        overshoot = None
        if "meas_pos_overshoot" in self.cmd_osc.get("keyword", {}):
            overshoot = self._read_meas("meas_pos_overshoot")

        return {
            "channel": self.channel,
            "impedance": "50",
            "edge_rise_time_s": edge_speed,
            "vertical_scale": VERTICAL_SCALE,
            "amplitude_vpp": AMPLITUDE_VPP,
            "rise_time_s": transition,
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
                {"name": "过渡时间(10%~90%)", "justify": "left"},
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
