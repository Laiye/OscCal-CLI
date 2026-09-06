import os

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from osccal.core.config import list_config_files, load_calibrator, load_commands, load_profile
from osccal.core.connect import (
    close_all_connections,
    connect_socket,
    connect_visa,
    list_visa_resources,
)

console = Console()


# ── 交互选择辅助 ─────────────────────────────────────────────────────────


def _auto_detect_probe(inst_calibrator, probes: dict) -> str | None:
    """查询校准仪当前装载的探头型号，自动匹配。"""
    try:
        head_raw = inst_calibrator.query("ROUT:FITT? CH1")
        head_id = head_raw.strip().strip('"').strip("'")
        # FLUKE 9500B 返回格式如 "9560" 或 "9560, " 带尾随逗号
        head_id = head_id.rstrip(",").strip()
        for pk in probes:
            if head_id == pk or pk in head_id:
                console.print(
                    f"[green]✓[/green] 自动识别探头: [cyan]{pk}[/cyan] (查询结果: {head_id})"
                )
                return pk
        console.print(
            f"[dim]⊘[/dim] 探头查询结果 [cyan]{head_id}[/cyan] 未匹配已知型号 {list(probes.keys())}"
        )
    except Exception:
        console.print("[dim]⊘[/dim] 无法查询探头型号，回退手动选择")
    return None


def _select_probe_interactive(cmd_calibrator: dict) -> str | None:
    """交互式选择探头型号。"""
    probes = cmd_calibrator.get("probes", {})
    if not probes:
        return None
    probe_keys = list(probes.keys())
    imp_rules = cmd_calibrator.get("impedance_rules", {})
    console.print("\n[bold]选择校准仪探头:[/bold]")
    for i, pk in enumerate(probe_keys):
        supported = list(imp_rules.get(pk, {}).keys())
        desc = f"{pk} (支持模式: {', '.join(supported)})"
        console.print(f"  [{i}] {desc}")
    choice = click.prompt("请选择", type=int, default=0)
    return probe_keys[choice]


def _select_channel() -> str:
    """交互式选择校准通道。"""
    console.print("\n[bold]选择校准通道:[/bold]")
    console.print("  [0] CH1 (默认)")
    console.print("  [1] CH2")
    console.print("  [2] CH3")
    console.print("  [3] CH4")
    console.print("  [4] CH1 + CH2")
    console.print("  [5] CH1 + CH2 + CH3")
    console.print("  [6] CH1 + CH2 + CH3 + CH4")
    console.print("  也可直接输入通道号，如: 1,2,3")
    ch_input = click.prompt("请选择或输入", default="0")
    presets = {"0": "1", "1": "2", "2": "3", "3": "4", "4": "1,2", "5": "1,2,3", "6": "1,2,3,4"}
    return presets.get(ch_input, ch_input)


def _pick_channel(channel_arg: str | None) -> str:
    """返回通道参数；未通过命令行指定时交互选择。"""
    if channel_arg:
        return channel_arg
    return _select_channel()


def _select_items() -> str:
    """交互式选择校准项目。"""
    console.print("\n[bold]选择校准项目:[/bold]")
    console.print("  [0] 全部项目")
    console.print("  [1] 幅度(ΔV)")
    console.print("  [2] 直流增益")
    console.print("  [3] Δt(时间)")
    console.print("  [4] 频带宽度")
    console.print("  [5] 上升时间及过冲")
    console.print("  也可输入序号多选(逗号分隔)，如: 1,3")
    choice = click.prompt("请选择或输入", default="0")
    presets = {
        "0": "all",
        "1": "amp",
        "2": "dc_gain",
        "3": "delta_time",
        "4": "bandwidth",
        "5": "transient",
    }
    if "," in choice:
        return ",".join(presets.get(c.strip(), c.strip()) for c in choice.split(","))
    return presets.get(choice, choice)


# ── 配置加载辅助 ─────────────────────────────────────────────────────────


