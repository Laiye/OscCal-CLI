import os
from datetime import datetime
from functools import partial

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from osccal import __version__
from osccal.core.config import (
    list_config_files,
    load_calibrator,
    load_characteristics,
    load_commands,
    load_scheme,
    load_spec,
    resolve_config_path,
)
from osccal.core.connect import (
    close_all_connections,
    connect_socket,
    connect_visa,
    list_visa_resources,
)

console = Console()


class CalibrationCommand(click.Command):
    """区分执行失败、参数错误与用户中断的退出状态。"""

    def invoke(self, ctx):
        from osccal.core.comm import ScpiError
        from osccal.measure.base import OutputShutdownError

        try:
            return super().invoke(ctx)
        except (KeyboardInterrupt, click.Abort) as exc:
            console.print("[yellow]校准已取消或中断[/yellow]")
            raise click.exceptions.Exit(130) from exc
        except (OSError, ScpiError, OutputShutdownError) as exc:
            raise click.ClickException(str(exc)) from exc


def _select_index(count: int) -> int:
    """限制列表序号范围，非法输入由 Click 重新询问。"""
    if count <= 0:
        raise click.UsageError("没有可选项")
    return click.prompt("请选择", type=click.IntRange(0, count - 1), default=0)


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
    choice = _select_index(len(probe_keys))
    return probe_keys[choice]


def _select_channel(max_channels: int = 4) -> str:
    """交互式选择校准通道。"""
    console.print("\n[bold]选择校准通道:[/bold]")
    options = [str(i) for i in range(1, max_channels + 1)]
    options.extend(",".join(str(ch) for ch in range(1, i + 1)) for i in range(2, max_channels + 1))
    presets = {str(i): value for i, value in enumerate(options)}
    for key, value in presets.items():
        console.print(f"  [{key}] " + " + ".join(f"CH{ch}" for ch in value.split(",")))
    console.print("  也可直接输入通道号，如: 1,2,3")
    ch_input = click.prompt("请选择或输入", default="0")
    return presets.get(ch_input, ch_input)


def _pick_channel(channel_arg: str | None, max_channels: int = 4) -> str:
    """返回通道参数；未通过命令行指定时交互选择。"""
    if channel_arg is not None:
        return channel_arg
    return _select_channel(max_channels)


def _select_items(available: list[str]) -> str:
    """交互式选择校准项目：只列方案实际列入的项目，顺序来自 registry。"""
    from osccal.measure.registry import CALIBRATION_ITEMS

    console.print("\n[bold]选择校准项目:[/bold]")
    console.print("  [0] 全部项目")
    presets = {"0": "all"}
    selected = [item for item in CALIBRATION_ITEMS if item["name"] in available]
    for index, item in enumerate(selected, start=1):
        console.print(f"  [{index}] {item['title']}（{item['clause']}）")
        presets[str(index)] = item["name"]
    console.print("  也可输入序号多选(逗号分隔)，如: 1,3")
    choice = click.prompt("请选择或输入", default="0")
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
    """加载示波器指令集：指定路径或交互选择。返回 (配置, 文件路径)。"""
    if path:
        return load_commands(path), path
    files = list_config_files(commands_dir)
    if not files:
        console.print("[red]✗[/red] 未找到示波器指令集文件")
        return {}, ""
    console.print("\n[bold]选择示波器指令集:[/bold]")
    for i, f in enumerate(files):
        console.print(f"  [{i}] {f}")
    choice = _select_index(len(files))
    fpath = os.path.join(commands_dir, files[choice])
    return load_commands(fpath), fpath


def _load_characteristics_config(characteristics_dir: str, path: str | None = None):
    """加载仪器特征配置：指定路径或交互选择。返回 (配置, 文件路径)。"""
    if path:
        return load_characteristics(path), path
    files = list_config_files(characteristics_dir)
    if not files:
        console.print("[red]✗[/red] 未找到仪器特征文件")
        return {}, ""
    console.print("\n[bold]选择仪器特征配置:[/bold]")
    for i, f in enumerate(files):
        console.print(f"  [{i}] {f}")
    choice = _select_index(len(files))
    fpath = os.path.join(characteristics_dir, files[choice])
    return load_characteristics(fpath), fpath


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
    choice = _select_index(len(resources))
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


