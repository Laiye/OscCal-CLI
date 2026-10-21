"""校准项目调度。

重建期（v0.2.0 M1'）`registry.RUNNERS` 为空，任何项目都会明确抛出
`ItemNotImplementedError`，**不静默跳过、不降级**。M3'~M5' 把 runner 注册进
`RUNNERS` 后本模块即可直接工作。
"""

from rich.console import Console

from osccal.measure.registry import ITEM_ORDER, RUNNERS

console = Console()


class ItemNotImplementedError(RuntimeError):
    """校准项目尚未实现（v0.2.0 重建期）。"""


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
    """依次执行项目；存在未实现项目时直接报错，避免产出半套结果。

    `points_by_item` 是 {项目名: 校准点列表}，由 core/points.py 按规范解析得到。
    """
    pending = pending_items(list(items))
    if pending:
        raise ItemNotImplementedError(f"项目尚未实现: {', '.join(pending)}")

    planned = points_by_item or {}
    results: dict = {}
    for name in items:
        console.rule(f"[bold blue]{name}[/bold blue]")
        runner = RUNNERS[name]
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