def _load_calibrator_config(calibrators_dir: str, path: str | None = None):
    """加载校准仪配置：指定路径或自动加载目录下首个。返回 (配置, 文件路径)。"""
    if path:
        return load_calibrator(path), path
    files = list_config_files(calibrators_dir)
    if not files:
        console.print("[red]✗[/red] 未找到校准仪配置文件")
        return {}, ""
    fpath = os.path.join(calibrators_dir, files[0])
    return load_calibrator(fpath), fpath


def _load_commands_config(commands_dir: str, path: str | None = None):
    """加载示波器指令集：指定路径或交互选择。"""
    if path:
        return load_commands(path)
    files = list_config_files(commands_dir)
    if not files:
        console.print("[red]✗[/red] 未找到示波器指令集文件")
        return {}
    console.print("\n[bold]选择示波器指令集:[/bold]")
    for i, f in enumerate(files):
        console.print(f"  [{i}] {f}")
    choice = click.prompt("请选择", type=int, default=0)
    return load_commands(os.path.join(commands_dir, files[choice]))


def _load_profile_config(profiles_dir: str, path: str | None = None):
    """加载示波器特征配置：指定路径或交互选择。"""
    if path:
        return load_profile(path)
    files = list_config_files(profiles_dir)
    if not files:
        console.print("[red]✗[/red] 未找到示波器特征文件")
        return {}
    console.print("\n[bold]选择示波器特征配置:[/bold]")
    for i, f in enumerate(files):
        console.print(f"  [{i}] {f}")
    choice = click.prompt("请选择", type=int, default=0)
    return load_profile(os.path.join(profiles_dir, files[choice]))


# ── 连接辅助 ─────────────────────────────────────────────────────────────


def _list_resources_safely() -> list[str]:
    """列出 VISA 资源，异常时返回空列表。"""
    try:
        return list_visa_resources()
    except Exception:
        console.print("[yellow]⚠[/yellow] VISA 资源扫描失败（可能未安装 VISA 驱动）")
        return []


def _pick_resource(resources: list[str], title: str) -> str:
    """从资源列表交互选择一项。"""
    console.print(f"\n[bold]{title}:[/bold]")
    for i, r in enumerate(resources):
        console.print(f"  [{i}] {r}")
    choice = click.prompt("请选择", type=int, default=0)
    return resources[choice]


def _connect_calibrator(resource_cal: str | None, resources: list[str], interactive: bool = True):
    """连接校准仪：优先 --resource-cal，其次资源列表，最后交互输入。"""
    if resource_cal:
        return connect_visa(resource_cal)
    if resources:
        if not interactive:
            return connect_visa(resources[0])
        return connect_visa(_pick_resource(resources, "选择校准仪资源"))
    if interactive:
        resource_str = click.prompt(
            "\n请输入校准仪 VISA 资源地址", type=str, default="GPIB0::19::INSTR"
        )
        return connect_visa(resource_str)
    return None, {}


def _connect_oscilloscope(cmd_osc, resource_osc, socket_osc, resources, interactive: bool = True):
    """连接示波器：按指令集类型（socket/visa）与命令行参数解析连接方式。"""
    comm_type = cmd_osc.get("type", "pyvisa")
    if comm_type == "socket":
        if socket_osc:
            host, port = socket_osc.split(":")
            return connect_socket(host, int(port))
        if interactive:
            console.print("\n[bold]Socket 连接示波器:[/bold]")
            host = click.prompt("请输入示波器 IP 地址", type=str)
            port = click.prompt("请输入示波器端口", type=int, default=5025)
            return connect_socket(host, port)
        return None, {}
    if socket_osc:
        host, port = socket_osc.split(":")
        return connect_socket(host, int(port))
    if resource_osc:
        return connect_visa(resource_osc)
    if resources:
        if not interactive:
            return connect_visa(resources[0])
        return connect_visa(_pick_resource(resources, "选择示波器资源"))
    return None, {}


# ── SCPI 日志输出 ────────────────────────────────────────────────────────


