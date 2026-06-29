import os
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


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
@click.option("--items", type=click.STRING, default=None, help="校准项目，逗号分隔 (amp,dc_gain,delta_time,bandwidth,transient,all)")
@click.option("--resource-osc", type=click.STRING, help="示波器 VISA 资源地址")
@click.option("--resource-cal", type=click.STRING, help="校准仪 VISA 资源地址")
@click.option("--socket-osc", type=click.STRING, help="示波器 Socket 地址 (host:port)")
@click.option("--bandwidth", type=click.FLOAT, default=None, help="示波器标称带宽 (MHz)")
@click.option("--bd-step", type=click.FLOAT, default=None, help="带宽扫描步进 (MHz)")
def calibrate(osc, profile, calibrator, channel, probe, items, resource_osc, resource_cal, socket_osc, bandwidth, bd_step):
    """执行示波器校准流程"""
    from osccal.core.config import load_commands, load_profile, load_calibrator, list_config_files
    from osccal.core.connect import connect_visa, connect_socket, list_visa_resources
    from osccal.core.storage import save_calibration_data

    console.print(Panel("[bold blue]OscCal-CLI[/bold blue] - 示波器自动校准系统", expand=False))

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_dir = base_dir

    commands_dir = os.path.join(project_dir, "commands")
    profiles_dir = os.path.join(project_dir, "profiles")
    calibrators_dir = os.path.join(project_dir, "calibrators")

    if calibrator:
        cmd_calibrator = load_calibrator(calibrator)
    else:
        cal_files = list_config_files(calibrators_dir)
        if not cal_files:
            console.print("[red]✗[/red] 未找到校准仪配置文件")
            return
        console.print("\n[bold]选择校准仪配置:[/bold]")
        for i, f in enumerate(cal_files):
            console.print(f"  [{i}] {f}")
        choice = click.prompt("请选择", type=int, default=0)
        cmd_calibrator = load_calibrator(os.path.join(calibrators_dir, cal_files[choice]))

    if not cmd_calibrator:
        console.print("[red]✗[/red] 加载校准仪配置失败")
        return

    if not probe:
        probes = cmd_calibrator.get("probes", {})
        if probes:
            probe_keys = list(probes.keys())
            imp_rules = cmd_calibrator.get("impedance_rules", {})
            console.print("\n[bold]选择校准仪探头:[/bold]")
            for i, pk in enumerate(probe_keys):
                p_info = probes[pk]
                supported_shapes = list(imp_rules.get(pk, {}).keys())
                desc = f"{pk} (支持模式: {', '.join(supported_shapes)})"
                console.print(f"  [{i}] {desc}")
            choice = click.prompt("请选择", type=int, default=0)
            probe = probe_keys[choice]
        else:
            probe = None

    if osc:
        cmd_osc = load_commands(osc)
    else:
        osc_files = list_config_files(commands_dir)
        if not osc_files:
            console.print("[red]✗[/red] 未找到示波器指令集文件")
            return
        console.print("\n[bold]选择示波器指令集:[/bold]")
        for i, f in enumerate(osc_files):
            console.print(f"  [{i}] {f}")
        choice = click.prompt("请选择", type=int, default=0)
        cmd_osc = load_commands(os.path.join(commands_dir, osc_files[choice]))

    if not cmd_osc:
        console.print("[red]✗[/red] 加载示波器指令集失败")
        return

    if profile:
        profile_data = load_profile(profile)
    else:
        profile_files = list_config_files(profiles_dir)
        if not profile_files:
            console.print("[red]✗[/red] 未找到示波器特征文件")
            return
        console.print("\n[bold]选择示波器特征配置:[/bold]")
        for i, f in enumerate(profile_files):
            console.print(f"  [{i}] {f}")
        choice = click.prompt("请选择", type=int, default=0)
        profile_data = load_profile(os.path.join(profiles_dir, profile_files[choice]))

    if not profile_data:
        console.print("[red]✗[/red] 加载示波器特征配置失败")
        return

    if not channel:
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
        channel_presets = {
            "0": "1",
            "1": "2",
            "2": "3",
            "3": "4",
            "4": "1,2",
            "5": "1,2,3",
            "6": "1,2,3,4",
        }
        channel = channel_presets.get(ch_input, ch_input)

    channel_list = [c.strip() for c in channel.split(",")]

    console.print("\n[bold]连接设备...[/bold]")

    try:
        resources = list_visa_resources()
        if resources:
            console.print("[bold]可用 VISA 资源:[/bold]")
            for i, r in enumerate(resources):
                console.print(f"  [{i}] {r}")
        else:
            console.print("[yellow]⚠[/yellow] 未发现 VISA 资源")
    except Exception:
        console.print("[yellow]⚠[/yellow] VISA 资源扫描失败（可能未安装 VISA 驱动）")
        resources = []

    if resource_cal:
        inst_calibrator, idn_cal = connect_visa(resource_cal)
    elif resources:
        console.print("\n[bold]选择校准仪资源:[/bold]")
        for i, r in enumerate(resources):
            console.print(f"  [{i}] {r}")
        choice = click.prompt("请选择", type=int, default=0)
        inst_calibrator, idn_cal = connect_visa(resources[choice])
    else:
        console.print("[red]✗[/red] 无可用资源连接校准仪")
        return

    if inst_calibrator is None:
        console.print("[red]✗[/red] 校准仪连接失败")
        return

    comm_type = cmd_osc.get("type", "pyvisa")

    if socket_osc:
        host, port = socket_osc.split(":")
        inst_osc, idn_osc = connect_socket(host, int(port))
    elif resource_osc:
        inst_osc, idn_osc = connect_visa(resource_osc)
    elif resources:
        console.print("\n[bold]选择示波器资源:[/bold]")
        for i, r in enumerate(resources):
            console.print(f"  [{i}] {r}")
        choice = click.prompt("请选择", type=int, default=0)
        if comm_type == "socket":
            host = click.prompt("输入示波器 IP 地址")
            port = click.prompt("输入示波器端口", type=int, default=5025)
            inst_osc, idn_osc = connect_socket(host, port)
        else:
            inst_osc, idn_osc = connect_visa(resources[choice])
    else:
        console.print("[red]✗[/red] 无可用资源连接示波器")
        return

    if inst_osc is None:
        console.print("[red]✗[/red] 示波器连接失败")
        return

    if not items:
        console.print("\n[bold]选择校准项目:[/bold]")
        console.print("  [0] 全部项目")
        console.print("  [1] 幅度(ΔV)")
        console.print("  [2] 直流增益")
        console.print("  [3] Δt(时间)")
        console.print("  [4] 频带宽度")
        console.print("  [5] 上升时间及过冲")
        console.print("  也可输入序号多选(逗号分隔)，如: 1,3")
        choice = click.prompt("请选择或输入", default="0")
        item_presets = {
            "0": "all",
            "1": "amp",
            "2": "dc_gain",
            "3": "delta_time",
            "4": "bandwidth",
            "5": "transient",
        }
        if "," in choice:
            items = ",".join(item_presets.get(c.strip(), c.strip()) for c in choice.split(","))
        else:
            items = item_presets.get(choice, choice)

    item_list = [i.strip() for i in items.split(",")]

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

    profile_data["bandwidth"] = int(bandwidth * 1E6)
    profile_data["bd_step"] = int(bd_step * 1E6)

    from osccal.measure.registry import CALIBRATORS_MAP

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
            ch_results = run_all(inst_osc, inst_calibrator, cmd_osc, cmd_calibrator, profile_data, ch, probe)
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
                    cal = CalClass(inst_osc, inst_calibrator, cmd_osc, cmd_calibrator, profile_data, ch, probe)
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
    }

    save_calibration_data(all_results, metadata)

    console.print("\n[bold green]✓ 校准完成！[/bold green]")


