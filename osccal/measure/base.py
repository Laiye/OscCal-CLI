import time
from functools import wraps

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from osccal.core.comm import read_measurement, scpi_query, scpi_setup_measurement, scpi_write
from osccal.core.command import assemble_cmd

console = Console()


class OutputShutdownError(RuntimeError):
    """无法确认关闭输出，必须终止会话。"""


def ensure_output_off(run):
    """正常结束、异常或用户中断时，均在释放连接前尝试关闭输出。"""

    @wraps(run)
    def guarded(self, *args, **kwargs):
        try:
            return run(self, *args, **kwargs)
        finally:
            try:
                self._write_calibrator("set_output", "OFF")
            except Exception as exc:
                console.print("[red]✗ 校准仪关闭输出失败，请检查设备输出状态；会话已终止[/red]")
                raise OutputShutdownError("校准仪关闭输出失败") from exc

    return guarded


class BaseCalibrator:
    def __init__(
        self, inst_osc, inst_calibrator, cmd_osc, cmd_calibrator, profile, channel, probe=None
    ):
        self.inst_osc = inst_osc
        self.inst_calibrator = inst_calibrator
        self.cmd_osc = cmd_osc
        self.cmd_calibrator = cmd_calibrator
        self.profile = profile
        self.channel = str(channel)
        self.probe = probe
        self.comm_type = cmd_osc.get("type", "pyvisa")
        self.cal_type = cmd_calibrator.get("type", "pyvisa")
        self.results = []

    def _get_limits(self, item_name):
        limits = self.profile.get("calibration_limits", {}).get(item_name, None)
        if limits:
            return (limits.get("lower", -2.0), limits.get("upper", 2.0))
        return None

    def _setup_signal_impedance(self, shape, preferred_osc_impedance="1M"):
        rules = self.cmd_calibrator.get("impedance_rules", {})
        probe = self.probe or "9550"
        probe_rules = rules.get(probe, {})
        supported = probe_rules.get(shape, None)

        if supported is None:
            raise ValueError(
                f"探头 {probe} 不支持 {shape} 信号模式。"
                f"探头 {probe} 支持的模式: {list(probe_rules.keys())}"
            )

        if preferred_osc_impedance in supported:
            actual_osc_imp = preferred_osc_impedance
        else:
            actual_osc_imp = supported[0]
            console.print(
                f"[yellow]⚠ 探头{probe}在{shape}模式下不支持{preferred_osc_impedance}Ω输出，"
                f"已自动切换为{actual_osc_imp}Ω（示波器与校准仪均切换）[/yellow]"
            )

        imp_key = "imp_meg" if actual_osc_imp == "1M" else "imp_fif"

        if self.profile.get("imp_has_50", False):
            self.setup_impedance(imp_key)
        elif imp_key == "imp_fif":
            console.print(
                f"[red]⚠ 示波器不支持50Ω输入，但探头{probe}在{shape}模式下只能输出50Ω，"
                f"存在阻抗不匹配，测量结果可能不准确[/red]"
            )

        self._write_calibrator("set_impedance", self.cmd_calibrator["keyword"][imp_key])

        return imp_key

    def _get_probe_edge_rise_times(self):
        probe = self.probe or "9550"
        probe_info = self.cmd_calibrator.get("probes", {}).get(probe, {})
        return probe_info.get("edge_rise_times", [150e-12])

    def _get_probe_max_frequency_hz(self) -> float:
        probe = self.probe or "9550"
        probe_info = self.cmd_calibrator.get("probes", {}).get(probe, {})
        max_freq = probe_info.get("max_frequency_hz", 0)
        if max_freq <= 0:
            return 600e6
        return float(max_freq)

    def _read_meas(self, meas_keyword):
        actual_keyword = self.cmd_osc["keyword"][meas_keyword]
        return read_measurement(self.inst_osc, None, self.cmd_osc, self.channel, actual_keyword)

    def _adjust_vertical_position(self, scale):
        if self.profile.get("skip_vertical_adjust", False):
            return
        if "set_vertical_position" not in self.cmd_osc["actions"]:
            return
        keywords = self.cmd_osc.get("keyword", {})
        has_max = "meas_max" in keywords
        has_min = "meas_min" in keywords
        if not has_max or not has_min:
            console.print(
                "[yellow]⚠ 指令集缺少 meas_max/meas_min 关键字，跳过垂直位置自动调整[/yellow]"
            )
            return

        self._write_osc("set_vertical_position", self.channel, 0.0)
        if scale > 0.002:
            return
        vertical_div = self.profile.get("vertical_div", 8)
        half_div = vertical_div / 2.0
        position = 0.0
        for _ in range(5):
            max_val = self._read_meas("meas_max")
            min_val = self._read_meas("meas_min")
            top_limit = half_div * scale
            bottom_limit = -half_div * scale
            need_adjust = False
            if max_val > top_limit:
                overshoot = (max_val - top_limit) / scale
                position -= overshoot * 0.6
                need_adjust = True
            if min_val < bottom_limit:
                undershoot = (bottom_limit - min_val) / scale
                position += undershoot * 0.6
                need_adjust = True
            if not need_adjust:
                break
            position = round(position, 2)
            self._write_osc("set_vertical_position", self.channel, position)
            time.sleep(0.5)

    def _write_osc(self, action_name, *args):
        action = self.cmd_osc["actions"][action_name]
        cmd = assemble_cmd(action, *args)
        scpi_write(self.inst_osc, cmd, self.comm_type)

    def _query_osc(self, action_name, *args):
        action = self.cmd_osc["actions"][action_name]
        cmd = assemble_cmd(action, *args)
        return scpi_query(self.inst_osc, cmd, self.comm_type)

    def _write_calibrator(self, action_name, *args):
        action = self.cmd_calibrator["actions"][action_name]
        cmd = assemble_cmd(action, *args)
        scpi_write(self.inst_calibrator, cmd, self.cal_type)

    def init_devices(self):
        self._write_osc("preset")
        self._write_calibrator("preset")
        time.sleep(self.profile.get("init_time", 2))

    def setup_channel(self):
        if (
            self.profile.get("probe_default", 1) != 1
            and "set_probe_gain" in self.cmd_osc["actions"]
        ):
            self._write_osc("set_probe_gain", self.channel, 1)
        self._write_osc("set_channel", self.channel, "ON")
        self._write_osc("set_trigger_source", self.channel)

    def setup_impedance(self, impedance_keyword):
        if "set_impedance" in self.cmd_osc["actions"]:
            self._write_osc(
                "set_impedance", self.channel, self.cmd_osc["keyword"][impedance_keyword]
            )

    def setup_measurement(self, meas_keyword):
        scpi_setup_measurement(
            self.inst_osc, self.cmd_osc, self.channel, self.cmd_osc["keyword"][meas_keyword]
        )

    def print_title(self, title):
        console.print(
            Panel(f"[bold blue]{title}[/bold blue]  通道: CH{self.channel}", expand=False)
        )

    def make_table(self, title, columns):
        table = Table(title=title, show_lines=True)
        for col in columns:
            justify = col.get("justify", "right")
            style = col.get("style", "")
            table.add_column(col["name"], justify=justify, style=style)
        return table

    def add_result_row(self, table, row_data, limits=None, check_col=None, check_value=None):
        styled_row = list(row_data)
        if limits and check_col is not None:
            val = row_data[check_col] if check_value is None else check_value
            if isinstance(val, (int, float)) and (val < limits[0] or val > limits[1]):
                styled_row[check_col] = f"[red]{row_data[check_col]}[/red]"
        table.add_row(*[str(v) for v in styled_row])

    def run(self):
        raise NotImplementedError

    def get_results(self):
        return self.results
