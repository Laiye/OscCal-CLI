import math
import time

from rich.progress import Progress

from osccal.core.utils import format_with_fixed_precision
from osccal.measure.base import BaseCalibrator, console, ensure_output_off


class DcGainCalibrator(BaseCalibrator):
    def _measure_dc_pair(self, val, impedance_label, row_index):
        vertical_div = self.profile.get("vertical_div", 8)
        averages = self._get_measurement_averages()

        self._write_osc("set_vertical_scale", self.channel, val)
        # 换挡位后微调触发电平，迫使平均序列重新开始（避免粘滞的旧平均值）
        self._nudge_trigger_level(val)

        std_value_p = val * (vertical_div - 2) * 0.5
        self._write_calibrator("set_volt", std_value_p)

        time.sleep(1)
        self._write_osc("set_number_of_acquisitions", averages)
        time.sleep(5)

        self._adjust_vertical_position(val)

        measure_p = self._read_meas("meas_mean")

        self._write_osc("set_number_of_acquisitions", 2)

        std_value_n = val * -0.5 * (vertical_div - 2)
        self._write_calibrator("set_volt", std_value_n)
        # 正/负半周之间挡位不变，同样需要一次微调让平均重新开始
        self._nudge_trigger_level(val)

        time.sleep(1)
        self._write_osc("set_number_of_acquisitions", averages)
        time.sleep(5)

        measure_n = self._read_meas("meas_mean")

        self._write_osc("set_number_of_acquisitions", 2)

        denom = std_value_p - std_value_n
        if not math.isfinite(denom) or denom == 0:
            raise ValueError("直流增益标准值差无效")
        g = (measure_p - measure_n) / denom
        if not math.isfinite(g) or g == 0:
            raise ValueError("直流增益无效：正负测量值相同或非有限数值")
        error = 100 * (1 - g) / g
        if not math.isfinite(error):
            raise ValueError("直流增益误差非有限数值")
        e = error

        return {
            "val": val,
            "impedance": impedance_label,
            "std_value_p": std_value_p,
            "std_value_n": std_value_n,
            "measured_p": measure_p,
            "measured_n": measure_n,
            "error": e,
            "row_data": [
                row_index,
                f"CH{self.channel}",
                impedance_label,
                round(val, 3),
                format_with_fixed_precision(std_value_p, 3),
                format_with_fixed_precision(std_value_n, 3),
                format_with_fixed_precision(measure_p, 3),
                format_with_fixed_precision(measure_n, 3),
                round(e, 2),
            ],
        }

    @ensure_output_off
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

        points = self.profile.get("points", {}).get("dc_gain", [])
        limit_range = self._get_limits("dc_gain")

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
                result = self._measure_dc_pair(val, "1 MΩ", i + 1)
                self.add_result_row(
                    table, result["row_data"], limit_range, check_col=8, check_value=result["error"]
                )
                self.results.append(
                    {
                        "index": i + 1,
                        "channel": self.channel,
                        "impedance": "1MΩ",
                        "scale": result["val"],
                        "std_value_p": result["std_value_p"],
                        "std_value_n": result["std_value_n"],
                        "measured_p": result["measured_p"],
                        "measured_n": result["measured_n"],
                        "error": result["error"],
                    }
                )
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

                    result = self._measure_dc_pair(val, "50 Ω", offset + i + 1)
                    self.add_result_row(
                        table,
                        result["row_data"],
                        limit_range,
                        check_col=8,
                        check_value=result["error"],
                    )
                    self.results.append(
                        {
                            "index": offset + i + 1,
                            "channel": self.channel,
                            "impedance": "50Ω",
                            "scale": result["val"],
                            "std_value_p": result["std_value_p"],
                            "std_value_n": result["std_value_n"],
                            "measured_p": result["measured_p"],
                            "measured_n": result["measured_n"],
                            "error": result["error"],
                        }
                    )
                    progress.update(task, advance=1)

        console.print(table)