@cli.command()
@click.option("--latest", is_flag=True, help="显示最近一次校准数据")
@click.option("--file", "filepath", type=click.Path(exists=True), help="指定校准数据文件")
def show(latest, filepath):
    """显示校准数据"""
    from osccal.core.storage import load_calibration_data, get_latest_calibration_file, list_calibration_files, DATA_DIR

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
    from osccal.core.storage import load_calibration_data, get_latest_calibration_file, list_calibration_files, DATA_DIR

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
    from osccal.core.connect import connect_visa, connect_socket, list_visa_resources

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


def _display_calibration_data(data: dict):
    metadata = data.get("metadata", {})
    results = data.get("results", {})

    console.print()
    info_table = Table(title="校准信息", show_lines=True)
    info_table.add_column("项目", style="cyan")
    info_table.add_column("内容", style="white")

    info_table.add_row("校准时间", metadata.get("timestamp", ""))
    info_table.add_row("通道", f"CH{metadata.get('channel', '')}")

    osc = metadata.get("oscilloscope", {})
    info_table.add_row("示波器", f"{osc.get('manufacturer', '')} {osc.get('model', '')}")
    info_table.add_row("示波器序列号", osc.get("serial", ""))

    cal = metadata.get("calibrator", {})
    info_table.add_row("校准仪", f"{cal.get('manufacturer', '')} {cal.get('model', '')}")

    console.print(info_table)

    from osccal.core.table_configs import ITEM_CONFIGS

    for item_name, rows in results.items():
        if not rows:
            continue

        config = ITEM_CONFIGS.get(item_name, {"title": item_name, "columns": [], "error_col": None})
        table = Table(title=config["title"], show_lines=True)

        for col in config["columns"]:
            table.add_column(col, justify="right")

        for row in rows:
            if isinstance(row, dict):
                values = list(row.values())
            else:
                values = row

            str_values = [str(v) for v in values]

            error_col = config.get("error_col")
            if error_col is not None and error_col < len(str_values):
                try:
                    error_val = float(str_values[error_col])
                    if abs(error_val) > 2.0:
                        str_values[error_col] = f"[red bold]{str_values[error_col]}[/red bold]"
                except (ValueError, IndexError):
                    pass

            table.add_row(*str_values)

        console.print()
        console.print(table)


if __name__ == "__main__":
    cli()
