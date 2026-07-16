import time
from osccal.measure.base import BaseCalibrator, console
from osccal.core.utils import format_with_fixed_precision


class TransientCalibrator(BaseCalibrator):

    def run(self):
        self.print_title("上升时间及过冲")
        self.init_devices()
        self.setup_channel()
        self._write_osc("set_vertical_scale", self.channel, 0.2)

        # 触发参数：Tek 系命令需通道号，ZDS 系不需要
        has_50 = self.profile.get("imp_has_50", False)
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
        h_scale = 5E-10 if has_50 else 5E-9
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
        if has_50:
            # 50Ω: 优先选最快的上升时间
            edge_speed = rise_times[0]
        else:
            # 1MΩ: 选最慢的上升时间（500ps，兼容 1MΩ 输出）
            edge_speed = rise_times[-1]

        self._write_calibrator("set_edge_speed", edge_speed)
        self._write_calibrator("set_output", "ON")

        time.sleep(3)
        # 提前设好测量项，SINGLE 捕获后直接查询（避免死数据/0.0）
        self.setup_measurement("meas_risetime")
        self.setup_measurement("meas_pos_overshoot")
        self._write_osc("set_acquire_stop_after", self.cmd_osc["keyword"]["acquire_stop_after_single"])
        time.sleep(2)

        risetime = self._read_meas("meas_risetime")
        pos_overshoot = self._read_meas("meas_pos_overshoot")

        risetime_ns = risetime * 1E9
        edge_speed_ps = edge_speed * 1E12

        columns = [
            {"name": "通道"},
            {"name": "上升时间(ns)"},
            {"name": "过冲(%)"},
            {"name": "探头上升时间(ps)"},
        ]
        table = self.make_table("瞬态响应校准结果", columns)

        row_data = [
            f"CH{self.channel}",
            format_with_fixed_precision(risetime_ns, 2),
            format_with_fixed_precision(pos_overshoot, 2),
            f"{edge_speed_ps:.0f}",
        ]
        table.add_row(*[str(v) for v in row_data])

        self.results.append({
            "channel": self.channel,
            "risetime_ns": risetime_ns,
            "pos_overshoot": pos_overshoot,
            "edge_speed_ps": edge_speed_ps,
        })

        console.print(table)
        self._write_calibrator("set_output", "OFF")