def _parse_socket_addr(addr: str) -> tuple[str, int] | None:
    """解析 host:port，非法时打印错误并返回 None。"""
    host, sep, port_str = addr.rpartition(":")
    if not sep or not host or not port_str.isdigit():
        console.print(f"[red]✗[/red] Socket 地址格式无效: {addr}（应为 host:port）")
        return None
    port = int(port_str)
    if not 1 <= port <= 65535:
        console.print(f"[red]✗[/red] Socket 端口超出范围: {port}")
        return None
    return host, port


def _connect_oscilloscope(cmd_osc, resource_osc, socket_osc, resources, interactive: bool = True):
    """连接示波器：按指令集类型（socket/visa）与命令行参数解析连接方式。"""
    comm_type = cmd_osc.get("type", "pyvisa")
    if comm_type == "socket":
        if socket_osc:
            parsed = _parse_socket_addr(socket_osc)
            return connect_socket(*parsed) if parsed else (None, {})
        if interactive:
            console.print("\n[bold]Socket 连接示波器:[/bold]")
            host = click.prompt("请输入示波器 IP 地址", type=str)
            port = click.prompt("请输入示波器端口", type=click.IntRange(1, 65535), default=5025)
            return connect_socket(host, port)
        return None, {}
    if socket_osc:
        parsed = _parse_socket_addr(socket_osc)
        inst, info = connect_socket(*parsed) if parsed else (None, {})
        if inst is not None:
            cmd_osc["type"] = "socket"
        return inst, info
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
@click.version_option(version=__version__, prog_name="osccal")
def cli():
    """OscCal-CLI - 示波器自动校准系统"""
    pass


