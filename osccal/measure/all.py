import time
from rich.console import Console
from osccal.measure.amp import AmpCalibrator
from osccal.measure.dc_gain import DcGainCalibrator
from osccal.measure.delta_time import DeltaTimeCalibrator
from osccal.measure.bandwidth import BandwidthCalibrator
from osccal.measure.transient import TransientCalibrator

console = Console()


def run_all(inst_osc, inst_calibrator, cmd_osc, cmd_calibrator, profile, channel, probe=None):
    all_results = {}

    calibrators = [
        ("amp", AmpCalibrator),
        ("dc_gain", DcGainCalibrator),
        ("delta_time", DeltaTimeCalibrator),
        ("bandwidth", BandwidthCalibrator),
        ("transient", TransientCalibrator),
    ]

    for name, CalClass in calibrators:
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
