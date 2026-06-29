import time
from rich.progress import Progress
from osccal.measure.base import BaseCalibrator, console
from osccal.core.utils import format_with_fixed_precision


class DeltaTimeCalibrator(BaseCalibrator):

    def run(self):
        self.print_title("校准Δt(时间)")
        self.init_devices()
        self.setup_channel()

        self._write_osc("set_vertical_scale", self.channel, 0.2)
        self.setup_measurement("meas_period")

        self._write_calibrator("set_shap", "MARK")
        if self.profile.get("imp_has_50", False):
            self._setup_signal_impedance("MARK", "50")
        else:
            self._setup_signal_impedance("MARK", "1M")
        self._write_calibrator("set_output", "ON")

        horizontal_div = self.profile.get("horizontal_div", 10)
        points = self.profile.get("points", {}).get("delta_time", [])
        limit_range = self._get_limits("delta_time")

        columns = [
            {"name": "序号"},
            {"name": "通道"},
            {"name": "挡位(s/div)"},
            {"name": "标准值MT(s)"},
            {"name": "被校示值tm(s)"},
            {"name": "相对误差(%)"},
        ]
        table = self.make_table("Δt校准结果", columns)

        with Progress() as progress:
            task = progress.add_task("Δt校准", total=len(points))
            for i, val in enumerate(points):
                self._write_osc("set_horizontal_scale", val)
                self._write_calibrator("set_mark_period", val)

                time.sleep(3)

                measured_raw = self._read_meas("meas_period")

                std_value = val * (horizontal_div - 2)
                measured = measured_raw * (horizontal_div - 2)

                std_fmt = float(format_with_fixed_precision(std_value, 4))
                meas_fmt = float(format_with_fixed_precision(measured, 4))
                error = round(100 * (meas_fmt - std_fmt) / std_fmt, 2) if std_fmt != 0 else 0.0

                row_data = [
                    i,
                    f"CH{self.channel}",
                    format_with_fixed_precision(val, 4),
                    format_with_fixed_precision(std_value, 4),
                    format_with_fixed_precision(measured, 4),
                    error,
                ]
                self.add_result_row(table, row_data, limit_range, check_col=5)

                self.results.append({
                    "index": i,
                    "channel": self.channel,
                    "scale": val,
                    "std_value": std_value,
                    "measured": measured,
                    "error": error,
                })

                progress.update(task, advance=1)

        console.print(table)
        self._write_calibrator("set_output", "OFF")