@cli.command(cls=CalibrationCommand)
@click.option("--osc", type=click.Path(exists=True), help="示波器指令集配置文件路径")
@click.option(
    "--characteristics",
    type=click.STRING,
    default=None,
    help="仪器特征：characteristics/ 下的名称（可省 .json）或文件路径",
)
@click.option(
    "--scheme",
    type=click.STRING,
    default="jjf1057_2026_single",
    show_default=True,
    help="校准方案：schemes/ 下的名称（可省 .json）或文件路径",
)
@click.option("--calibrator", type=click.Path(exists=True), help="校准仪配置文件路径")
@click.option("--channel", type=click.STRING, default=None, help="校准通道，逗号分隔（如 1,2）")
@click.option("--probe", type=click.STRING, default=None, help="校准仪探头型号 (9560/9550/9530)")
@click.option(
    "--items",
    type=click.STRING,
    default=None,
    help="校准项目，逗号分隔（项目集见 osccal.measure.registry，旧项目名已删除）",
)
@click.option("--resource-osc", type=click.STRING, help="示波器 VISA 资源地址")
@click.option("--resource-cal", type=click.STRING, help="校准仪 VISA 资源地址")
@click.option("--socket-osc", type=click.STRING, help="示波器 Socket 地址 (host:port)")
@click.option("--auto", is_flag=True, help="自动扫描 VISA 资源，根据 *IDN? 识别设备并匹配配置")
@click.option("--log-scpi", is_flag=True, help="打印完整 SCPI 指令日志与失败统计")
def calibrate(
    osc,
    characteristics,
    scheme,
    calibrator,
    channel,
    probe,
    items,
    resource_osc,
    resource_cal,
    socket_osc,
    auto,
    log_scpi,
):
    """执行示波器校准流程"""
    from osccal.core import scpi_trace
    from osccal.core.config_validation import validate_device_identity
    from osccal.core.storage import (
        CalibrationRecording,
        configuration_snapshot,
        scheme_record,
        spec_record,
    )

    scpi_trace.reset()
    scpi_trace.set_log_enabled(log_scpi)

    console.print(Panel("[bold blue]OscCal-CLI[/bold blue] - 示波器自动校准系统", expand=False))

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_dir = base_dir
    commands_dir = os.path.join(project_dir, "commands")
    characteristics_dir = os.path.join(project_dir, "characteristics")
    calibrators_dir = os.path.join(project_dir, "calibrators")
    specs_dir = os.path.join(project_dir, "specs")
    schemes_dir = os.path.join(project_dir, "schemes")

    scheme_filepath = resolve_config_path(schemes_dir, scheme)
    if scheme_filepath is None:
        raise click.BadParameter(f"找不到方案配置文件: {scheme}", param_hint="--scheme")
    scheme_data = load_scheme(scheme_filepath)
    if not scheme_data:
        raise click.UsageError("校准方案配置校验失败，已中止")
    spec_name = scheme_data.get("spec", "")
    spec_filepath = resolve_config_path(specs_dir, spec_name)
    if spec_filepath is None:
        raise click.UsageError(f"校准方案 {scheme} 引用的规范不存在: {spec_name}")
    spec_data = load_spec(spec_filepath)
    if not spec_data:
        raise click.UsageError("校准规范配置校验失败，已中止")
    console.print(
        Panel(
            f"[bold]{spec_data.get('spec_code', '')}[/bold]"
            f"　实施: {spec_data.get('effective', '未注明')}"
            f"　复校间隔: {spec_data.get('recall_interval_months', '未注明')} 个月"
            f"　偏离声明: {len(spec_data.get('deviations', []))} 条\n"
            f"方案: [bold]{scheme_data.get('name', '')}[/bold]"
            f"　项目: {len(scheme_data.get('items', {}))}",
            title="校准规范与方案",
            expand=False,
        )
    )

    session_failed = False

    try:
        if socket_osc is not None and _parse_socket_addr(socket_osc) is None:
            raise click.BadParameter("应为有效的 host:port 地址", param_hint="--socket-osc")
        if auto:
            # ── 自动模式：扫描 VISA、识别设备、匹配配置 ──
            from osccal.core.auto_detect import detect_configs, print_auto_detection_summary
            from osccal.core.connect import _parse_idn

            console.print("\n[bold]自动扫描 VISA 资源...[/bold]")
            try:
                import pyvisa
            except ImportError:
                raise click.ClickException("✗ pyvisa 未安装，请运行: pip install pyvisa") from None

            try:
                rm = pyvisa.ResourceManager()
                all_resources = list(rm.list_resources())
                rm.close()
            except Exception as e:
                raise click.ClickException(f"✗ 扫描 VISA 资源失败: {e}") from e

            if not all_resources:
                raise click.ClickException("✗ 未发现任何 VISA 资源")

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
                raise click.ClickException("✗ 所有资源均无 *IDN? 响应")

            # 多台同类设备必须明确选择，避免由资源枚举顺序决定被校设备。
            from osccal.core.auto_detect import _identify_brand

            cal_candidates = [
                (r, idn)
                for r, idn in devices
                if "FLUKE" in idn.get("manufacturer", "").upper()
                and (not resource_cal or r == resource_cal)
            ]
            osc_candidates = [
                (r, idn)
                for r, idn in devices
                if _identify_brand(idn.get("manufacturer", ""))
                and (not resource_osc or r == resource_osc)
            ]
            if len(cal_candidates) > 1 or len(osc_candidates) > 1:
                raise click.UsageError(
                    "检测到多台同类设备，请用 --resource-cal / --resource-osc 指定资源"
                )
            cal_device = cal_candidates[0] if cal_candidates else None
            osc_device = osc_candidates[0] if osc_candidates else None

            if not cal_device:
                raise click.ClickException("✗ 未检测到 FLUKE 校准仪")

            if not osc_device:
                raise click.ClickException("✗ 未检测到可识别的示波器")

            console.print(
                f"\n[green]✓[/green] 校准仪: [cyan]{cal_device[0]}[/cyan] → {cal_device[1].get('manufacturer', '?')} {cal_device[1].get('model', '?')}"
            )
            console.print(
                f"[green]✓[/green] 示波器: [cyan]{osc_device[0]}[/cyan] → {osc_device[1].get('manufacturer', '?')} {osc_device[1].get('model', '?')}"
            )

            # 匹配示波器指令集和仪器特征
            cmd_osc, characteristics_data, cmd_filepath, characteristics_filepath = detect_configs(
                commands_dir, characteristics_dir, osc_device[1]
            )

            if not cmd_osc or not characteristics_data:
                raise click.UsageError("✗ 自动匹配配置失败")

            # 校准仪配置（--calibrator 优先，否则自动加载首个）
            cmd_calibrator, cal_filepath = _load_calibrator_config(calibrators_dir, calibrator)
            if not cmd_calibrator:
                raise click.UsageError("✗ 加载校准仪配置失败")

            # 连接校准仪（先连才能查询探头）
            console.print("\n[bold]连接校准仪...[/bold]")
            inst_calibrator, idn_cal = _connect_calibrator(cal_device[0], [])
            if inst_calibrator is None:
                raise click.ClickException("✗ 校准仪连接失败")

            # 探头自动识别（如未通过命令行指定）
            if probe is None:
                probes = cmd_calibrator.get("probes", {})
                if probes:
                    probe = _auto_detect_probe(inst_calibrator, probes)
                if probe is None:
                    probe = _select_probe_interactive(cmd_calibrator)

            # 打印识别结果，等待用户确认
            print_auto_detection_summary(
                osc_device[1],
                cal_device[1],
                cmd_filepath,
                characteristics_filepath,
                cal_filepath,
                probe,
            )
            if not click.confirm("\n确认执行校准?", default=True):
                raise click.Abort()

            # 连接示波器（直接使用检测到的资源；socket 型示波器交互输入 IP）
            console.print("\n[bold]连接示波器...[/bold]")
            inst_osc, idn_osc = _connect_oscilloscope(cmd_osc, osc_device[0], socket_osc, [])
            if inst_osc is None:
                raise click.ClickException("✗ 示波器连接失败")

        else:
            # ── 手动/交互模式 ──
            cmd_calibrator, cal_filepath = _load_calibrator_config(calibrators_dir, calibrator)
            if not cmd_calibrator:
                raise click.UsageError("✗ 加载校准仪配置失败")

            if probe is None:
                probe = _select_probe_interactive(cmd_calibrator)

            cmd_osc, cmd_filepath = _load_commands_config(commands_dir, osc)
            if not cmd_osc:
                raise click.UsageError("✗ 加载示波器指令集失败")

            characteristics_path = None
            if characteristics:
                characteristics_path = resolve_config_path(characteristics_dir, characteristics)
                if characteristics_path is None:
                    raise click.BadParameter(
                        f"找不到特征文件: {characteristics}", param_hint="--characteristics"
                    )
            characteristics_data, characteristics_filepath = _load_characteristics_config(
                characteristics_dir, characteristics_path
            )
            if not characteristics_data:
                raise click.UsageError("✗ 加载仪器特征配置失败")

            channel = _pick_channel(channel, characteristics_data.get("channels", 4))

            console.print("\n[bold]连接设备...[/bold]")
            resources = _list_resources_safely()
            inst_calibrator, idn_cal = _connect_calibrator(resource_cal, resources)
            if inst_calibrator is None:
                raise click.ClickException("✗ 校准仪连接失败")

            inst_osc, idn_osc = _connect_oscilloscope(cmd_osc, resource_osc, socket_osc, resources)
            if inst_osc is None:
                raise click.ClickException("✗ 示波器连接失败")

        from osccal.core.points import build_plan
        from osccal.measure.all import run_items
        from osccal.measure.registry import ITEM_ORDER, RUNNERS

        round_start_errors = 0
        while True:
            # 通道选择
            if channel is None:
                channel = _select_channel(characteristics_data.get("channels", 2))
            channel_list = [c.strip() for c in channel.split(",") if c.strip()]

            errors = validate_device_identity(cmd_osc, idn_osc, "示波器指令集")
            errors.extend(validate_device_identity(characteristics_data, idn_osc, "示波器特征"))
            errors.extend(validate_device_identity(cmd_calibrator, idn_cal, "校准仪"))
            if inst_osc is inst_calibrator or (
                resource_cal and resource_osc and resource_cal.upper() == resource_osc.upper()
            ):
                errors.append("示波器和校准仪不能使用同一设备资源")
            if errors:
                raise click.UsageError("执行前检查失败：\n" + "\n".join(errors))

            # 按方案解析本轮实际要跑的点（每个通道一份），并提示被跳过的点。
            plans_by_channel: dict[str, dict[str, dict]] = {}
            skipped_notes: list[dict] = []
            planned_items: set[str] = set()
            for ch in channel_list:
                plan = build_plan(
                    spec_data, scheme_data, characteristics_data, cmd_calibrator, probe, [ch]
                )
                planned = {
                    item["name"]: item for item in plan["items"] if item["status"] == "planned"
                }
                plans_by_channel[ch] = planned
                planned_items.update(planned)
            if not planned_items:
                raise click.UsageError("校准方案未解析出任何校准项目，请检查 --scheme")
            available_items = [name for name in ITEM_ORDER if name in planned_items]

            # 项目选择
            if items is None:
                items = _select_items(available_items)
            requested = [i.strip() for i in items.split(",") if i.strip()]
            requested_all = "all" in requested
            item_list = available_items if requested_all else requested
            if not item_list:
                available = "、".join(sorted(available_items)) or "无"
                raise click.UsageError(f"没有可执行的项目（当前方案: {available}）")

            unimplemented = [name for name in item_list if name not in RUNNERS]
            if unimplemented:
                available = "、".join(sorted(RUNNERS)) or "无"
                raise click.UsageError(
                    "以下项目尚未实现: " + "、".join(unimplemented) + f"\n当前已实现: {available}"
                )

            missing_items = [name for name in item_list if name not in planned_items]
            if missing_items:
                raise click.UsageError("以下项目不在所选方案中: " + "、".join(missing_items))

            seen_skips: set[tuple[str, str]] = set()
            for planned in plans_by_channel.values():
                for name in item_list:
                    item = planned[name]
                    for skip in item["skipped"]:
                        key = (item["title"], str(skip.get("reason", "")))
                        if key in seen_skips:
                            continue
                        seen_skips.add(key)
                        skipped_notes.append({"item": item["title"], "reason": key[1]})
            for note in skipped_notes:
                console.print(f"[yellow]·[/yellow] {note['item']} 跳过：{note['reason']}")

            metadata = {
                "timestamp": datetime.now().isoformat(),
                "channel": ",".join(channel_list),
                "probe": probe or "",
                "oscilloscope": idn_osc if isinstance(idn_osc, dict) else {},
                "calibrator": idn_cal if isinstance(idn_cal, dict) else {},
                "commands_file": os.path.basename(cmd_filepath) if cmd_filepath else "",
                "characteristics_file": (
                    os.path.basename(characteristics_filepath) if characteristics_filepath else ""
                ),
                "calibrator_file": os.path.basename(cal_filepath) if cal_filepath else "",
                "limits": spec_data.get("reference_limits", {}),
                "spec": spec_record(spec_data, spec_filepath),
                "scheme": scheme_record(scheme_data, scheme_filepath),
                "bandwidth_hz": characteristics_data.get("bandwidth_hz", 0),
                "points_plan": {
                    ch: {
                        name: len(planned[name]["points"]) for name in item_list if name in planned
                    }
                    for ch, planned in plans_by_channel.items()
                },
                "skipped_points": skipped_notes,
                "status": "in_progress",
                "requested_items": item_list,
                "item_status": {},
                "failures": {},
                "configurations": {
                    "commands": configuration_snapshot(cmd_osc),
                    "characteristics": configuration_snapshot(characteristics_data),
                    "calibrator": configuration_snapshot(cmd_calibrator),
                    "scheme": configuration_snapshot(scheme_data),
                },
            }
            recording = CalibrationRecording(metadata, round_start_errors)

            try:
                recording.checkpoint()
                for ch in channel_list:
                    record_result = partial(
                        recording.record_result, channel=ch, multichannel=len(channel_list) > 1
                    )
                    if len(channel_list) > 1:
                        console.rule(f"[bold green]通道 CH{ch}[/bold green]")
                        console.print(
                            f"\n[yellow]请将校准仪探头连接到示波器 CH{ch}，确认接线完毕后按回车继续...[/yellow]"
                        )
                        click.prompt("  按回车继续", default="", show_default=False)

                    run_items(
                        inst_osc,
                        inst_calibrator,
                        cmd_osc,
                        cmd_calibrator,
                        characteristics_data,
                        ch,
                        probe,
                        item_list,
                        item_plans=plans_by_channel.get(ch, {}),
                        on_result=record_result,
                    )
                metadata["status"] = (
                    "completed_with_errors" if metadata["failures"] else "completed"
                )
                recording.checkpoint()
            except BaseException as exc:
                metadata["status"] = (
                    "interrupted" if isinstance(exc, (KeyboardInterrupt, click.Abort)) else "failed"
                )
                metadata["error"] = {
                    "type": type(exc).__name__,
                    "message": str(exc) or "校准被中断",
                }
                if not recording.save_failed:
                    recording.checkpoint()
                raise

            if metadata["failures"]:
                session_failed = True
                console.print("\n[yellow]校准完成，部分项目失败；已保存部分结果与失败原因[/yellow]")
            else:
                console.print("\n[bold green]✓ 校准完成！[/bold green]")

            round_start_errors = scpi_trace.failure_count()
            if not click.confirm("\n是否继续校准？", default=False):
                break
            # 重置参数，下一轮重新选择
            channel = None
            items = None
        if session_failed:
            raise click.ClickException("本次会话有项目执行失败，详情见已保存记录")
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
@click.option(
    "--scheme",
    type=click.STRING,
    default="jjf1057_2026_single",
    show_default=True,
    help="校准方案：schemes/ 下的名称（可省 .json）或文件路径",
)
@click.option(
    "--characteristics",
    type=click.STRING,
    default="tektronix_mdo3052",
    show_default=True,
    help="仪器特征：characteristics/ 下的名称（可省 .json）或文件路径",
)
@click.option("--calibrator", type=click.Path(exists=True), help="校准仪配置路径")
@click.option("--probe", type=click.STRING, default="9530", help="校准仪探头型号")
@click.option("--channel", type=click.STRING, default="1,2", help="通道，逗号分隔（如 1,2）")
@click.option("--json", "json_out", type=click.Path(), default=None, help="同时写出计划 JSON")
def plan(scheme, characteristics, calibrator, probe, channel, json_out):
    """只解析校准点表，不连接任何仪器。"""
    import json

    from osccal.core.methods import describe_methods_short
    from osccal.core.points import STRATEGY_LABELS, build_plan

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    specs_dir = os.path.join(base_dir, "specs")
    schemes_dir = os.path.join(base_dir, "schemes")
    characteristics_dir = os.path.join(base_dir, "characteristics")
    calibrators_dir = os.path.join(base_dir, "calibrators")

    console.print(Panel("[bold blue]校准点表解析[/bold blue]（离线，不连接仪器）", expand=False))

    scheme_path = resolve_config_path(schemes_dir, scheme)
    if scheme_path is None:
        raise click.BadParameter(f"找不到方案配置文件: {scheme}", param_hint="--scheme")
    scheme_data = load_scheme(scheme_path)
    if not scheme_data:
        raise click.UsageError("校准方案配置校验失败，已中止")

    spec_name = scheme_data.get("spec", "")
    spec_path = resolve_config_path(specs_dir, spec_name)
    if spec_path is None:
        raise click.UsageError(f"校准方案 {scheme} 引用的规范不存在: {spec_name}")
    spec_data = load_spec(spec_path)
    if not spec_data:
        raise click.UsageError("校准规范配置校验失败，已中止")

    characteristics_path = resolve_config_path(characteristics_dir, characteristics)
    if characteristics_path is None:
        raise click.BadParameter(
            f"找不到特征文件: {characteristics}", param_hint="--characteristics"
        )
    calibrator_path = calibrator or _first_config(calibrators_dir, "校准仪")
    if calibrator_path is None:
        raise click.UsageError("缺少校准仪配置")

    characteristics_data = load_characteristics(characteristics_path)
    calibrator_data = load_calibrator(calibrator_path)
    if not characteristics_data or not calibrator_data:
        raise click.UsageError("特征或校准仪配置加载失败")

    channels = [c.strip() for c in channel.split(",") if c.strip()]
    plan_data = build_plan(
        spec_data, scheme_data, characteristics_data, calibrator_data, probe, channels
    )

    table = Table(
        title=(
            f"校准点表　{plan_data['spec_code']}　"
            f"{plan_data['characteristics_series']}　{plan_data['scheme_name']}"
        )
    )
    table.add_column("条款", min_width=6)
    table.add_column("校准项目", min_width=12)
    table.add_column("方法", min_width=15)
    table.add_column("取点策略", min_width=9)
    table.add_column("点数", justify="right", min_width=3)
    table.add_column("跳过", justify="right", min_width=3)
    for item in plan_data["items"]:
        strategy = item["strategy"]
        clause_text = item["clause"].split(" / ")[0]
        if item["status"] == "manual":
            strategy_text = "人工"
            methods_text = "—"
        elif item["status"] == "not_in_scheme":
            strategy_text = "方案未列入"
            methods_text = "—"
        else:
            strategy_text = STRATEGY_LABELS.get(strategy, strategy or "—")
            methods_text = describe_methods_short(item["name"], item["methods"], item["primary"])
        table.add_row(
            clause_text,
            item["title"],
            methods_text,
            strategy_text,
            str(len(item["points"])),
            str(len(item["skipped"])),
        )
    console.print(table)
    console.print(
        f"合计 [bold]{plan_data['total_points']}[/bold] 个校准点，"
        f"跳过 [bold]{plan_data['total_skipped']}[/bold] 处"
    )

    for item in plan_data["items"]:
        if item["status"] != "planned":
            continue
        for skip in item["skipped"]:
            detail = " ".join(f"{k}={v}" for k, v in skip.items() if k != "reason")
            console.print(
                f"[yellow]·[/yellow] {item['title']} 跳过 {detail or '-'}：{skip.get('reason', '')}"
            )

    if json_out:
        directory = os.path.dirname(os.path.abspath(json_out))
        os.makedirs(directory, exist_ok=True)
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(plan_data, f, ensure_ascii=False, indent=2)
        console.print(f"[green]✓[/green] 计划已写入: [cyan]{json_out}[/cyan]")


