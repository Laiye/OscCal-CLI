import json
import os
from collections.abc import Callable
from typing import cast

from rich.console import Console

from osccal.core.config_validation import (
    validate_calibrator,
    validate_characteristics,
    validate_commands,
    validate_scheme,
    validate_spec,
)
from osccal.core.types import (
    CalibratorConfig,
    CharacteristicsConfig,
    CommandConfig,
    SchemeConfig,
    SpecConfig,
)

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
        try:
            errors = validator(data)
        except Exception as e:
            console.print(f"[red]✗[/red] {label}配置校验异常 ({os.path.basename(filepath)}): {e}")
            return {}
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


def load_characteristics(filepath: str) -> CharacteristicsConfig:
    data = _load_json(filepath, validator=validate_characteristics, label="特征")
    if data:
        factor = data.get("factor", "unknown")
        series = data.get("series", "unknown")
        console.print(f"  特征配置: [yellow]{factor} {series}[/yellow]")
    return cast(CharacteristicsConfig, data)


def load_scheme(filepath: str) -> SchemeConfig:
    data = _load_json(filepath, validator=validate_scheme, label="校准方案")
    if data:
        name = data.get("name", "unknown")
        spec = data.get("spec", "")
        count = len(data.get("items", {}))
        suffix = f" | 规范: {spec}" if spec else ""
        console.print(f"  校准方案: [yellow]{name}[/yellow] | 项目: {count}{suffix}")
    return cast(SchemeConfig, data)


def load_calibrator(filepath: str) -> CalibratorConfig:
    data = _load_json(filepath, validator=validate_calibrator, label="校准仪")
    if data:
        name = data.get("name", "unknown")
        series = data.get("series", [])
        console.print(f"  校准仪: [yellow]{name}[/yellow] | 系列: {series}")
    return cast(CalibratorConfig, data)


def load_spec(filepath: str) -> SpecConfig:
    data = _load_json(filepath, validator=validate_spec, label="校准规范")
    if data:
        code = data.get("spec_code", "unknown")
        effective = data.get("effective", "")
        suffix = f" | 实施: {effective}" if effective else ""
        console.print(f"  校准规范: [yellow]{code}[/yellow]{suffix}")
    return cast(SpecConfig, data)


def resolve_config_path(directory: str, name_or_path: str | None) -> str | None:
    """把配置名（可省 .json）或直接路径解析为配置文件路径。"""
    if not name_or_path:
        return None
    if os.path.isfile(name_or_path):
        return name_or_path
    for candidate in (name_or_path, f"{name_or_path}.json"):
        path = os.path.join(directory, candidate)
        if os.path.isfile(path):
            return path
    return None
