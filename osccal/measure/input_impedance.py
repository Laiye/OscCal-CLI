"""输入阻抗（JJF 1057-2026 7.3.1 方法一）。

规范方法：设置示波器输入为直流耦合、阻抗为 1 MΩ（或 50 Ω）状态，按图 1 连接
示波器校准仪与被校示波器，读取校准仪屏幕上显示的**电阻测量值 R₀ 与电容测量值 C₀**。

9500B 的对应能力在 `CONFigure` 子系统（Remote Commands Manual）：
    CONF:RES → READ?   输入电阻（1 MΩ 挡约 50 kΩ~20 MΩ；50 Ω 挡约 10~150 Ω）
    CONF:CAP → READ?   输入电容（约 1 pF~120 pF）
    无法分辨或未选中功能时返回哨兵值 2E35，必须判为无效，不能当成读数。

测量经有源头完成，因此校准仪通道阻抗要与被测通道一致（1 MΩ / 50 Ω），
测量结束后用 SOURce:FUNCtion:SHAPe 恢复常规波形输出。
"""

import math

from rich.progress import Progress

from osccal.measure.base import BaseCalibrator, console, ensure_output_off

#: 9500B 在无法给出读数时返回的哨兵值（见 Remote Commands Manual）。
INVALID_SENTINEL = 2e35
#: 标称阻抗与参考指标（规范表 1：50 Ω ±1%，1 MΩ ±0.5%）。
NOMINAL = {"1M": 1e6, "50": 50.0}
TOLERANCE_PCT = {"1M": 0.5, "50": 1.0}
#: 电容仅作记录，不做符合性判断。
IMPEDANCE_LABELS = {"1M": "1 MΩ", "50": "50 Ω"}


class InputImpedanceCalibrator(BaseCalibrator):
    """输入阻抗：读校准仪的 R 与 C。"""

    title = "输入阻抗（7.3.1）"

    @staticmethod
    def parse_reading(text: str) -> float | None:
        """解析 READ? 响应；哨兵值与非数值返回 None。"""
        for token in reversed(str(text).replace("\n", " ").split()):
            try:
                value = float(token)
            except ValueError:
                continue
            if not math.isfinite(value) or value >= INVALID_SENTINEL / 2:
                return None
            return value
        return None

    def _read_load(self, function: str) -> float | None:
        self._write_calibrator("set_load_func", function)
        return self.parse_reading(self._query_calibrator("query_load"))

    def _measure_point(self, point: dict) -> dict:
        impedance = point.get("impedance", "1M")
        nominal = NOMINAL[impedance]

        # 必须先退出负载测量功能再改阻抗：在测量功能下写 ROUT:SIGN:IMP 会被判
        # "settings conflict" 而静默不生效（实机表现：后续点仍按 1 MΩ 测量）。
        self._write_calibrator("set_shap", "DC")
        self._apply_impedance(impedance)
        self._write_osc("set_coupling", self.channel, "DC")

        resistance = self._read_load("RES")
        capacitance = self._read_load("CAP")
        # 本点结束即退出测量功能，避免影响下一个点的阻抗切换。
        self._write_calibrator("set_shap", "DC")

        error_pct = 100.0 * (resistance - nominal) / nominal if resistance is not None else None
        return {
            "channel": self.channel,
            "impedance": impedance,
            "nominal_ohm": nominal,
            "resistance_ohm": resistance,
            "capacitance_f": capacitance,
            "error_pct": error_pct,
            "tolerance_pct": TOLERANCE_PCT[impedance],
        }

    @ensure_output_off
    def run(self):
        self.print_title(self.title)
        self.init_devices()
        self.setup_channel()

        if not self.points:
            console.print("[yellow]⚠ 本轮没有可执行的校准点[/yellow]")
            return

        table = self.make_table(
            "输入阻抗校准结果",
            [
                {"name": "序号"},
                {"name": "通道", "justify": "center"},
                {"name": "阻抗状态", "justify": "center"},
                {"name": "标称值", "justify": "left"},
                {"name": "实测电阻", "justify": "left"},
                {"name": "实测电容", "justify": "left"},
                {"name": "电阻误差(%)"},
                {"name": "参考指标"},
            ],
        )

        with Progress() as progress:
            task = progress.add_task("输入阻抗", total=len(self.points))
            try:
                for index, point in enumerate(self.points, start=1):
                    record = self._measure_point(point)
                    self.results.append({"index": index, **record})
                    resistance = record["resistance_ohm"]
                    capacitance = record["capacitance_f"]
                    self.add_result_row(
                        table,
                        [
                            index,
                            f"CH{self.channel}",
                            IMPEDANCE_LABELS[record["impedance"]],
                            f"{record['nominal_ohm']:g} Ω",
                            "无效" if resistance is None else f"{resistance:.6g} Ω",
                            "无效" if capacitance is None else f"{capacitance * 1e12:.4g} pF",
                            "—" if record["error_pct"] is None else f"{record['error_pct']:+.3f}",
                            f"±{record['tolerance_pct']:g}%",
                        ],
                    )
                    progress.update(task, advance=1)
            finally:
                # 退出负载测量功能，恢复常规波形输出（手册：用 SOURce:FUNCtion:SHAPe 退出）
                self._write_calibrator("set_shap", "DC")
        console.print(table)
