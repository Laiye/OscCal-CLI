import json
import os
from datetime import datetime

from rich.console import Console

console = Console()

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data"
)


def save_calibration_data(cal_results: dict, metadata: dict) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"calibration_{timestamp}.json"
    filepath = os.path.join(DATA_DIR, filename)

    data = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "channel": metadata.get("channel", ""),
            "probe": metadata.get("probe", ""),
            "oscilloscope": metadata.get("oscilloscope", {}),
            "calibrator": metadata.get("calibrator", {}),
            "commands_file": metadata.get("commands_file", ""),
            "profile_file": metadata.get("profile_file", ""),
            "calibrator_file": metadata.get("calibrator_file", ""),
            "simulated": metadata.get("simulated", False),
            "limits": metadata.get("limits", {}),
        },
        "results": cal_results,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    console.print(f"[green]✓[/green] 校准数据已保存: [cyan]{filepath}[/cyan]")
    return filepath


def load_calibration_data(filepath: str) -> dict:
    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        console.print(f"[red]✗[/red] 文件不存在: {filepath}")
        return {}
    except json.JSONDecodeError as e:
        console.print(f"[red]✗[/red] JSON 解析错误: {e}")
        return {}


def list_calibration_files() -> list[str]:
    if not os.path.isdir(DATA_DIR):
        return []
    files = sorted(
        [f for f in os.listdir(DATA_DIR) if f.startswith("calibration_") and f.endswith(".json")],
        reverse=True,
    )
    return files


def get_latest_calibration_file() -> str:
    files = list_calibration_files()
    if not files:
        return ""
    return os.path.join(DATA_DIR, files[0])