def _print_scpi_log(max_entries: int = 200) -> None:
    """打印本次校准会话的 SCPI 指令日志与失败统计。"""
    from osccal.core import scpi_trace

    log = scpi_trace.get_log()
    failures = scpi_trace.failure_count()
    console.rule("[bold cyan]SCPI 指令日志[/bold cyan]")

    summary = Table(title="指令统计", show_lines=True)
    summary.add_column("统计项", style="cyan")
    summary.add_column("数量", justify="right")
    summary.add_row("写入", str(sum(1 for d, _, _ in log if d == "W")))
    summary.add_row("查询", str(sum(1 for d, _, _ in log if d == "Q")))
    summary.add_row("失败", str(failures))
    console.print(summary)

    if not log:
        return
    log_table = Table(title="完整 SCPI 指令序列", show_lines=False)
    log_table.add_column("#", justify="right", style="dim")
    log_table.add_column("方向", style="magenta")
    log_table.add_column("指令")
    log_table.add_column("结果", style="dim", overflow="fold", max_width=60)
    start = max(0, len(log) - max_entries)
    for i, (direction, cmd, result) in enumerate(log[start:], start + 1):
        log_table.add_row(str(i), direction, cmd, result)
    if start > 0:
        console.print(f"[dim]（仅显示最近 {max_entries} 条，共 {len(log)} 条）[/dim]")
    console.print(log_table)


# ── 命令定义 ─────────────────────────────────────────────────────────────


@click.group()
@click.version_option(version="0.1.0", prog_name="osccal")
def cli():
    """OscCal-CLI - 示波器自动校准系统"""
    pass


