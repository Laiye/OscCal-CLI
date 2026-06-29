import time
from rich.console import Console
from osccal.measure.registry import CALIBRATOR_ORDER

console = Console()


def run_all(inst_osc, inst_calibrator, cmd_osc, cmd_calibrator, profile, channel, probe=None):
    all_results = {}

    for entry in CALIBRATOR_ORDER:
        name, CalClass = entry["name"], entry["class"]
        try:
            console.rule(f"[bold blue]{name}[/bold blue]")
            cal = CalClass(inst_osc, inst_calibrator, cmd_osc, cmd_calibrator, profile, channel, probe)
            cal.run()
            all_results[name] = cal.get_results()
            time.sleep(5)
        except Exception as e:
            console.print(f"[red]✗[/red] {name} 校准失败: {e}")
            all_results[name] = []

    return all_results
