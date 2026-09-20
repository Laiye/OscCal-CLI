"""simulate_calibrate.py — 用模拟仪器在本地运行完整校准流程。

无需真实示波器/校准仪，构造两个实现 pyvisa 接口（.write/.query）的模拟仪器，
共享一个 SimState 状态对象：校准仪 write 更新输出信号状态，示波器 query 据此
返回合理的测量值（幅度/DC 均值/周期/上升时间/过冲/最大最小值），并按一阶低通
模型模拟示波器频带滚降，使带宽校准能产生合理的 -3dB 结果。

用法示例：
    python simulate_calibrate.py                         # 默认跑全部 5 项，通道 1，9560 探头
    python simulate_calibrate.py --items amp,dc_gain     # 只跑指定项
    python simulate_calibrate.py --channel 1,2           # 多通道
    python simulate_calibrate.py --probe 9530            # 切换探头
    python simulate_calibrate.py --log-scpi --export     # 打印 SCPI 日志并导出 Excel
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

console = Console()


# ---------------------------------------------------------------------------
# 全局 patch：加速模拟（去除 sleep / 自动回答交互 prompt）
# ---------------------------------------------------------------------------

_real_sleep = time.sleep


def _patch_fast_mode(enable: bool):
    """启用快速模式：time.sleep 置空，click.prompt 自动返回默认值。"""
    if not enable:
        return
    time.sleep = lambda x: None
    try:
        import click as _click

        _real_prompt = _click.prompt

        def _auto_prompt(*args, **kwargs):
            return kwargs.get("default", 0)

        _click.prompt = _auto_prompt
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 共享状态：校准仪输出信号（示波器据此"测量"）
# ---------------------------------------------------------------------------


class SimState:
    """校准仪输出信号状态，示波器模拟器读取此状态计算测量响应。"""

    def __init__(self):
        self.shape = None  # DC / SQU / MARK / SIN / EDGE
        self.volt = 0.0  # 输出幅度（方波为 p-p，DC 为电平）
        self.freq = 0.0  # 正弦频率
        self.mark_period = 0.0  # MARK 周期
        self.edge_speed = 0.0  # EDGE 上升时间
        self.output = False  # 输出开关
        self.impedance = "10000"  # 校准仪输出阻抗（10000=1M, 50=50Ω）
        self.squ_polarity = "SYMM"

    def reset(self):
        self.__init__()


# ---------------------------------------------------------------------------
# 模拟 FLUKE 9500B 校准仪（pyvisa 接口）
# ---------------------------------------------------------------------------


class SimulatedCalibrator:
    """模拟校准仪：解析 SCPI write 更新 SimState；仅响应 *IDN? 查询。"""

    def __init__(self, state: SimState, idn: str = "FLUKE,9500B,SIM001,1.0"):
        self.state = state
        self.idn = idn
        self.log: list[tuple[str, str]] = []  # (direction, cmd)

    def write(self, cmd: str):
        self.log.append(("W", cmd))
        self._parse(cmd)
        return len(cmd)

    def query(self, cmd: str) -> str:
        self.log.append(("Q", cmd))
        if cmd.strip() == "*IDN?":
            return self.idn + "\n"
        return "0\n"

    def _parse(self, cmd: str):
        c = cmd.strip()
        cu = c.upper()
        if cu in ("*RST", "*CLS;*RST"):
            self.state.reset()
            return
        if cu.startswith("SOUR:SCOP:SHAP "):
            self.state.shape = c.split(" ", 1)[1]
        elif cu.startswith("SOUR:VOLT "):
            self.state.volt = float(c.split(" ", 1)[1])
        elif cu.startswith("SOUR:FREQ "):
            self.state.freq = float(c.split(" ", 1)[1])
        elif cu.startswith("OUTP "):
            self.state.output = c.split(" ", 1)[1].upper() == "ON"
        elif cu.startswith("ROUT:SIGN:IMP "):
            self.state.impedance = c.split(" ", 1)[1]
        elif cu.startswith("SOUR:PER "):
            self.state.mark_period = float(c.split(" ", 1)[1])
        elif cu.startswith("SOUR:PAR:SQU:POL "):
            self.state.squ_polarity = c.split(" ", 1)[1]
        elif cu.startswith("SOUR:PAR:EDGE:SPE "):
            self.state.edge_speed = float(c.split(" ", 1)[1])


# ---------------------------------------------------------------------------
# 模拟示波器（pyvisa 接口）
# ---------------------------------------------------------------------------

# 已知测量助记符 → 规范类型（兼容 long/short 形式与多厂家命名）
_MEAS_TYPE_MAP = {
    "AMPLITUDE": "amp",
    "AMP": "amp",
    # TBS1000/TDS1000/TDS2000/TPS2000 系列没有 AMPlitude 测量，幅度用 PK2pk
    "PK2PK": "amp",
    "MEAN": "mean",
    "CMEAN": "mean",
    "PERIOD": "period",
    "PERI": "period",
    "PER": "period",
    "MAXIMUM": "max",
    "MAX": "max",
    "VMAX": "max",
    "MINIMUM": "min",
    "MIN": "min",
    "VMIN": "min",
    "RISE": "risetime",
    "RIS": "risetime",
    "POVERSHOOT": "overshoot",
    "POV": "overshoot",
    "ROVE": "overshoot",
    "FREQUENCY": "freq",
    "FREQ": "freq",
}


class SimulatedOscilloscope:
    """模拟示波器：解析 SCPI write 维护内部状态，按测量类型返回合理响应。

    测量响应模型：
    - amp  (幅度)   = 校准仪 volt × 频率衰减 × (1+0.1% 增益误差)
    - mean (DC均值) = 校准仪 volt × (1+0.2% 误差)
    - period(周期)  = 校准仪 mark_period × (1-0.1% 误差)
    - max/min       = ±3×vertical_scale（落在 ±4×scale 内，避免触发垂直位置调整循环）
    - risetime      = edge_speed × 1.4（示波器测量值略大于探头标称）
    - overshoot     = 2.0%（典型值）
    频率衰减：一阶低通 1/sqrt(1+(f/bw)^2)，bw=SIM_BANDWIDTH_HZ，使带宽校准得 ~bw
    """

    def __init__(
        self,
        state: SimState,
        cmd_osc: dict,
        idn: str = "TEK,MDO34,SIM001,v1.0",
        sim_bandwidth_hz: float = 200e6,
    ):
        self.state = state
        self.cmd_osc = cmd_osc
        self.idn = idn
        self.sim_bandwidth_hz = sim_bandwidth_hz
        self.log: list[tuple[str, str]] = []

        self.meas_type = None  # 当前测量类型助记符（原始字符串）
        self.meas_source = None  # 当前测量源（如 CH1）
        self.vertical_scale: dict[str, float] = {}
        self.vertical_position: dict[str, float] = {}
        self.impedance: dict[str, str] = {}
        self.channel_on: dict[str, str] = {}
        self.trigger_source = None
        self.trigger_level: dict[str, float] = {}
        self.horizontal_scale = 1e-3
        self.acq_mode = None
        self.numav = 2
        self.acquire_state = None
        self.stop_after = None
        self.meas_method = None

    def write(self, cmd: str):
        self.log.append(("W", cmd))
        self._parse(cmd)
        return len(cmd)

    def query(self, cmd: str) -> str:
        self.log.append(("Q", cmd))
        c = cmd.strip()
        if c == "*IDN?":
            return self.idn + "\n"
        # 测量值查询（merge 模式：MEASUrement:IMMed:VALue? / split 模式：:MEAS:...?）
        if "?" in c and ("MEAS" in c.upper()):
            return self._measurement_response(c)
        return "0\n"

    # ---- SCPI 解析 ----

    def _parse(self, cmd: str):
        c = cmd.strip()
        cu = c.upper()
        if cu in ("FACTORY", "*RST", "*CLS;*RST", "FAC"):
            self._reset_state()
            return
        if cu.startswith("SELECT:CH"):
            rest = cu[len("SELECT:CH") :]
            ch = rest.split(" ")[0]
            val = c.split(" ", 1)[1] if " " in c else ""
            self.channel_on[ch] = val
        elif cu.startswith("CH") and ":SCA" in cu:
            ch = cu[2:].split(":")[0]
            self.vertical_scale[ch] = float(c.split(" ", 1)[1])
        elif cu.startswith("CH") and ":POS" in cu:
            ch = cu[2:].split(":")[0]
            self.vertical_position[ch] = float(c.split(" ", 1)[1])
        elif cu.startswith("CH") and ":TER" in cu:
            ch = cu[2:].split(":")[0]
            self.impedance[ch] = c.split(" ", 1)[1]
        elif cu.startswith("TRIGGER:A:EDGE:SOURCE"):
            self.trigger_source = c.split(" ", 1)[1] if " " in c else ""
        elif cu.startswith("TRIGGER:A:LEVEL:CH"):
            ch = cu[len("TRIGGER:A:LEVEL:CH") :].split(" ")[0]
            self.trigger_level[ch] = float(c.split(" ", 1)[1]) if " " in c else 0.0
        elif cu.startswith("HORIZONTAL:SCA"):
            self.horizontal_scale = float(c.split(" ", 1)[1])
        elif cu.startswith("ACQUIRE:MODE"):
            self.acq_mode = c.split(" ", 1)[1]
        elif cu.startswith("ACQUIRE:NUMAV"):
            self.numav = int(float(c.split(" ", 1)[1]))
        elif cu.startswith("ACQUIRE:STATE"):
            self.acquire_state = c.split(" ", 1)[1]
        elif cu.startswith("ACQUIRE:STOPA"):
            self.stop_after = c.split(" ", 1)[1]
        elif cu.startswith("MEASUREMENT:IMMED:SOURCE"):
            self.meas_source = c.split(" ", 1)[1] if " " in c else ""
        elif cu.startswith("MEASUREMENT:IMMED:TYPE"):
            self.meas_type = c.split(" ", 1)[1]
        elif cu.startswith("MEASUREMENT:METHOD"):
            self.meas_method = c.split(" ", 1)[1]
        # 其余指令忽略

    def _reset_state(self):
        self.meas_type = None
        self.meas_source = None
        self.vertical_scale.clear()
        self.vertical_position.clear()
        self.impedance.clear()
        self.channel_on.clear()
        self.trigger_source = None
        self.trigger_level.clear()
        self.horizontal_scale = 1e-3
        self.acq_mode = None
        self.numav = 2
        self.acquire_state = None
        self.stop_after = None

    # ---- 测量响应 ----

    def _current_channel(self) -> str:
        src = (self.meas_source or "").upper()
        if src.startswith("CHAN"):
            return src[4:].split(":")[0]
        if src.startswith("CH"):
            return src[2:].split(":")[0]
        return "1"

    def _resolve_meas_type(self, query_cmd: str) -> str:
        """从 meas_type 状态或查询指令本身解析规范测量类型。"""
        if self.meas_type:
            t = _MEAS_TYPE_MAP.get(self.meas_type.upper())
            if t:
                return t
        # split 模式：从查询指令中提取助记符
        cu = query_cmd.upper()
        for token in cu.replace("?", " ").replace(",", " ").split():
            t = _MEAS_TYPE_MAP.get(token)
            if t:
                return t
        return ""

    def _attenuation(self, freq: float) -> float:
        if freq <= 0:
            return 1.0
        return 1.0 / math.sqrt(1.0 + (freq / self.sim_bandwidth_hz) ** 2)

    def _compute_value(self, meas_kind: str) -> float:
        st = self.state
        ch = self._current_channel()
        scale = self.vertical_scale.get(ch, 0.1)

        if meas_kind == "amp":
            # 幅度 = 校准仪输出幅度 × 频率衰减 × 0.1% 增益误差
            return st.volt * self._attenuation(st.freq) * 1.001
        if meas_kind == "mean":
            # DC 均值 = 校准仪 DC 电平 × 0.2% 误差
            return st.volt * 1.002
        if meas_kind == "period":
            # 周期 = MARK 周期 × (1-0.1% 误差)
            return st.mark_period * 0.999 if st.mark_period > 0 else 1e-6
        if meas_kind == "max":
            # +3 div，落在 ±4 div 内，不触发垂直位置调整
            return scale * 3
        if meas_kind == "min":
            return -scale * 3
        if meas_kind == "risetime":
            return st.edge_speed * 1.4 if st.edge_speed > 0 else 0.5e-9
        if meas_kind == "overshoot":
            return 2.0
        if meas_kind == "freq":
            return 1.0 / st.mark_period if st.mark_period > 0 else 1e6
        return 0.0

    def _measurement_response(self, query_cmd: str) -> str:
        kind = self._resolve_meas_type(query_cmd)
        value = self._compute_value(kind)
        feature = self.cmd_osc.get("feature", {}) if self.cmd_osc else {}
        idx = feature.get("return_value_index", 0)
        # return_value_index=1（Tek merge）：响应形如 ":MEASUREMENT:IMMED:VALUE <val>"
        if idx == 1:
            return f":MEASUREMENT:IMMED:VALUE {value:.12g}\n"
        return f"{value:.12g}\n"


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_configs(commands_name: str, profile_name: str, calibrator_name: str):
    cmd_osc = _load_json(PROJECT_ROOT / "commands" / f"{commands_name}.json")
    profile = _load_json(PROJECT_ROOT / "profiles" / f"{profile_name}.json")
    cmd_cal = _load_json(PROJECT_ROOT / "calibrators" / f"{calibrator_name}.json")
    return cmd_osc, profile, cmd_cal


# ---------------------------------------------------------------------------
# 运行校准流程
# ---------------------------------------------------------------------------


def run_calibration(args):
    cmd_osc, profile, cmd_cal = load_configs(args.commands, args.profile, args.calibrator)

    # 注入带宽参数到 profile（与 cli.py 行为一致，单位 Hz）
    profile["bandwidth"] = int(args.bandwidth * 1e6)
    profile["bd_step"] = int(args.bd_step * 1e6)

    # 构造模拟仪器
    state = SimState()
    idn_osc = f"TEK,{profile.get('series', 'MDO34')},SIM001,v1.0"
    inst_cal = SimulatedCalibrator(state, idn="FLUKE,9500B,SIM001,1.0")
    inst_osc = SimulatedOscilloscope(
        state,
        cmd_osc,
        idn=idn_osc,
        sim_bandwidth_hz=args.sim_bandwidth * 1e6,
    )

    console.print(
        Panel.fit(
            f"[bold blue]模拟校准流程[/bold blue]\n"
            f"示波器: {profile.get('series')}  通道: {args.channel}  探头: {args.probe}\n"
            f"指令集: {cmd_osc.get('name')}  校准仪: {cmd_cal.get('name')}\n"
            f"校准项目: {args.items}  带宽: {args.bandwidth}MHz  步进: {args.bd_step}MHz\n"
            f"模拟 -3dB 带宽: {args.sim_bandwidth}MHz",
            title="OscCal-CLI 模拟运行",
            border_style="blue",
        )
    )

    item_list = [x.strip() for x in args.items.split(",") if x.strip()]
    channel_list = [c.strip() for c in args.channel.split(",") if c.strip()]

    all_results = {}
    for ch in channel_list:
        console.rule(f"[bold magenta]通道 CH{ch}[/bold magenta]")
        if "all" in item_list:
            from osccal.measure.all import run_all

            ch_results = run_all(inst_osc, inst_cal, cmd_osc, cmd_cal, profile, ch, args.probe)
            for key, val in ch_results.items():
                result_key = f"{key}_ch{ch}" if len(channel_list) > 1 else key
                all_results[result_key] = val
        else:
            for item in item_list:
                from osccal.measure.registry import CALIBRATORS_MAP

                CalClass = CALIBRATORS_MAP.get(item)
                if not CalClass:
                    console.print(f"[red]✗[/red] 未知校准项目: {item}")
                    continue
                cal = CalClass(inst_osc, inst_cal, cmd_osc, cmd_cal, profile, ch, args.probe)
                cal.run()
                result_key = f"{item}_ch{ch}" if len(channel_list) > 1 else item
                all_results[result_key] = cal.get_results()

    return inst_osc, inst_cal, profile, all_results


# ---------------------------------------------------------------------------
# SCPI 日志与结果汇总
# ---------------------------------------------------------------------------


def print_scpi_log(inst_osc: SimulatedOscilloscope, inst_cal: SimulatedCalibrator, full: bool):
    console.rule("[bold cyan]SCPI 指令日志[/bold cyan]")

    summary = Table(title="指令统计", show_lines=True)
    summary.add_column("仪器", style="cyan")
    summary.add_column("写入", justify="right")
    summary.add_column("查询", justify="right")
    summary.add_column("合计", justify="right")
    osc_w = sum(1 for d, _ in inst_osc.log if d == "W")
    osc_q = sum(1 for d, _ in inst_osc.log if d == "Q")
    cal_w = sum(1 for d, _ in inst_cal.log if d == "W")
    cal_q = sum(1 for d, _ in inst_cal.log if d == "Q")
    summary.add_row("示波器", str(osc_w), str(osc_q), str(osc_w + osc_q))
    summary.add_row("校准仪", str(cal_w), str(cal_q), str(cal_w + cal_q))
    console.print(summary)

    if not full:
        return

    log_table = Table(title="完整 SCPI 指令序列", show_lines=False)
    log_table.add_column("#", justify="right", style="dim")
    log_table.add_column("仪器", style="cyan")
    log_table.add_column("方向", style="magenta")
    log_table.add_column("指令")
    for i, (inst_name, direction, cmd) in enumerate(_interleave_log(inst_osc, inst_cal), 1):
        log_table.add_row(str(i), inst_name, direction, cmd)
    console.print(log_table)


def _interleave_log(inst_osc, inst_cal):
    """按调用顺序合并两个仪器的日志（粗略按索引交错，便于阅读）。"""
    osc_iter = iter(inst_osc.log)
    cal_iter = iter(inst_cal.log)
    # 简单策略：轮流取一条，直到都取完
    result = []
    while True:
        advanced = False
        try:
            d, c = next(osc_iter)
            result.append(("示波器", "W" if d == "W" else "Q", c))
            advanced = True
        except StopIteration:
            pass
        try:
            d, c = next(cal_iter)
            result.append(("校准仪", "W" if d == "W" else "Q", c))
            advanced = True
        except StopIteration:
            pass
        if not advanced:
            break
    return result


def print_results_summary(all_results: dict):
    console.rule("[bold green]结果汇总[/bold green]")
    table = Table(title="校准结果汇总", show_lines=True)
    table.add_column("项目", style="cyan")
    table.add_column("数据点数", justify="right")
    table.add_column("说明")
    for key, rows in all_results.items():
        if not rows:
            table.add_row(key, "0", "[red]无数据[/red]")
            continue
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            errs = [r.get("error", 0) for r in rows if "error" in r]
            if errs:
                max_err = max(abs(e) for e in errs)
                status = (
                    "[green]合格[/green]"
                    if max_err <= 2.0
                    else f"[red]超差(最大{max_err:.2f}%)[/red]"
                )
                table.add_row(key, str(len(rows)), f"误差范围 ±{max_err:.2f}%  {status}")
            elif "bandwidth_mhz" in rows[0]:
                bws = [r.get("bandwidth_mhz", 0) for r in rows]
                table.add_row(key, str(len(rows)), f"带宽 {min(bws):.1f}~{max(bws):.1f} MHz")
            elif "risetime_ns" in rows[0]:
                r = rows[0]
                overshoot = r.get("pos_overshoot")
                # 机型无正过冲测量时 pos_overshoot 为 None → 显示"不适用"
                overshoot_text = "不适用" if overshoot is None else f"{overshoot:.2f}%"
                table.add_row(
                    key,
                    str(len(rows)),
                    f"上升时间 {r.get('risetime_ns', 0):.2f} ns, 过冲 {overshoot_text}",
                )
            else:
                table.add_row(key, str(len(rows)), "")
        else:
            table.add_row(key, str(len(rows)), "")
    console.print(table)


def save_and_export(all_results: dict, profile: dict, args):
    """保存校准数据 JSON 并导出 Excel 报告。"""
    metadata = {
        "channel": "",
        "probe": args.probe,
        "oscilloscope": {
            "manufacturer": "TEK",
            "model": profile.get("series", ""),
            "serial": "SIM001",
            "firmware": "v1.0",
        },
        "calibrator": {
            "manufacturer": "FLUKE",
            "model": "9500B",
            "serial": "SIM001",
            "firmware": "1.0",
        },
        "commands_file": f"{args.commands}.json",
        "profile_file": f"{args.profile}.json",
        "calibrator_file": f"{args.calibrator}.json",
        "simulated": True,
        "limits": profile.get("calibration_limits", {}),
    }
    from osccal.core.storage import save_calibration_data

    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    json_path = save_calibration_data(all_results, metadata)
    console.print(f"[green]✓[/green] 数据已保存: {json_path}")

    try:
        from osccal.core.export import export_to_excel

        ts = time.strftime("%Y%m%d_%H%M%S")
        xlsx_path = str(data_dir / f"sim_calibration_{ts}.xlsx")
        export_to_excel({"metadata": metadata, "results": all_results}, xlsx_path)
        console.print(f"[green]✓[/green] Excel 已导出: {xlsx_path}")
    except Exception as e:
        console.print(f"[red]✗[/red] Excel 导出失败: {e}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    from osccal.core.utils import enable_utf8_output

    enable_utf8_output()

    parser = argparse.ArgumentParser(description="用模拟仪器本地运行完整校准流程")
    parser.add_argument("--commands", default="tektronix_mdo3", help="指令集文件名（不含.json）")
    parser.add_argument("--profile", default="tektronix_mdo34", help="Profile 文件名（不含.json）")
    parser.add_argument("--calibrator", default="fluke_9500b", help="校准仪配置文件名（不含.json）")
    parser.add_argument(
        "--items",
        default="all",
        help="校准项目，逗号分隔（amp,dc_gain,delta_time,bandwidth,transient,all）",
    )
    parser.add_argument("--channel", default="1", help="通道，逗号分隔（如 1,2）")
    parser.add_argument("--probe", default="9560", help="探头型号（9560/9550/9530）")
    parser.add_argument("--bandwidth", type=float, default=100.0, help="起始带宽（MHz）")
    parser.add_argument("--bd-step", type=float, default=20.0, help="带宽扫描步进（MHz）")
    parser.add_argument(
        "--sim-bandwidth", type=float, default=200.0, help="模拟示波器 -3dB 带宽（MHz）"
    )
    parser.add_argument("--log-scpi", action="store_true", help="打印完整 SCPI 指令日志")
    parser.add_argument("--export", action="store_true", help="保存数据并导出 Excel")
    parser.add_argument("--real-sleep", action="store_true", help="保留真实 sleep 延时（默认加速）")
    args = parser.parse_args()

    _patch_fast_mode(not args.real_sleep)

    try:
        inst_osc, inst_cal, profile, all_results = run_calibration(args)
        print_results_summary(all_results)
        print_scpi_log(inst_osc, inst_cal, args.log_scpi)
        if args.export:
            save_and_export(all_results, profile, args)
    except Exception as e:
        console.print(f"[red]✗ 模拟运行失败: {e}[/red]")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
