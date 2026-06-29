import time
import click
from osccal.measure.base import BaseCalibrator, console
from osccal.core.utils import format_with_fixed_precision


class TransientCalibrator(BaseCalibrator):

    def run(self):
        self.print_title("上升时间及过冲")
        self.init_devices()
        self.setup_channel()
        self._write_osc("set_vertical_scale", self.channel, 0.2)
        self._write_osc("set_trigger_level", self.channel, -0.5)
        self._write_osc("set_vertical_position", self.channel, 2)
        self._write_osc("set_horizontal_scale", 5E-10)
        self._write_osc("set_meas_source", self.channel)

        self._write_calibrator("set_shap", "EDGE")
        self._setup_signal_impedance("EDGE", "50")

        rise_times = self._get_probe_edge_rise_times()
        if len(rise_times) == 1:
            edge_speed = rise_times[0]
        else:
            console.print("\n[bold]选择上升时间:[/bold]")
            for i, rt in enumerate(rise_times):
                rt_ps = rt * 1E12
                console.print(f"  [{i}] {rt_ps:.0f} ps")
            idx = click.prompt("请选择", type=int, default=0)
            edge_speed = rise_times[idx]

        self._write_calibrator("set_edge_speed", edge_speed)
        self._write_calibrator("set_output", "ON")

        time.sleep(3)
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
