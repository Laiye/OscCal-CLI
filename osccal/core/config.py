import json
import os
from collections.abc import Callable
from typing import cast

from rich.console import Console

from osccal.core.config_validation import (
    validate_calibrator,
    validate_commands,
    validate_profile,
)
from osccal.core.types import CalibratorConfig, CommandConfig, ProfileConfig

console = Console()

Validator = Callable[[dict], list[str]]


def _load_json(filepath: str, validator: Validator | None = None, label: str = "") -> dict:
    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        console.print(f"[red]✗[/red] 文件不存在: {filepath}")
        return {}
    except json.JSONDecodeError as e:
        console.print(f"[red]✗[/red] JSON 解析错误 ({filepath}): {e}")
        return {}
    except Exception as e:
        console.print(f"[red]✗[/red] 加载文件失败 ({filepath}): {e}")
        return {}

    if validator is not None:
        errors = validator(data)
        if errors:
            console.print(f"[red]✗[/red] {label}配置校验失败 ({os.path.basename(filepath)}):")
            for err in errors:
                console.print(f"    [red]- {err}[/red]")
            return {}
    console.print(f"[green]✓[/green] 已加载配置: [cyan]{os.path.basename(filepath)}[/cyan]")
    return data


def list_config_files(directory: str) -> list[str]:
    try:
        if not os.path.isdir(directory):
            console.print(f"[red]✗[/red] 目录不存在: {directory}")
            return []
        files = sorted(
            [
                f
                for f in os.listdir(directory)
                if f.endswith(".json") and os.path.isfile(os.path.join(directory, f))
            ]
        )
        console.print(
            f"[green]✓[/green] 在 [cyan]{directory}[/cyan] 中找到 {len(files)} 个配置文件"
        )
        return files
    except Exception as e:
        console.print(f"[red]✗[/red] 列出配置文件失败: {e}")
        return []


def load_commands(filepath: str) -> CommandConfig:
    data = _load_json(filepath, validator=validate_commands, label="指令集")
    if data:
        name = data.get("name", "unknown")
        series = data.get("series", [])
        comm_type = data.get("type", "pyvisa")
        console.print(f"  指令集: [yellow]{name}[/yellow] | 系列: {series} | 通信: {comm_type}")
    return cast(CommandConfig, data)


def load_profile(filepath: str) -> ProfileConfig:
    data = _load_json(filepath, validator=validate_profile, label="特征")
    if data:
        factor = data.get("factor", "unknown")
        series = data.get("series", "unknown")
        console.print(f"  特征配置: [yellow]{factor} {series}[/yellow]")
    return cast(ProfileConfig, data)


def load_calibrator(filepath: str) -> CalibratorConfig:
    data = _load_json(filepath, validator=validate_calibrator, label="校准仪")
    if data:
        name = data.get("name", "unknown")
        series = data.get("series", [])
        console.print(f"  校准仪: [yellow]{name}[/yellow] | 系列: {series}")
    return cast(CalibratorConfig, data)
