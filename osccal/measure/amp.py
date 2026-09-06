import time

from rich.progress import Progress

from osccal.core.utils import format_with_fixed_precision
from osccal.measure.base import BaseCalibrator, console


class AmpCalibrator(BaseCalibrator):
    def run(self):
        self.print_title("校准ΔV(幅度)")
        self.init_devices()
        self.setup_channel()

        self._write_osc("set_horizontal_scale", 1e-3)
        self.setup_measurement("meas_amp")

        self._write_osc("set_acquisition_mode", self.cmd_osc["keyword"]["acquisition_mode_average"])
        self._write_osc("set_number_of_acquisitions", 2)

        self._write_calibrator("set_squ_polarity", "SYMM")
        self._setup_signal_impedance("SQU", "1M")
        self._write_calibrator("set_output", "ON")

        vertical_div = self.profile.get("vertical_div", 8)
        points = self.profile.get("points", {}).get("delta_amp", [])
        limit_range = self._get_limits("amp")

        columns = [
            {"name": "序号"},
            {"name": "通道"},
            {"name": "挡位(V/div)"},
            {"name": "标准值(V)"},
            {"name": "被校示值(V)"},
            {"name": "相对误差(%)"},
        ]
        table = self.make_table("幅度校准结果", columns)

        with Progress() as progress:
            task = progress.add_task("幅度校准", total=len(points))
            for i, val in enumerate(points):
                self._write_osc("set_vertical_scale", self.channel, val)

                std_value = val * (vertical_div - 2)
                self._write_calibrator("set_volt", std_value)

                time.sleep(1)
                self._write_osc("set_number_of_acquisitions", 16)
                time.sleep(5)

                self._adjust_vertical_position(val)

                measured = self._read_meas("meas_amp")

                std_fmt = float(format_with_fixed_precision(std_value, 3))
                meas_fmt = float(format_with_fixed_precision(measured, 3))
                error = round(100 * (meas_fmt - std_fmt) / std_value, 2) if std_value != 0 else 0.0

                self._write_osc("set_number_of_acquisitions", 2)

                row_data = [
                    i + 1,
                    f"CH{self.channel}",
                    round(val, 3),
                    format_with_fixed_precision(std_value, 3),
                    format_with_fixed_precision(measured, 3),
                    error,
                ]
                self.add_result_row(table, row_data, limit_range, check_col=5)

                self.results.append(
                    {
                        "index": i + 1,
                        "channel": self.channel,
                        "scale": val,
                        "std_value": std_value,
                        "measured": measured,
                        "error": error,
                    }
                )

                progress.update(task, advance=1)

        console.print(table)
        self._write_calibrator("set_output", "OFF")