@cli.command()
@click.option("--osc", type=click.Path(exists=True), help="示波器指令集配置文件路径")
@click.option("--profile", type=click.Path(exists=True), help="示波器特征配置文件路径")
@click.option("--calibrator", type=click.Path(exists=True), help="校准仪配置文件路径")
@click.option("--channel", type=click.STRING, default=None, help="校准通道，逗号分隔 (1,2,3,4)")
@click.option("--probe", type=click.STRING, default=None, help="校准仪探头型号 (9560/9550/9530)")
@click.option(
    "--items",
    type=click.STRING,
    default=None,
    help="校准项目，逗号分隔 (amp,dc_gain,delta_time,bandwidth,transient,all)",
)
@click.option("--resource-osc", type=click.STRING, help="示波器 VISA 资源地址")
@click.option("--resource-cal", type=click.STRING, help="校准仪 VISA 资源地址")
@click.option("--socket-osc", type=click.STRING, help="示波器 Socket 地址 (host:port)")
@click.option("--bandwidth", type=click.FLOAT, default=None, help="示波器标称带宽 (MHz)")
@click.option("--bd-step", type=click.FLOAT, default=None, help="带宽扫描步进 (MHz)")
@click.option("--auto", is_flag=True, help="自动扫描 VISA 资源，根据 *IDN? 识别设备并匹配配置")
@click.option("--log-scpi", is_flag=True, help="打印完整 SCPI 指令日志与失败统计")
def calibrate(
    osc,
    profile,
    calibrator,
    channel,
    probe,
    items,
    resource_osc,
    resource_cal,
    socket_osc,
    bandwidth,
    bd_step,
    auto,
    log_scpi,
):
    """执行示波器校准流程"""
    from osccal.core import scpi_trace
    from osccal.core.storage import save_calibration_data

    scpi_trace.reset()
    scpi_trace.set_log_enabled(log_scpi)

    console.print(Panel("[bold blue]OscCal-CLI[/bold blue] - 示波器自动校准系统", expand=False))

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_dir = base_dir
    commands_dir = os.path.join(project_dir, "commands")
    profiles_dir = os.path.join(project_dir, "profiles")
    calibrators_dir = os.path.join(project_dir, "calibrators")

    try:
        if auto:
            # ── 自动模式：扫描 VISA、识别设备、匹配配置 ──
            from osccal.core.auto_detect import detect_configs, print_auto_detection_summary
            from osccal.core.connect import _parse_idn

            console.print("\n[bold]自动扫描 VISA 资源...[/bold]")
            try:
                import pyvisa
            except ImportError:
                console.print("[red]✗[/red] pyvisa 未安装，请运行: pip install pyvisa")
                return

            try:
                rm = pyvisa.ResourceManager()
                all_resources = list(rm.list_resources())
                rm.close()
            except Exception as e:
                console.print(f"[red]✗[/red] 扫描 VISA 资源失败: {e}")
                return

            if not all_resources:
                console.print("[red]✗[/red] 未发现任何 VISA 资源")
                return

            # 逐个查询 *IDN?（200ms 超时，超时=不可用，忽略继续）
            devices = []
            rm = pyvisa.ResourceManager()
            for r in all_resources:
                try:
                    inst = rm.open_resource(r)
                    inst.timeout = 200
                    idn_raw = inst.query("*IDN?")
                    idn_info = _parse_idn(idn_raw)
                    devices.append((r, idn_info))
                    console.print(
                        f"  [green]✓[/green] [cyan]{r}[/cyan] → {idn_info.get('manufacturer', '?')} {idn_info.get('model', '?')}"
                    )
                    inst.close()
                except Exception:
                    console.print(f"  [dim]⊘[/dim] [cyan]{r}[/cyan] [dim]（无响应，忽略）[/dim]")
            rm.close()

            if not devices:
                console.print("[red]✗[/red] 所有资源均无 *IDN? 响应")
                return

            # 分类：校准仪 vs 示波器（取首个匹配到的，其余忽略）
            from osccal.core.auto_detect import _identify_brand

            cal_device = None
            osc_device = None

            for r, idn in devices:
                mfr = idn.get("manufacturer", "").upper()
                if cal_device is None and "FLUKE" in mfr:
                    cal_device = (r, idn)
                elif osc_device is None and _identify_brand(idn.get("manufacturer", "")):
                    osc_device = (r, idn)
                else:
                    console.print(
                        f"  [dim]⊘[/dim] [cyan]{r}[/cyan] → {idn.get('manufacturer', '?')} {idn.get('model', '?')} [dim]（忽略）[/dim]"
                    )

            if not cal_device:
                console.print("[red]✗[/red] 未检测到 FLUKE 校准仪")
                return

            if not osc_device:
                console.print("[red]✗[/red] 未检测到可识别的示波器")
                return

            console.print(
                f"\n[green]✓[/green] 校准仪: [cyan]{cal_device[0]}[/cyan] → {cal_device[1].get('manufacturer', '?')} {cal_device[1].get('model', '?')}"
            )
            console.print(
                f"[green]✓[/green] 示波器: [cyan]{osc_device[0]}[/cyan] → {osc_device[1].get('manufacturer', '?')} {osc_device[1].get('model', '?')}"
            )

            # 匹配示波器指令集和特征配置
            cmd_osc, profile_data, cmd_filepath, profile_filepath = detect_configs(
                commands_dir, profiles_dir, osc_device[1]
            )

            if not cmd_osc or not profile_data:
                console.print("[red]✗[/red] 自动匹配配置失败")
                return

            # 校准仪配置
            cmd_calibrator, cal_filepath = _load_calibrator_config(calibrators_dir)
            if not cmd_calibrator:
                console.print("[red]✗[/red] 加载校准仪配置失败")
                return

            # 连接校准仪（先连才能查询探头）
            console.print("\n[bold]连接校准仪...[/bold]")
            inst_calibrator, idn_cal = _connect_calibrator(cal_device[0], [])
            if inst_calibrator is None:
                console.print("[red]✗[/red] 校准仪连接失败")
                return

            # 探头自动识别（如未通过命令行指定）
            if not probe:
                probes = cmd_calibrator.get("probes", {})
                if probes:
                    probe = _auto_detect_probe(inst_calibrator, probes)
                if not probe:
                    probe = _select_probe_interactive(cmd_calibrator)

            # 打印识别结果，等待用户确认
            print_auto_detection_summary(
                osc_device[1],
                cal_device[1],
                cmd_filepath,
                profile_filepath,
                cal_filepath,
                probe,
            )
            if not click.confirm("\n确认执行校准?", default=True):
                console.print("[yellow]已取消[/yellow]")
                return

            # 连接示波器（直接使用检测到的资源；socket 型示波器交互输入 IP）
            console.print("\n[bold]连接示波器...[/bold]")
            inst_osc, idn_osc = _connect_oscilloscope(cmd_osc, osc_device[0], socket_osc, [])
            if inst_osc is None:
                console.print("[red]✗[/red] 示波器连接失败")
                return

        else:
            # ── 手动/交互模式 ──
            cmd_calibrator, _ = _load_calibrator_config(calibrators_dir, calibrator)
            if not cmd_calibrator:
                console.print("[red]✗[/red] 加载校准仪配置失败")
                return

            if not probe:
                probe = _select_probe_interactive(cmd_calibrator)

            cmd_osc = _load_commands_config(commands_dir, osc)
            if not cmd_osc:
                console.print("[red]✗[/red] 加载示波器指令集失败")
                return

            profile_data = _load_profile_config(profiles_dir, profile)
            if not profile_data:
                console.print("[red]✗[/red] 加载示波器特征配置失败")
                return

            channel = _pick_channel(channel)

            console.print("\n[bold]连接设备...[/bold]")
            resources = _list_resources_safely()
            inst_calibrator, idn_cal = _connect_calibrator(resource_cal, resources)
            if inst_calibrator is None:
                console.print("[red]✗[/red] 校准仪连接失败")
                return

            inst_osc, idn_osc = _connect_oscilloscope(cmd_osc, resource_osc, socket_osc, resources)
            if inst_osc is None:
                console.print("[red]✗[/red] 示波器连接失败")
                return

        from osccal.measure.registry import CALIBRATORS_MAP

        while True:
            # 通道选择
            if channel is None:
                channel = _select_channel()
            channel_list = [c.strip() for c in channel.split(",")]

            # 项目选择
            if not items:
                items = _select_items()
            item_list = [i.strip() for i in items.split(",")]

            # 带宽参数（仅首次询问）
            needs_bw = "all" in item_list or "bandwidth" in item_list
            if needs_bw:
                if bandwidth is None:
                    console.print("\n[bold]示波器标称带宽:[/bold]")
                    bandwidth = click.prompt("请输入 (MHz)", type=float, default=100.0)
                if bd_step is None:
                    console.print("\n[bold]带宽扫描步进:[/bold]")
                    bd_step = click.prompt("请输入 (MHz)", type=float, default=5.0)
            else:
                if bandwidth is None:
                    bandwidth = 100.0
                if bd_step is None:
                    bd_step = 5.0

            profile_data["bandwidth"] = int(bandwidth * 1e6)
            profile_data["bd_step"] = int(bd_step * 1e6)

            all_results = {}

            for ch in channel_list:
                if len(channel_list) > 1:
                    console.rule(f"[bold green]通道 CH{ch}[/bold green]")
                    console.print(
                        f"\n[yellow]请将校准仪探头连接到示波器 CH{ch}，确认接线完毕后按回车继续...[/yellow]"
                    )
                    click.prompt("  按回车继续", default="", show_default=False)

                if "all" in item_list:
                    from osccal.measure.all import run_all

                    ch_results = run_all(
                        inst_osc, inst_calibrator, cmd_osc, cmd_calibrator, profile_data, ch, probe
                    )
                    for key, val in ch_results.items():
                        result_key = f"{key}_ch{ch}" if len(channel_list) > 1 else key
                        all_results[result_key] = val
                else:
                    for item in item_list:
                        CalClass = CALIBRATORS_MAP.get(item)
                        if not CalClass:
                            console.print(f"[yellow]⚠[/yellow] 未知校准项目: {item}")
                            continue
                        try:
                            console.rule(f"[bold blue]{item}[/bold blue]")
                            cal = CalClass(
                                inst_osc,
                                inst_calibrator,
                                cmd_osc,
                                cmd_calibrator,
                                profile_data,
                                ch,
                                probe,
                            )
                            cal.run()
                            result_key = f"{item}_ch{ch}" if len(channel_list) > 1 else item
                            all_results[result_key] = cal.get_results()
                        except Exception as e:
                            console.print(f"[red]✗[/red] {item} 校准失败: {e}")
                            result_key = f"{item}_ch{ch}" if len(channel_list) > 1 else item
                            all_results[result_key] = []

            metadata = {
                "channel": ",".join(channel_list),
                "probe": probe or "",
                "oscilloscope": idn_osc if isinstance(idn_osc, dict) else {},
                "calibrator": idn_cal if isinstance(idn_cal, dict) else {},
                "commands_file": cmd_osc.get("name", ""),
                "profile_file": profile_data.get("series", ""),
                "calibrator_file": cmd_calibrator.get("name", ""),
                "simulated": False,
                "limits": profile_data.get("calibration_limits", {}),
                "scpi_errors": scpi_trace.failure_count(),
            }

            save_calibration_data(all_results, metadata)

            console.print("\n[bold green]✓ 校准完成！[/bold green]")

            if not click.confirm("\n是否继续校准？", default=False):
                break
            # 重置参数，下一轮重新选择
            channel = None
            items = None
    finally:
        close_all_connections()
        if scpi_trace.failure_count() > 0:
            console.print(
                f"[red]⚠[/red] 本次校准存在 {scpi_trace.failure_count()} 次 SCPI "
                f"通信/组装失败，结果可能不可靠，请检查连接与配置"
            )
        if log_scpi:
            _print_scpi_log()


