"""直流增益（JJF 1057-2026 7.4.1 / 7.4.2 / 7.4.3 三种方法并列）。

规范前置条件：选取通道量程、直流耦合、直流偏置调零。

- 方法一（7.4.1）：直流两点法。输入 V₊ 使显示在屏 90% 位置、V₋ 在 10% 位置，
  读测量值 V₊ᵣ、V₋ᵣ，G = (V₊ᵣ − V₋ᵣ)/(V₊ − V₋)。
- 方法二（7.4.2）：方波幅度法。1 kHz 方波、幅度 V，覆盖 ≥80% 屏，读幅度 Vᵣ，
  G = Vᵣ/V。
- 方法三（7.4.3）：多点最小二乘。m = 16 点、每点采集 n ≥ 1000 点，
  Eᵢ = E_L + (i − 0.5)·E_r/m，G = Σ(Eᵢ−Ē)(ȳᵢ−ȳ)/Σ(Eᵢ−Ē)²，截距 d = ȳ − G·Ē。

三种方法在同一次运行里对同一个点各测一遍，记录并列保存，便于互相印证。
"""

import time

from rich.progress import Progress

from osccal.measure.base import BaseCalibrator, console, ensure_output_off

#: 方法一的两个取点位置：屏幕高度的 90% / 10%（相对中心即 ±3.2 格，共 8 格）。
POSITION_HIGH = 0.9
POSITION_LOW = 0.1
#: 方法三的测量点数（规范取 m = 16）。
SWEEP_POINTS = 16
#: 方法三每点的采集点数下限（规范要求 n ≥ 1000）。
SWEEP_SAMPLES = 1000


