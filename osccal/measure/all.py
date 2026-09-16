import time

import click
from rich.console import Console

from osccal.measure.base import OutputShutdownError
from osccal.measure.registry import CALIBRATOR_ORDER, CALIBRATORS_MAP

console = Console()


def run_items(
    inst_osc,
    inst_calibrator,
    cmd_osc,
    cmd_calibrator,
    profile,
    channel,
    probe,
    items,
    on_result=None,
    pause=0,
):
    """统一执行项目；每项结束或中断时回传已完成的数据点及失败原因。"""
    all_results = {}

    for name in items:
        cal = None
        error = None
        try:
            console.rule(f"[bold blue]{name}[/bold blue]")
            CalClass = CALIBRATORS_MAP.get(name)
            if CalClass is None:
                raise ValueError(f"未知校准项目: {name}")
            cal = CalClass(
                inst_osc, inst_calibrator, cmd_osc, cmd_calibrator, profile, channel, probe
            )
            cal.run()
        except BaseException as exc:
            error = exc
            if not isinstance(exc, Exception) or isinstance(
                exc, (OutputShutdownError, click.Abort)
            ):
                raise
            console.print(f"[red]✗[/red] {name} 校准失败: {exc}")
        finally:
            rows = cal.get_results() if cal is not None else []
            all_results[name] = rows
            # 回调的存储错误必须向上传播，不能当成测量失败后继续运行。
            if on_result is not None:
                on_result(name, rows, error)
        if pause and error is None:
            time.sleep(pause)

    return all_results


def run_all(
    inst_osc,
    inst_calibrator,
    cmd_osc,
    cmd_calibrator,
    profile,
    channel,
    probe=None,
    on_result=None,
):
    """按注册顺序执行全部项目，并保留原有项目间稳定时间。"""
    return run_items(
        inst_osc,
        inst_calibrator,
        cmd_osc,
        cmd_calibrator,
        profile,
        channel,
        probe,
        [entry["name"] for entry in CALIBRATOR_ORDER],
        on_result,
        pause=5,
    )
