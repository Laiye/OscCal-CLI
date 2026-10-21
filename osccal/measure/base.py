import time
from functools import wraps

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from osccal.core.comm import (
    read_measurement,
    scpi_query,
    scpi_query_raw,
    scpi_setup_measurement,
    scpi_write,
    set_write_delay,
)
from osccal.core.command import assemble_cmd

console = Console()

#: 等待单次采集结束的最长时间（秒）。
ACQUIRE_TIMEOUT_SECONDS = 5.0
#: 触发单次采集后先静置的时间（秒）：过短会读到半填记录。
ACQUIRE_SETTLE_SECONDS = 0.6


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
        self,
        inst_osc,
        inst_calibrator,
        cmd_osc,
        cmd_calibrator,
        profile,
        channel,
        probe=None,
        points=None,
    ):
        self.inst_osc = inst_osc
        self.inst_calibrator = inst_calibrator
        self.cmd_osc = cmd_osc
        self.cmd_calibrator = cmd_calibrator
        self.profile = profile
        self.channel = str(channel)
        self.probe = probe
        # 本轮该项目的校准点（由 core/points.py 按规范解析得到），不再是 Profile 里的点表。
        self.points = list(points or [])
        self.comm_type = cmd_osc.get("type", "pyvisa")
        self.cal_type = cmd_calibrator.get("type", "pyvisa")
        self.results = []
        # 触发电平微调方向（每次调用翻转，保证相对上一次都是有效变化）
        self._level_nudge_sign = 1
        # 指令间隔由指令集声明：少数机型背靠背连续写入会静默丢指令（实测 UPO1104X），
        # 未声明或为 0 时不节流，既有各机型时序不变。
        set_write_delay(cmd_osc.get("feature", {}).get("write_delay_ms", 0))

    def _get_measurement_averages(self) -> int:
        """本次测量使用的平均次数（Profile 未声明时为 16，保持既有行为）。"""
        averages = self.profile.get("averages", 16)
        return averages if isinstance(averages, int) and averages >= 2 else 16

    def _get_meas_amp_scale(self) -> float:
        """幅度测量的换算系数（指令集未声明 feature.meas_amp_scale 时为 1）。

        标准值口径是屏幕中部的 6 格**峰峰值**：`PK2pk`/`AMPlitude` 直接就是该口径；
        没有幅度测量的机型用 `CRMs`（第一周期真有效值），对称方波的有效值等于
        **幅度**（即峰峰值的一半），故需按 2 换算后再与标准值比较。
        """
        value = self.cmd_osc.get("feature", {}).get("meas_amp_scale", 1.0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return 1.0
        return float(value)

    def _nudge_trigger_level(self, scale: float) -> None:
        """换挡位后微调触发电平，迫使示波器重新开始平均。

        平均模式下示波器可能沿用上一次的累加平均（现场表现为"粘滞"），手册
        ACQuire:NUMACq? 说明：改变触发参数会复位平均序列（Sample/PeakDetect 模式下
        改触发电平不复位，Average 模式下复位）。微调量取当前挡位的 0.1 格：
        既大于触发电平 DAC 的分辨率（保证示波器确实发生状态变化），
        又远小于被测波形幅度（不影响测量）；符号逐次翻转以确保每次都是有效变化。
        """
        if "set_trigger_level" not in self.cmd_osc.get("actions", {}):
            return
        level = 0.1 * scale * self._level_nudge_sign
        self._level_nudge_sign = -self._level_nudge_sign
        action = self.cmd_osc["actions"]["set_trigger_level"]
        if action.get("args_num", 0) >= 2:
            self._write_osc("set_trigger_level", self.channel, level)
        else:
            self._write_osc("set_trigger_level", level)

    def _get_limits(self, item_name):
        """参考指标来自规范（specs/*.json），Profile 不再持有判据。"""
        return None

    def _apply_impedance(self, label: str) -> None:
        """把示波器与校准仪的输入阻抗同时切到 1 MΩ 或 50 Ω。

        切换前先关输出，避免在校准仪输出有效电平时改变负载。
        """
        key = "imp_fif" if label == "50" else "imp_meg"
        if label == "50" and not self.profile.get("imp_has_50", False):
            raise ValueError("该机型不支持 50 Ω 输入阻抗")
        self._write_calibrator("set_output", "OFF")
        self.setup_impedance(key)
        self._write_calibrator("set_impedance", self.cmd_calibrator["keyword"][key])

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
        # 单次采集模式下，改完激励/时基若不重新采集，MEASU:IMM:VAL 会返回**上一次**
        # 的读数（实机：30 MHz 的读数一直延续到 300 kHz 的点上）。读数前先取新数据。
        self._run_single_acquisition()
        return read_measurement(self.inst_osc, None, self.cmd_osc, self.channel, actual_keyword)

    def _run_single_acquisition(self, wait_seconds: float = 0.3) -> None:
        """触发一次单次采集并**等它真正结束**；指令集未声明采集控制时静默跳过。

        只靠 `*OPC?` 不够稳：实机出现过采集尚未开始时 `*OPC?` 就返回，取回的是刚
        清空/半填的记录（幅度只有正常的 1/64，拟合于是锁定到噪声上）。改为轮询
        `ACQuire:STATE?`，等它从 RUN(1) 回到 STOP(0) 再返回。
        """
        actions = self.cmd_osc.get("actions", {})
        if "set_acquire_stop_after" not in actions or "set_acquire_state" not in actions:
            return
        keywords = self.cmd_osc.get("keyword", {})
        self._write_osc("set_acquire_stop_after", keywords["acquire_stop_after_single"])
        # 先显式 STOP 再 RUN 重新布防：连续两次单次采集时，若直接写 RUN，示波器
        # 会给出与时间轴不匹配的记录（实测拟合频率偏离 3~5 倍）。
        self._write_osc("set_acquire_state", keywords.get("acquire_state_stop", "STOP"))
        time.sleep(0.05)
        self._write_osc("set_acquire_state", keywords["acquire_state_run"])
        # 先给示波器足够的重新布防时间：实测 0.3 s 太短，状态查询会在采集真正开始
        # 前就返回"已停止"，取回的是半填的记录（幅度只有正常值的一小部分）。
        time.sleep(max(wait_seconds, ACQUIRE_SETTLE_SECONDS))

        if "query_acquire_state" in actions:
            deadline = time.monotonic() + ACQUIRE_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                try:
                    raw = str(self._query_osc("query_acquire_state"))
                except Exception:  # noqa: BLE001 - 查询失败退回固定等待
                    break
                tokens = [token for token in raw.replace("\n", " ").split() if token]
                if tokens and tokens[-1] in {"0", "0.0"}:
                    return
                time.sleep(0.1)
        try:
            scpi_query(self.inst_osc, "*OPC?", self.comm_type)
        except Exception:  # noqa: BLE001 - 个别机型不支持 *OPC?，退回固定等待
            time.sleep(wait_seconds)

    def _read_waveform(self, samples: int, fresh: bool = True):
        """读回当前通道波形（二进制块），返回 core.waveform.Waveform。

        `fresh=False` 表示复用刚刚那次采集（调用方已通过 _read_meas 触发过）：
        示波器在"连续两次单次采集"时会返回与时间轴不匹配的记录，复用同一次
        采集既避免该问题，也保证测量值与波形来自同一份数据。
        """
        from osccal.core.waveform import build_waveform, parse_block, parse_preamble

        required = (
            "set_wave_source",
            "set_wave_encoding",
            "set_wave_width",
            "set_wave_start",
            "set_wave_stop",
            "query_wave_preamble",
            "query_wave_data",
        )
        missing = [name for name in required if name not in self.cmd_osc.get("actions", {})]
        if missing:
            raise ValueError(f"指令集未声明波形读回能力，缺少 action: {missing}")

        # 先取一次全新采集：改完时基/激励后若示波器处于停止或单次状态，
        # CURVe? 会返回上一次的陈旧记录（实机表现为拟合频率与读数差一个量级）。
        if fresh:
            self._run_single_acquisition()
        self._write_osc("set_wave_source", self.channel)
        self._write_osc("set_wave_encoding", "RIBinary")
        self._write_osc("set_wave_width", "2")
        self._write_osc("set_wave_start", 1)
        self._write_osc("set_wave_stop", self._waveform_stop(samples))
        preamble = parse_preamble(self._query_osc("query_wave_preamble"))
        action = self.cmd_osc["actions"]["query_wave_data"]
        raw = scpi_query_raw(self.inst_osc, assemble_cmd(action), self.comm_type)
        return build_waveform(parse_block(raw), preamble)

    def _waveform_stop(self, samples: int) -> int:
        """取点数上限：不得超过示波器的实际记录长度。

        实机教训（MDO3052）：把 `DATa:STOP` 写成远超记录长度的值（如 2000000），
        示波器会把**整条记录抽点**成 10000 点返回，而 `WFMOutpre:XINcr` 仍按原始
        记录给出。结果是 8 ms 的数据被标成 1 ms，3 kHz 正弦看上去有 8 倍频率。
        因此先读实际记录长度，再取两者的较小值。
        """
        if "query_record_length" not in self.cmd_osc.get("actions", {}):
            return samples
        try:
            raw = str(self._query_osc("query_record_length"))
        except Exception:  # noqa: BLE001 - 读不到就退回调用方的值
            return samples
        for token in reversed(raw.replace("\n", " ").split()):
            try:
                length = int(float(token))
            except ValueError:
                continue
            if length > 0:
                return min(samples, length)
        return samples

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
        # 整屏电压与允许的最大位移（本调整只为把略微超出格线的波形挪回格内）
        screen = vertical_div * scale
        max_shift = half_div * scale
        position = 0.0
        for _ in range(5):
            max_val = self._read_meas("meas_max")
            min_val = self._read_meas("meas_min")
            # 波形远超整屏时（例如挡位与信号不匹配，或刚换挡读到尚未刷新的旧数据），
            # 按超屏量换算出的位移会大到把波形整个推出屏幕——实机出现过算出 -45.6 V
            # 偏移，之后所有测量都返回无效值。这种情况属于挡位问题而非位置问题，
            # 直接跳过自动调整，避免把可恢复的读数问题变成整项失败。
            if abs(max_val) > 2 * screen or abs(min_val) > 2 * screen:
                console.print(
                    f"[yellow]⚠ 波形远超当前挡位量程"
                    f"（max={max_val:.4g} V, min={min_val:.4g} V，整屏 {screen:.4g} V），"
                    f"跳过垂直位置自动调整[/yellow]"
                )
                return
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
            # 先按既有精度取整，再限幅：保证写入的偏移绝不超过半屏电压
            position = max(-max_shift, min(max_shift, round(position, 2)))
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

    def _query_calibrator(self, action_name, *args):
        action = self.cmd_calibrator["actions"][action_name]
        cmd = assemble_cmd(action, *args)
        return scpi_query(self.inst_calibrator, cmd, self.cal_type)

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

    def _set_timebase(self, seconds_per_div: float) -> float | None:
        """设置水平挡位，返回**实际生效**的挡位（读不回来时返回 None）。

        两件事都必须做对：
        1. 显式设时基。`*RST` 后时基可能是 4 µs/div，1 kHz 方波在屏上只占
           0.04 个周期，幅度测量直接返回无效值 9.9E+37。
        2. 回读校验。示波器的水平挡位是离散序列（MDO3052 为 1-2-4-8 序列，
           **没有 1 µs/div**，写 1 µs 会静默吸附到 800 ns/div），只按设定值记录
           会让报告里的挡位与实际不符。
        """
        if "set_horizontal_scale" not in self.cmd_osc.get("actions", {}):
            return None
        self._write_osc("set_horizontal_scale", seconds_per_div)
        if "query_horizontal_scale" not in self.cmd_osc.get("actions", {}):
            return None
        try:
            raw = self._query_osc("query_horizontal_scale")
        except Exception:  # noqa: BLE001 - 回读失败不影响设定本身
            return None
        tokens = str(raw).replace("\n", " ").split()
        for token in reversed(tokens):
            try:
                value = float(token)
            except ValueError:
                continue
            if value > 0:
                return value
        return None

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
