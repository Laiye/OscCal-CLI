import time
from rich.progress import Progress
from osccal.measure.base import BaseCalibrator, format_with_fixed_precision, console


class DcGainCalibrator(BaseCalibrator):

    def run(self):
        self.print_title("校准直流增益准确度")
        self.init_devices()
        self.setup_channel()

        self.setup_measurement("meas_mean")
        self._write_osc("set_acquisition_mode", self.cmd_osc["keyword"]["acquisition_mode_average"])
        self._write_osc("set_number_of_acquisitions", 2)

        self._write_calibrator("set_shap", "DC")
        self._setup_signal_impedance("DC", "1M")
        self._write_calibrator("set_output", "ON")

        vertical_div = self.profile.get("vertical_div", 8)
        points = self.profile.get("points", {}).get("dc_gain", [])
        limits = self.profile.get("calibration_limits", {}).get("dc_gain", None)
        limit_range = None
        if limits:
            limit_range = (limits.get("lower", -2.0), limits.get("upper", 2.0))

        columns = [
            {"name": "序号"},
            {"name": "通道"},
            {"name": "阻抗"},
            {"name": "挡位(V/div)"},
            {"name": "标准值U+(V)"},
            {"name": "标准值U-(V)"},
            {"name": "被校示值Ur+(V)"},
            {"name": "被校示值Ur-(V)"},
            {"name": "直流增益误差(%)"},
        ]
        table = self.make_table("直流增益校准结果", columns)

        total_points = len(points)
        if self.profile.get("imp_has_50", False):
            total_points += sum(1 for v in points if v <= 1)

        with Progress() as progress:
            task = progress.add_task("直流增益校准", total=total_points)

            for i, val in enumerate(points):
                self._write_osc("set_vertical_scale", self.channel, val)

                std_value_p = val * (vertical_div - 2) * 0.5
                self._write_calibrator("set_volt", std_value_p)

                time.sleep(1)
                self._write_osc("set_number_of_acquisitions", 16)
                time.sleep(5)

                self._adjust_vertical_position(val)

                measure_p = self._read_meas("meas_mean")

                self._write_osc("set_number_of_acquisitions", 2)

                std_value_n = val * -0.5 * (vertical_div - 2)
                self._write_calibrator("set_volt", std_value_n)

                time.sleep(1)
                self._write_osc("set_number_of_acquisitions", 16)
                time.sleep(5)

                measure_n = self._read_meas("meas_mean")

                self._write_osc("set_number_of_acquisitions", 2)

                std_p_fmt = float(format_with_fixed_precision(std_value_p, 3))
                std_n_fmt = float(format_with_fixed_precision(std_value_n, 3))
                meas_p_fmt = float(format_with_fixed_precision(measure_p, 3))
                meas_n_fmt = float(format_with_fixed_precision(measure_n, 3))

                denom = std_p_fmt - std_n_fmt
                g = (meas_p_fmt - meas_n_fmt) / denom if denom != 0 else 1.0
                e = round(100 * (1 - g) / g, 2) if g != 0 else 0.0

                row_data = [
                    i,
                    f"CH{self.channel}",
                    "1 MΩ",
                    round(val, 3),
                    format_with_fixed_precision(std_value_p, 3),
                    format_with_fixed_precision(std_value_n, 3),
                    format_with_fixed_precision(measure_p, 3),
                    format_with_fixed_precision(measure_n, 3),
                    e,
                ]
                self.add_result_row(table, row_data, limit_range, check_col=8)

                self.results.append({
                    "index": i,
                    "channel": self.channel,
                    "impedance": "1MΩ",
                    "scale": val,
                    "std_value_p": std_value_p,
                    "std_value_n": std_value_n,
                    "measured_p": measure_p,
                    "measured_n": measure_n,
                    "error": e,
                })

                progress.update(task, advance=1)

            self._write_calibrator("set_output", "OFF")

            if self.profile.get("imp_has_50", False):
                self._write_calibrator("preset")
                time.sleep(3)

                self._write_osc("set_number_of_acquisitions", 2)

                self._write_calibrator("set_shap", "DC")
                self._setup_signal_impedance("DC", "50")
                self._write_calibrator("set_output", "ON")

                time.sleep(3)

                offset = len(points)
                for i, val in enumerate(points):
                    if val > 1:
                        continue

                    self._write_osc("set_vertical_scale", self.channel, val)

                    std_value_p = val * (vertical_div - 2) * 0.5
                    self._write_calibrator("set_volt", std_value_p)

                    time.sleep(1)
                    self._write_osc("set_number_of_acquisitions", 16)
                    time.sleep(5)

                    self._adjust_vertical_position(val)

                    measure_p = self._read_meas("meas_mean")

                    self._write_osc("set_number_of_acquisitions", 2)

                    std_value_n = val * -0.5 * (vertical_div - 2)
                    self._write_calibrator("set_volt", std_value_n)

                    time.sleep(1)
                    self._write_osc("set_number_of_acquisitions", 16)
                    time.sleep(5)

                    measure_n = self._read_meas("meas_mean")

                    self._write_osc("set_number_of_acquisitions", 2)

                    std_p_fmt = float(format_with_fixed_precision(std_value_p, 3))
                    std_n_fmt = float(format_with_fixed_precision(std_value_n, 3))
                    meas_p_fmt = float(format_with_fixed_precision(measure_p, 3))
                    meas_n_fmt = float(format_with_fixed_precision(measure_n, 3))

                    denom = std_p_fmt - std_n_fmt
                    g = (meas_p_fmt - meas_n_fmt) / denom if denom != 0 else 1.0
                    e = round(100 * (1 - g) / g, 2) if g != 0 else 0.0

                    row_data = [
                        offset + i,
                        f"CH{self.channel}",
                        "50 Ω",
                        round(val, 3),
                        format_with_fixed_precision(std_value_p, 3),
                        format_with_fixed_precision(std_value_n, 3),
                        format_with_fixed_precision(measure_p, 3),
                        format_with_fixed_precision(measure_n, 3),
                        e,
                    ]
                    self.add_result_row(table, row_data, limit_range, check_col=8)

                    self.results.append({
                        "index": offset + i,
                        "channel": self.channel,
                        "impedance": "50Ω",
                        "scale": val,
                        "std_value_p": std_value_p,
                        "std_value_n": std_value_n,
                        "measured_p": measure_p,
                        "measured_n": measure_n,
                        "error": e,
                    })

                    progress.update(task, advance=1)

        console.print(table)
        self._write_calibrator("set_output", "OFF")
