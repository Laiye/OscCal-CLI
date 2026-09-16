import hashlib
import json
import os
import tempfile
from datetime import datetime
from uuid import uuid4

import click
from rich.console import Console

from osccal.core import scpi_trace

console = Console()

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data"
)

STATUS_LABELS = {
    "in_progress": "进行中（阶段记录）",
    "completed": "已完成",
    "completed_with_errors": "已结束（部分项目失败）",
    "interrupted": "已中断（部分结果）",
    "failed": "失败（部分结果）",
}


def configuration_snapshot(config: dict) -> dict:
    """记录实际使用的配置副本及内容摘要，便于文件修改后追溯。"""
    content = json.dumps(config, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return {
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "data": json.loads(content),
    }


class CalibrationRecording:
    """一轮校准的阶段记录，持有独立路径、结果和错误计数基线。"""

    def __init__(self, metadata: dict, start_errors: int = 0):
        self.metadata = metadata
        self.results: dict = {}
        self.filepath: str | None = None
        self.start_errors = start_errors
        self.save_failed = False

    def checkpoint(self):
        self.metadata["scpi_errors"] = scpi_trace.failure_count() - self.start_errors
        try:
            self.filepath = save_calibration_data(
                self.results, self.metadata, filepath=self.filepath
            )
        except BaseException:
            self.save_failed = True
            raise

    def record_result(self, name, rows, error, *, channel, multichannel):
        result_key = f"{name}_ch{channel}" if multichannel else name
        self.results[result_key] = rows
        self.metadata["item_status"][result_key] = "completed" if error is None else "failed"
        if error is not None:
            self.metadata["failures"][result_key] = {
                "type": type(error).__name__,
                "message": str(error) or "校准被中断",
            }
            if isinstance(error, (KeyboardInterrupt, click.Abort)):
                self.metadata["item_status"][result_key] = "interrupted"
        self.checkpoint()


def save_calibration_data(cal_results: dict, metadata: dict, *, filepath: str | None = None) -> str:
    """原子保存结果；传入已有路径时更新同一轮校准的阶段记录。"""
    now = datetime.now()
    if filepath is None:
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
        filename = f"calibration_{timestamp}_{uuid4().hex}.json"
        filepath = os.path.join(DATA_DIR, filename)
    directory = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(directory, exist_ok=True)

    data = {
        "metadata": {
            "timestamp": now.isoformat(),
            "channel": metadata.get("channel", ""),
            "probe": metadata.get("probe", ""),
            "oscilloscope": metadata.get("oscilloscope", {}),
            "calibrator": metadata.get("calibrator", {}),
            "commands_file": metadata.get("commands_file", ""),
            "profile_file": metadata.get("profile_file", ""),
            "calibrator_file": metadata.get("calibrator_file", ""),
            "simulated": metadata.get("simulated", False),
            "limits": metadata.get("limits", {}),
            "scpi_errors": 0,
            **metadata,
            "updated_at": now.isoformat(),
        },
        "results": cal_results,
    }

    temporary_path = None
    try:
        # 临时文件与目标文件同目录，写入完整并刷新后再替换，保留旧的有效记录。
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=".calibration_",
            suffix=".tmp",
            delete=False,
        ) as f:
            temporary_path = f.name
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_path, filepath)
    finally:
        if temporary_path is not None and os.path.exists(temporary_path):
            os.unlink(temporary_path)

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