@cli.command()
@click.option("--latest", is_flag=True, help="显示最近一次校准数据")
@click.option("--file", "filepath", type=click.Path(exists=True), help="指定校准数据文件")
def show(latest, filepath):
    """显示校准数据"""
    from osccal.core.storage import (
        DATA_DIR,
        get_latest_calibration_file,
        list_calibration_files,
        load_calibration_data,
    )

    if filepath:
        data = load_calibration_data(filepath)
    elif latest:
        latest_file = get_latest_calibration_file()
        if not latest_file:
            console.print("[yellow]⚠[/yellow] 未找到校准数据文件")
            return
        data = load_calibration_data(latest_file)
    else:
        files = list_calibration_files()
        if not files:
            console.print("[yellow]⚠[/yellow] 未找到校准数据文件")
            return
        for i, f in enumerate(files):
            console.print(f"  [{i}] {f}")
        choice = click.prompt("选择文件序号", type=int, default=0)
        if 0 <= choice < len(files):
            data = load_calibration_data(os.path.join(DATA_DIR, files[choice]))
        else:
            console.print("[red]✗[/red] 无效选择")
            return

    if not data:
        return

    _display_calibration_data(data)


@cli.command()
@click.option("--format", "fmt", type=click.Choice(["excel"]), default="excel", help="导出格式")
@click.option("--file", "filepath", type=click.Path(exists=True), help="校准数据文件路径")
@click.option("--output", type=click.Path(), help="输出文件路径")
def export(fmt, filepath, output):
    """导出校准报告"""
    from osccal.core.storage import (
        get_latest_calibration_file,
        load_calibration_data,
    )

    if not filepath:
        latest_file = get_latest_calibration_file()
        if not latest_file:
            console.print("[yellow]⚠[/yellow] 未找到校准数据文件")
            return
        filepath = latest_file

    data = load_calibration_data(filepath)
    if not data:
        console.print("[red]✗[/red] 加载校准数据失败")
        return

    if not output:
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        output = os.path.join(os.path.dirname(filepath), f"{base_name}.xlsx")

    if fmt == "excel":
        from osccal.core.export import export_to_excel

        export_to_excel(data, output)


