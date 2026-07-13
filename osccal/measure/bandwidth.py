import time
from rich.progress import Progress
from osccal.measure.base import BaseCalibrator, console
from osccal.core.utils import format_with_fixed_precision


class BandwidthCalibrator(BaseCalibrator):

    def run(self):
        self.print_title("频带宽度")
        self.init_devices()
        self.setup_channel()

        self._write_osc("set_vertical_scale", self.channel, 0.1)
        self._write_osc("set_trigger_source", self.channel)
        self.setup_measurement("meas_amp")
        self._write_osc("set_horizontal_scale", 1E-5)
        self._write_osc("set_acquisition_mode", self.cmd_osc["keyword"]["acquisition_mode_average"])
        self._write_osc("set_number_of_acquisitions", 16)

        self._write_calibrator("set_shap", "SIN")

        if self.profile.get("imp_has_50", False):
            self._setup_signal_impedance("SIN", "50")
        else:
            self._setup_signal_impedance("SIN", "1M")

        self._write_calibrator("set_volt", 0.003)
        self._write_calibrator("set_freq", 50E3)
        self._write_calibrator("set_output", "ON")

        time.sleep(2)

        vertical_div = self.profile.get("vertical_div", 8)
        points = self.profile.get("points", {}).get("bandwidth", [])
        start_bd = self.profile.get("bandwidth", 100E6)
        bd_step = self.profile.get("bd_step", 10E6)
        max_bd = self._get_probe_max_frequency_hz()

        columns = [
            {"name": "序号"},
            {"name": "通道"},
            {"name": "挡位(V/div)"},
            {"name": "实测值(MHz)"},
        ]
        table = self.make_table("频带宽度校准结果", columns)

        with Progress() as progress:
            task = progress.add_task("频带宽度校准", total=len(points))
            for i, val in enumerate(points):
                self._write_osc("set_horizontal_scale", 1E-5)
                self._write_osc("set_vertical_scale", self.channel, val)
                self._write_calibrator("set_freq", 50E3)
                self._write_calibrator("set_volt", val * (vertical_div - 2))

                time.sleep(5)

                ref_amp = self._read_meas("meas_amp")

                current_bd = start_bd
                current_amp = ref_amp

                while current_amp >= ref_amp * 0.707:
                    current_bd = current_bd + bd_step
                    if current_bd > max_bd:
                        break

                    self._write_calibrator("set_freq", current_bd)
                    self._write_osc("set_horizontal_scale", 0.5 / current_bd)

                    time.sleep(5)
                    current_amp = self._read_meas("meas_amp")
                    time.sleep(5)

                bandwidth_mhz = (current_bd - bd_step) * 1E-6

                row_data = [i + 1, f"CH{self.channel}", val, round(bandwidth_mhz, 2)]
                table.add_row(*[str(v) for v in row_data])

                self.results.append({
                    "index": i + 1,
                    "channel": self.channel,
                    "scale": val,
                    "bandwidth_mhz": bandwidth_mhz,
                })

                progress.update(task, advance=1)

        console.print(table)
        self._write_calibrator("set_output", "OFF")