def _first_config(directory: str, label: str) -> str | None:
    """返回目录下第一个 JSON 配置的完整路径。"""
    files = list_config_files(directory)
    if not files:
        console.print(f"[red]✗[/red] {label} 目录为空: {directory}")
        return None
    return os.path.join(directory, files[0])


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
            parsed = _parse_socket_addr(socket)
            if parsed is None:
                return
            inst, idn_info = connect_socket(*parsed)
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
    from osccal.core.storage import STATUS_LABELS

    metadata = data.get("metadata", {})
    results = data.get("results", {})

    console.print()
    info_table = Table(title="校准信息", show_lines=True)
    info_table.add_column("项目", style="cyan")
    info_table.add_column("内容", style="white")

    info_table.add_row("校准时间", metadata.get("timestamp", ""))
    info_table.add_row("校准状态", STATUS_LABELS.get(metadata.get("status"), "未记录"))
    info_table.add_row("SCPI 失败次数", str(metadata.get("scpi_errors", "未记录")))
    for name, failure in metadata.get("failures", {}).items():
        info_table.add_row(f"失败项目 {name}", failure.get("message", ""))
    info_table.add_row("通道", f"CH{metadata.get('channel', '')}")
    info_table.add_row("探头", metadata.get("probe", ""))
    characteristics_file = metadata.get("characteristics_file") or metadata.get("profile_file")
    if characteristics_file:
        info_table.add_row("特征配置", characteristics_file)

    osc = metadata.get("oscilloscope", {})
    info_table.add_row("示波器", f"{osc.get('manufacturer', '')} {osc.get('model', '')}")
    info_table.add_row("示波器序列号", osc.get("serial", ""))

    cal = metadata.get("calibrator", {})
    info_table.add_row("校准仪", f"{cal.get('manufacturer', '')} {cal.get('model', '')}")

    console.print(info_table)

    skipped_points = metadata.get("skipped_points", [])
    if skipped_points:
        skipped_table = Table(title="跳过的校准点", show_lines=True)
        skipped_table.add_column("项目", style="cyan")
        skipped_table.add_column("原因")
        for note in skipped_points:
            skipped_table.add_row(str(note.get("item", "")), str(note.get("reason", "")))
        console.print(skipped_table)

    from osccal.core.table_configs import (
        LIMITS_DISCLAIMER,
        active_config,
        base_item_name,
        method_note,
        reference_text,
        row_values,
        select_rows,
    )
    from osccal.core.utils import format_display_value

    # 按校准项目分组：同一项目的所有通道数据合并到同一个表格。
    # 失败项目即使留有部分数据点也不展示（失败原因见"校准信息"表），避免半套结果被当成完整记录。
    failed_keys = set(metadata.get("failures", {}))
    grouped: dict[str, list] = {}
    for item_name, rows in results.items():
        if not rows or item_name in failed_keys:
            continue
        base_name = base_item_name(item_name)
        grouped.setdefault(base_name, []).extend(rows)

    for base_name, rows in grouped.items():
        config = active_config(base_name, rows, metadata.get("scheme"))
        if config is None:
            console.print(f"[yellow]⚠ 未知校准项目，跳过显示: {base_name}[/yellow]")
            continue
        data_rows = select_rows(config, rows)
        if not data_rows:
            continue

        table = Table(title=config["title"], show_lines=True)
        for col in config["columns"]:
            table.add_column(col, justify="right")

        precision_specs = config.get("precision") or []
        for row in data_rows:
            values = row_values(config, row)
            str_values = [
                format_display_value(v, precision_specs[i] if i < len(precision_specs) else None)
                for i, v in enumerate(values)
            ]
            table.add_row(*str_values)

        console.print()
        console.print(table)
        note = method_note(base_name, rows, metadata.get("scheme"))
        if note:
            console.print(f"[dim]执行方法：{note}[/dim]")
        console.print(f"[dim]参考指标：{reference_text(base_name, metadata.get('limits'))}[/dim]")

    if grouped:
        console.print(f"\n[dim]{LIMITS_DISCLAIMER}[/dim]")

    spec = metadata.get("spec") or {}
    if spec:
        console.print(
            f"[dim]依据规范：{spec.get('name', '')}（{spec.get('spec_code', '')}），"
            f"配置文件 {spec.get('file', '')}[/dim]"
        )
    scheme = metadata.get("scheme") or {}
    if scheme:
        console.print(
            f"[dim]依据方案：{scheme.get('name', '')}，配置文件 {scheme.get('file', '')}[/dim]"
        )
    if spec:
        for deviation in spec.get("deviations", []):
            console.print(f"[dim]偏离声明：{deviation}[/dim]")


def main() -> None:
    """命令行入口：先统一输出编码，再执行 CLI。

    把编码设置放在这里（而非模块导入时）可避免影响作为库导入本模块的调用方，
    同时保证任何输出（含 --help、子命令）之前编码已就绪。
    """
    from osccal.core.utils import enable_utf8_output

    enable_utf8_output()
    cli()


if __name__ == "__main__":
    main()