@cli.group()
def device():
    """设备管理命令"""
    pass


@device.command("list")
def device_list():
    """列出可用的 VISA 设备资源"""
    from osccal.core.connect import list_visa_resources

    try:
        resources = list_visa_resources()
        if resources:
            table = Table(title="可用 VISA 资源", show_lines=True)
            table.add_column("序号", justify="center", style="cyan")
            table.add_column("资源地址", style="white")
            for i, r in enumerate(resources):
                table.add_row(str(i), r)
            console.print(table)
        else:
            console.print("[yellow]⚠[/yellow] 未发现 VISA 资源")
    except Exception as e:
        console.print(f"[red]✗[/red] 扫描 VISA 资源失败: {e}")


@device.command("info")
@click.option("--resource", type=click.STRING, help="VISA 资源地址")
@click.option("--socket", type=click.STRING, help="Socket 地址 (host:port)")
def device_info(resource, socket):
    """查询设备信息 (*IDN?)"""
    from osccal.core.connect import (
        close_all_connections,
        connect_socket,
        connect_visa,
        list_visa_resources,
    )

    try:
        if socket:
            host, port = socket.split(":")
            inst, idn_info = connect_socket(host, int(port))
        elif resource:
            inst, idn_info = connect_visa(resource)
        else:
            resources = list_visa_resources()
            if resources:
                console.print("[bold]选择设备:[/bold]")
                for i, r in enumerate(resources):
                    console.print(f"  [{i}] {r}")
                choice = click.prompt("请选择", type=int, default=0)
                inst, idn_info = connect_visa(resources[choice])
            else:
                console.print("[yellow]⚠[/yellow] 未发现 VISA 资源")
                return

        if inst is not None and isinstance(idn_info, dict):
            table = Table(title="设备信息", show_lines=True)
            table.add_column("项目", style="cyan")
            table.add_column("内容", style="white")
            for key, value in idn_info.items():
                table.add_row(key, str(value))
            console.print(table)
    finally:
        close_all_connections()