class DcGainCalibrator(BaseCalibrator):
    """直流增益：方法一（直流两点）、方法二（方波幅度）、方法三（多点回归）。"""

    title = "直流增益（7.4.1 / 7.4.2 / 7.4.3）"

    def _zero_position(self) -> None:
        """规范 7.4 前置：直流耦合、直流偏置调零。"""
        self._write_osc("set_coupling", self.channel, "DC")
        # 1 kHz 方波：200 µs/div → 屏上 2 个周期，保证幅度测量有效
        self._set_timebase(200e-6)
        if "set_vertical_position" in self.cmd_osc["actions"]:
            self._write_osc("set_vertical_position", self.channel, 0.0)

    def _read_mean(self) -> tuple[float, float]:
        """读平均值并等收敛，返回 (读数, 已等待秒数)。

        直流电平换挡后标准源同样需要建立时间；方法一/三此前用固定延时 + 单次
        读数，与方法二判据不一致。这里统一用 `_read_meas_stable`（间隔 0.3 s、
        相对差 ≤0.05%、最长 4 s），并把等待时间写入记录。
        """
        value, _spread, waited = self._read_meas_stable(
            "meas_mean",
            tolerance=0.0005,
            interval=0.3,
            max_wait=4.0,
            trigger=False,
        )
        return value, waited

    def _set_dc(self, volts: float) -> None:
        """输出带符号的直流电平。

        实机教训：早前用 abs() 取绝对值导致负电平被当作正电平输出，方法一/三的
        读数不随输入变化（G≈0、截距≈恒定值）。
        """
        self._write_calibrator("set_shap", "DC")
        self._write_calibrator("set_volt", volts)
        self._write_calibrator("set_output", "ON")
        time.sleep(0.3)  # 函数切换的建立时间由随后的读数收敛判据兜底

    def _method_one(
        self, scale: float, vertical_div: float
    ) -> tuple[float | None, float | None, float]:
        """方法一：屏幕 90% / 10% 两个直流点的增益。"""
        span = scale * vertical_div
        level_high = (POSITION_HIGH - 0.5) * span
        level_low = (POSITION_LOW - 0.5) * span

        self.setup_measurement("meas_mean")
        self._set_dc(level_high)
        read_high, wait_high = self._read_mean()
        self._set_dc(level_low)
        read_low, wait_low = self._read_mean()

        if level_high == level_low:
            return None, None, wait_high + wait_low
        gain = (read_high - read_low) / (level_high - level_low)
        return gain, 100.0 * (gain - 1.0), wait_high + wait_low

    def _method_two(self, std_value: float) -> tuple[float, float, float, float]:
        """方法二：方波幅度法。

        切换函数后幅度需要秒级建立，这里用"读数收敛"代替固定延时：
        返回 (增益, 误差%, 已等待秒数, 两次读数相对差%)。
        """
        self.setup_measurement("meas_amp")
        self._write_calibrator("set_shap", "SQU")
        # 必须是双极性对称波：单极性（0~V）时波形顶部会超出屏幕被削顶
        self._write_calibrator("set_squ_polarity", "SYMM")
        self._write_calibrator("set_freq", 1000.0)
        self._write_calibrator("set_volt", std_value)
        self._write_calibrator("set_output", "ON")
        measured, spread_pct, waited = self._read_meas_stable("meas_amp")
        measured *= self._get_meas_amp_scale()
        gain = measured / std_value if std_value else float("nan")
        return gain, 100.0 * (gain - 1.0), waited, spread_pct

    def _method_three(self, scale: float, vertical_div: float) -> tuple[float | None, float | None]:
        """方法三：量程内 m 点最小二乘，返回 (G, 截距 d, 累计等待秒数)。"""
        span = scale * vertical_div
        low_limit = -span / 2.0
        high_limit = span / 2.0
        step = abs(high_limit - low_limit) / SWEEP_POINTS

        self.setup_measurement("meas_mean")
        inputs: list[float] = []
        readings: list[float] = []
        settle = 0.0
        for index in range(SWEEP_POINTS):
            level = low_limit + (index + 0.5) * step
            self._set_dc(level)
            value, waited = self._read_mean()
            inputs.append(level)
            readings.append(value)
            settle += waited

        count = len(inputs)
        if count < 2:
            return None, None, settle
        mean_x = sum(inputs) / count
        mean_y = sum(readings) / count
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(inputs, readings, strict=True))
        denominator = sum((x - mean_x) ** 2 for x in inputs)
        if denominator == 0:
            return None, None, settle
        gain = numerator / denominator
        intercept = mean_y - gain * mean_x
        return gain, intercept, settle

    def _measure_point(self, point: dict) -> dict:
        scale = float(point["scale"])
        impedance = point.get("impedance", "1M")
        std_value = float(point["std_value_vpp"])
        vertical_div = float(self.profile.get("vertical_div", 8))

        self._apply_impedance(impedance)
        self._write_osc("set_vertical_scale", self.channel, scale)
        self._zero_position()

        # 方法二放在最前：它依赖校准仪的方波状态最"干净"。实机发现若先跑直流类
        # 方法（一/三），随后的方波幅度读数会系统性偏高 1.9%~5.0%（且正好是
        # 0.625% 的整数倍，属量化台阶上的偏差）。
        gain2, error2, settle_s, spread2 = self._method_two(std_value)
        gain1, error1, settle_m1 = self._method_one(scale, vertical_div)
        gain3, intercept3, settle_m3 = self._method_three(scale, vertical_div)

        return {
            "channel": self.channel,
            "impedance": impedance,
            "scale": scale,
            "std_value_vpp": std_value,
            "measured_vpp": gain2 * std_value,
            "gain": gain2,
            "error_pct": error2,
            "gain_m1": gain1,
            "error_m1_pct": error1,
            "gain_m3": gain3,
            "error_m3_pct": None if gain3 is None else 100.0 * (gain3 - 1.0),
            "intercept_m3_v": intercept3,
            "settle_s_m1": settle_m1,
            "settle_s_m2": settle_s,
            "settle_s_m3": settle_m3,
            "read_spread_m2_pct": spread2,
        }

    @ensure_output_off
    def run(self):
        self.print_title(self.title)
        self.init_devices()
        self.setup_channel()
        self.setup_measurement("meas_amp")

        if not self.points:
            console.print("[yellow]⚠ 本轮没有可执行的校准点[/yellow]")
            return

        table = self.make_table(
            "直流增益校准结果",
            [
                {"name": "序号"},
                {"name": "通道", "justify": "center"},
                {"name": "阻抗", "justify": "center"},
                {"name": "挡位(V/div)"},
                {"name": "方法一 G"},
                {"name": "误差1(%)"},
                {"name": "方法二 G"},
                {"name": "误差2(%)"},
                {"name": "方法三 G"},
                {"name": "误差3(%)"},
                {"name": "截距 d(V)"},
            ],
        )

        with Progress() as progress:
            task = progress.add_task("直流增益", total=len(self.points))
            for index, point in enumerate(self.points, start=1):
                record = self._measure_point(point)
                self.results.append({"index": index, **record})
                self.add_result_row(
                    table,
                    [
                        index,
                        f"CH{self.channel}",
                        "1 MΩ" if record["impedance"] == "1M" else "50 Ω",
                        f"{record['scale']:g}",
                        self._fmt(record["gain_m1"], 4),
                        self._fmt(record["error_m1_pct"], 3),
                        self._fmt(record["gain"], 4),
                        self._fmt(record["error_pct"], 3),
                        self._fmt(record["gain_m3"], 4),
                        self._fmt(record["error_m3_pct"], 3),
                        self._fmt(record["intercept_m3_v"], 5),
                    ],
                )
                progress.update(task, advance=1)
        console.print(table)

    @staticmethod
    def _fmt(value, digits: int) -> str:
        if value is None:
            return "—"
        return f"{value:.{digits}f}"
