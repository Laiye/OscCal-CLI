import time

from osccal.core.utils import format_display_value
from osccal.measure.base import BaseCalibrator, console, ensure_output_off


class TransientCalibrator(BaseCalibrator):
    @ensure_output_off
    def run(self):
        self.print_title("上升时间及过冲")
        self.init_devices()
        self.setup_channel()
        self._write_osc("set_vertical_scale", self.channel, 0.2)

        # 触发参数：Tek 系命令需通道号，ZDS 系不需要
        has_50 = self.profile.get("imp_has_50", False)
        # 正过冲不是所有机型都有（如泰克 TBS1000/TDS1000/TDS2000 系列无 POVERshoot 测量）：
        # 指令集未声明 meas_pos_overshoot 时只测上升时间，过冲列记为“不适用”，不整项失败。
        has_overshoot = "meas_pos_overshoot" in self.cmd_osc.get("keyword", {})
        trg_lev_action = self.cmd_osc["actions"].get("set_trigger_level", {})
        trg_lev = -0.5  # 触发电平：-0.5V（所有模式通用）
        if trg_lev_action.get("args_num", 0) >= 2:
            self._write_osc("set_trigger_level", self.channel, trg_lev)
        else:
            self._write_osc("set_trigger_level", trg_lev)

        # 垂直位置：OFFSet 模式用伏特值，POS 模式用格数值
        vp_action = self.cmd_osc["actions"].get("set_vertical_position", {})
        vp_cmd = " ".join(vp_action.get("commands", []))
        if "OFFSET" in vp_cmd.upper():
            # OFFSET 单位是伏特：2格 × 0.2V/div = 0.4V
            self._write_osc("set_vertical_position", self.channel, 0.4)
        else:
            self._write_osc("set_vertical_position", self.channel, 2)

        # 水平时基：50Ω 快沿用 500ps/div，1MΩ 慢沿用 5ns/div
        h_scale = 5e-10 if has_50 else 5e-9
        self._write_osc("set_horizontal_scale", h_scale)

        # ItemChannel 模式不需要 set_meas_source
        if "set_meas_source" in self.cmd_osc["actions"]:
            self._write_osc("set_meas_source", self.channel)

        self._write_calibrator("set_shap", "EDGE")

        # 示波器无 50Ω → 用 1MΩ + 最大可选上升时间（9530 的 500ps）
        if has_50:
            self._setup_signal_impedance("EDGE", "50")
        else:
            self._setup_signal_impedance("EDGE", "1M")

        rise_times = self._get_probe_edge_rise_times()
        # 50Ω: 优先选最快的上升时间；1MΩ: 选最慢的上升时间（500ps，兼容 1MΩ 输出）
        edge_speed = rise_times[0] if has_50 else rise_times[-1]

        self._write_calibrator("set_edge_speed", edge_speed)
        self._write_calibrator("set_output", "ON")

        time.sleep(3)
        # 提前设好测量项，SINGLE 捕获后直接查询（避免死数据/0.0）
        self.setup_measurement("meas_risetime")
        if has_overshoot:
            self.setup_measurement("meas_pos_overshoot")
        else:
            console.print(
                "[yellow]⚠ 指令集未声明正过冲测量（meas_pos_overshoot），"
                "本次只记录上升时间，过冲列记为“不适用”[/yellow]"
            )
        self._write_osc(
            "set_acquire_stop_after", self.cmd_osc["keyword"]["acquire_stop_after_single"]
        )
        # 触发单次采集：STOPAfter=SEQuence/SINGle 模式下 RUN 后完成一个序列自动停止。
        # ZLG 系（zlg_zds/zlg_zds1000）无 set_acquire_state，其 SING 命令本身即触发捕获，无需下发。
        if "set_acquire_state" in self.cmd_osc.get("actions", {}):
            self._write_osc(
                "set_acquire_state", self.cmd_osc["keyword"].get("acquire_state_run", "RUN")
            )
        time.sleep(2)

        risetime = self._read_meas("meas_risetime")
        pos_overshoot = self._read_meas("meas_pos_overshoot") if has_overshoot else None

        risetime_ns = risetime * 1e9
        edge_speed_ps = edge_speed * 1e12

        columns = [
            {"name": "通道"},
            {"name": "上升时间(ns)"},
            {"name": "过冲(%)"},
            {"name": "探头上升时间(ps)"},
        ]
        table = self.make_table("瞬态响应校准结果", columns)

        row_data = [
            f"CH{self.channel}",
            format_display_value(risetime_ns, ("sig", 2)),
            format_display_value(pos_overshoot, ("sig", 2)),
            format_display_value(edge_speed_ps, ("dec", 0)),
        ]
        table.add_row(*[str(v) for v in row_data])

        self.results.append(
            {
                "channel": self.channel,
                "risetime_ns": risetime_ns,
                "pos_overshoot": pos_overshoot,
                "edge_speed_ps": edge_speed_ps,
            }
        )

        console.print(table)