def _display_calibration_data(data: dict):
    metadata = data.get("metadata", {})
    results = data.get("results", {})

    console.print()
    info_table = Table(title="校准信息", show_lines=True)
    info_table.add_column("项目", style="cyan")
    info_table.add_column("内容", style="white")

    info_table.add_row("校准时间", metadata.get("timestamp", ""))
    info_table.add_row("通道", f"CH{metadata.get('channel', '')}")
    info_table.add_row("探头", metadata.get("probe", ""))

    osc = metadata.get("oscilloscope", {})
    info_table.add_row("示波器", f"{osc.get('manufacturer', '')} {osc.get('model', '')}")
    info_table.add_row("示波器序列号", osc.get("serial", ""))

    cal = metadata.get("calibrator", {})
    info_table.add_row("校准仪", f"{cal.get('manufacturer', '')} {cal.get('model', '')}")

    console.print(info_table)

    from osccal.core.table_configs import ITEM_CONFIGS

    limits_map = metadata.get("limits", {}) or {}

    # 按校准项目分组：同一项目的所有通道数据合并到同一个表格
    grouped: dict[str, list] = {}
    for item_name, rows in results.items():
        if not rows:
            continue
        base_name = item_name.split("_ch")[0]
        grouped.setdefault(base_name, []).extend(rows)

    for base_name, rows in grouped.items():
        config = ITEM_CONFIGS.get(base_name, {"title": base_name, "columns": [], "error_col": None})
        item_limits = limits_map.get(base_name, {}) or {}
        lower = item_limits.get("lower", -2.0)
        upper = item_limits.get("upper", 2.0)
        min_mhz = item_limits.get("min_mhz")

        table = Table(title=config["title"], show_lines=True)

        for col in config["columns"]:
            table.add_column(col, justify="right")

        for row in rows:
            values = list(row.values()) if isinstance(row, dict) else row

            str_values = [str(v) for v in values]

            error_col = config.get("error_col")
            if error_col is not None and error_col < len(str_values):
                try:
                    error_val = float(str_values[error_col])
                    if error_val < lower or error_val > upper:
                        str_values[error_col] = f"[red bold]{str_values[error_col]}[/red bold]"
                except (ValueError, IndexError):
                    pass

            min_col = config.get("min_col")
            if min_col is not None and min_col < len(str_values) and min_mhz is not None:
                try:
                    if float(str_values[min_col]) < min_mhz:
                        str_values[min_col] = f"[red bold]{str_values[min_col]}[/red bold]"
                except (ValueError, IndexError):
                    pass

            table.add_row(*str_values)

        console.print()
        console.print(table)


if __name__ == "__main__":
    cli()
