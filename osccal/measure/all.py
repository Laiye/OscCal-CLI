"""校准项目调度：按注册顺序逐项执行。

单项失败不再中止整轮：捕获项目异常后写入 failures/item_status，保留该项目已测到
的数据点，继续执行后续项目。用户中断（Ctrl+C / click.Abort）与"无法关闭校准仪
输出"（OutputShutdownError）仍会立即终止会话。
"""

from click import Abort
from rich.console import Console

from osccal.measure.base import OutputShutdownError
from osccal.measure.registry import ITEM_ORDER, RUNNERS

console = Console()


class ItemNotImplementedError(RuntimeError):
    """校准项目尚未实现（RUNNERS 中缺少该项目）。"""


def pending_items(items: list[str] | None = None) -> list[str]:
    """返回尚未实现的项目名；items 为空表示按注册顺序检查全部。"""
    names = list(items) if items else list(ITEM_ORDER)
    return [name for name in names if name not in RUNNERS]


def run_items(
    inst_osc,
    inst_calibrator,
    cmd_osc,
    cmd_calibrator,
    profile,
    channel,
    probe,
    items,
    points_by_item=None,
    on_result=None,
):
    """依次执行项目；单项失败只记录该项目的失败，其余项目继续执行。

    `points_by_item` 是 {项目名: 校准点列表}，由 core/points.py 按规范解析得到。
    `on_result(项目名, 数据行, 异常或 None)` 在每个项目结束后调用。
    """
    pending = pending_items(list(items))
    if pending:
        raise ItemNotImplementedError(f"项目尚未实现: {', '.join(pending)}")

    planned = points_by_item or {}
    results: dict = {}
    for name in items:
        console.rule(f"[bold blue]{name}[/bold blue]")
        runner = RUNNERS[name]
        calibrator = None
        try:
            calibrator = runner(
                inst_osc,
                inst_calibrator,
                cmd_osc,
                cmd_calibrator,
                profile,
                channel,
                probe,
                planned.get(name, []),
            )
            calibrator.run()
        except (OutputShutdownError, Abort):
            # 无法确认关闭校准仪输出、或用户中断：必须终止整个会话，不能继续采集
            raise
        except Exception as exc:  # noqa: BLE001 - 单项失败不得终止整轮
            rows = calibrator.get_results() if calibrator is not None else []
            results[name] = rows
            console.print(f"[red]✗[/red] 项目 {name} 执行失败：{exc}")
            if on_result is not None:
                on_result(name, rows, exc)
            continue
        rows = calibrator.get_results()
        results[name] = rows
        if on_result is not None:
            on_result(name, rows, None)
    return results


def run_all(
    inst_osc,
    inst_calibrator,
    cmd_osc,
    cmd_calibrator,
    profile,
    channel,
    probe=None,
    points_by_item=None,
    on_result=None,
):
    """按注册顺序执行全部已实现项目。"""
    return run_items(
        inst_osc,
        inst_calibrator,
        cmd_osc,
        cmd_calibrator,
        profile,
        channel,
        probe,
        [name for name in ITEM_ORDER if name in RUNNERS],
        points_by_item,
        on_result=on_result,
    )
