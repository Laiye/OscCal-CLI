import socket
from rich.console import Console
from rich.table import Table
from osccal.core.comm import scpi_query

console = Console()


def _parse_idn(idn_str: str) -> dict:
    parts = idn_str.replace("\n", "").split(",")
    return {
        "manufacturer": parts[0] if len(parts) > 0 else "",
        "model": parts[1] if len(parts) > 1 else "",
        "serial": parts[2] if len(parts) > 2 else "",
        "firmware": parts[3] if len(parts) > 3 else "",
    }


def _print_device_info(idn_info: dict) -> None:
    table = Table(title="设备信息", show_header=True, header_style="bold cyan")
    table.add_column("属性", style="bold")
    table.add_column("值")
    table.add_row("制造商", idn_info.get("manufacturer", ""))
    table.add_row("型号", idn_info.get("model", ""))
    table.add_row("序列号", idn_info.get("serial", ""))
    table.add_row("固件版本", idn_info.get("firmware", ""))
    console.print(table)


def list_visa_resources() -> list[str]:
    try:
        import pyvisa
        rm = pyvisa.ResourceManager()
        resources = list(rm.list_resources())
        rm.close()
        console.print(f"[green]✓[/green] 找到 {len(resources)} 个 VISA 资源")
        for r in resources:
            console.print(f"  [cyan]{r}[/cyan]")
        return resources
    except ImportError:
        console.print("[red]✗[/red] pyvisa 未安装，请运行: pip install pyvisa")
        return []
    except Exception as e:
        console.print(f"[red]✗[/red] 列出 VISA 资源失败: {e}")
        return []


def connect_visa(resource: str) -> tuple:
    try:
        import pyvisa
        rm = pyvisa.ResourceManager()
        inst = rm.open_resource(resource)
        idn_raw = scpi_query(inst, "*IDN?", "pyvisa")
        idn_info = _parse_idn(idn_raw)
        console.print(f"[green]✓[/green] VISA 连接成功: [cyan]{resource}[/cyan]")
        _print_device_info(idn_info)
        return inst, idn_info
    except ImportError:
        console.print("[red]✗[/red] pyvisa 未安装，请运行: pip install pyvisa")
        return None, {}
    except Exception as e:
        console.print(f"[red]✗[/red] VISA 连接失败 ({resource}): {e}")
        return None, {}


def connect_socket(host: str, port: int) -> tuple:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, port))
        idn_raw = scpi_query(s, "*IDN?", "socket")
        idn_info = _parse_idn(idn_raw)
        console.print(f"[green]✓[/green] Socket 连接成功: [cyan]{host}:{port}[/cyan]")
        _print_device_info(idn_info)
        return s, idn_info
    except Exception as e:
        console.print(f"[red]✗[/red] Socket 连接失败 ({host}:{port}): {e}")
        return None, {}


def connect_device(
    resource: str = "",
    comm_type: str = "pyvisa",
    host: str = None,
    port: int = None,
) -> tuple:
    if comm_type == "pyvisa":
        if not resource:
            console.print("[red]✗[/red] VISA 模式需要指定 resource 参数")
            return None, {}
        return connect_visa(resource)
    if comm_type == "socket":
        if not host or port is None:
            console.print("[red]✗[/red] Socket 模式需要指定 host 和 port 参数")
            return None, {}
        return connect_socket(host, port)
    console.print(f"[red]✗[/red] 不支持的通信类型: {comm_type}")
    return None, {}
