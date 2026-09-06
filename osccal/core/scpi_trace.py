"""SCPI 指令跟踪与失败统计（跨模块共享的轻量状态）。

- 指令日志：启用后记录每次 SCPI 写入/查询的指令与结果，供 --log-scpi 展示；
- 失败计数：记录通信重试耗尽或命令组装失败的总次数，供校准结果标注。
"""

from __future__ import annotations

from typing import Final

_log_enabled: bool = False
_log: list[tuple[str, str, str]] = []  # (方向 W/Q, 指令, 结果摘要)
_failures: int = 0

MAX_RESULT_LEN: Final = 200


def set_log_enabled(enabled: bool) -> None:
    """启用/关闭 SCPI 指令日志。"""
    global _log_enabled
    _log_enabled = enabled


def log_enabled() -> bool:
    return _log_enabled


def log_entry(direction: str, cmd: str, result: str = "") -> None:
    """记录一条 SCPI 指令（仅日志启用时生效）。"""
    if not _log_enabled:
        return
    summary = result.strip().replace("\n", " ")[:MAX_RESULT_LEN]
    _log.append((direction, cmd, summary))


def get_log() -> list[tuple[str, str, str]]:
    """返回指令日志副本。"""
    return list(_log)


def record_failure() -> None:
    """记录一次 SCPI 失败。"""
    global _failures
    _failures += 1


def failure_count() -> int:
    return _failures


def reset() -> None:
    """清空日志与失败计数（每次校准前调用）。"""
    global _log, _failures
    _log = []
    _failures = 0
