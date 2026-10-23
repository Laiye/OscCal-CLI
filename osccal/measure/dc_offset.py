"""直流偏置（JJF 1057-2026 7.5.2 方法二）。

实机结论：示波器的"电压平均值"测量**已对偏置做过补偿**，直接用 MEAN 读数无法
反映偏置误差（实测偏置 0 V 与 0.2 V 时拟合截距都是约 3 mV）。规范 7.5.2 要求
"按 7.4.3 操作"——取的是**直流波形采样数据** y_ij，即未经偏置补偿的原始码值：

    v_raw = (码值 − YOFf) × YMUlt        （不叠加 YZEro，它是示波器的补偿项）

于是 v_raw ≈ E − d₀ − ε，线性拟合截距 b = −(d₀ + ε)，从而

    d_c = −b = d₀ + ε         偏置示值
    Δd  = d_c − d₀ = ε        偏置误差（式 9）
    G_d = d_c / d₀            偏置增益（式 10，d₀ ≠ 0 时）

本实现：先在 d₀ = 0 下扫一遍得到零点误差，再在 d₀ = 2 格下扫一遍得到偏置示值。
"""

import time

from rich.progress import Progress

from osccal.measure.base import BaseCalibrator, console, ensure_output_off

#: 偏置设定值：2 格。
OFFSET_DIV = 2.0
#: 扫描范围：±2 格，保证 d₀ 与 E 叠加后仍在屏内。
SWEEP_HALF_DIV = 2.0
#: 扫描点数（规范取 m = 16）。
SWEEP_POINTS = 16
#: 每个电平的采集点数（规范要求 n ≥ 1000）。
SWEEP_SAMPLES = 1000
#: 每个电平的建立时间。
SETTLE_SECONDS = 0.6
#: 零点插值用的小电平（校准仪 1 MΩ 下的最小有效幅度约 1 mV）。
ZERO_PROBE_V = 0.001


class DcOffsetCalibrator(BaseCalibrator):
    """直流偏置：按 7.5.2（原始采样值 + 线性拟合）评定零点与偏置误差。"""

    title = "直流偏置（7.5.2 方法二）"

    def _set_offset(self, volts: float) -> None:
        if "set_offset" in self.cmd_osc.get("actions", {}):
            self._write_osc("set_offset", self.channel, volts)
            time.sleep(0.3)

    def _read_mean(self) -> float:
        """自由运行下读电压平均值（直流信号没有触发沿）。"""
        self._ensure_free_running(0.3)
        # 读数必须等收敛：从上一个偏置电平切回 0 V 时若立即读数，会读到尚未建立的
        # 残留（实测零点读数恒为满量程的约 23%，即上一点 d0=2 格的残留）。
        return self._read_meas_stable("meas_mean", trigger=False)[0]

    def _method_one(self, scale: float) -> tuple[float, float, float, float]:
        """7.5.1 方法一：零点读数 + 偏置示值（同号激励）。

        规范原文写"激励电压幅度为 −d₀"，但示波器的偏置是抵消输入用的：输入 +d₀、
        偏置 d₀ 时波形才居中；用 −d₀ 会把波形推出约两倍偏置量，无法读数。
        故按实机的正确做法取**同号**激励，并在记录中写明该偏离。
        """
        offset_nominal = OFFSET_DIV * scale
        self.setup_measurement("meas_mean")
        self._write_calibrator("set_shap", "DC")

        # 零点：偏置 0。校准仪输出不了 0 V（实测设 0 V 与 0.5 mV 都被静默丢弃、
        # 保持原值），因此用 ±ZERO_PROBE_V 两点插值到 0 V 处。
        self._set_offset(0.0)
        self._write_calibrator("set_output", "ON")
        readings = []
        for level in (ZERO_PROBE_V, -ZERO_PROBE_V):
            self._write_calibrator("set_volt", level)
            time.sleep(SETTLE_SECONDS)
            readings.append(self._read_mean())
        zero_reading = (readings[0] + readings[1]) / 2.0

        # 偏置 d₀ + 同号激励 d₀ → 波形居中，读数为偏置示值
        self._set_offset(offset_nominal)
        self._write_calibrator("set_volt", offset_nominal)
        time.sleep(SETTLE_SECONDS)
        offset_reading = self._read_mean()

        error = offset_reading - offset_nominal
        gain = offset_reading / offset_nominal if offset_nominal else float("nan")
        return zero_reading, offset_reading, error, gain

    def _raw_mean(self) -> float:
        """读回波形并求原始码值的均值（不叠加偏置补偿项 YZEro）。"""
        # 直流信号没有边沿，不能走"单次采集等触发"（每次会白等 5 s 超时）
        self._ensure_free_running(0.3)
        wave = self._read_waveform(SWEEP_SAMPLES, fresh=False)
        preamble = wave.preamble
        values = [(code - preamble.y_off) * preamble.y_mult for code in wave.codes]
        return sum(values) / len(values)

    def _sweep(self, scale: float) -> tuple[float, float]:
        """在给定量程内扫 16 个直流电平，返回 (斜率 G, 截距 b)。"""
        half = SWEEP_HALF_DIV * scale
        step = 2.0 * half / SWEEP_POINTS
        self.setup_measurement("meas_mean")

        inputs: list[float] = []
        readings: list[float] = []
        for index in range(SWEEP_POINTS):
            level = -half + (index + 0.5) * step
            self._write_calibrator("set_shap", "DC")
            self._write_calibrator("set_volt", level)
            self._write_calibrator("set_output", "ON")
            time.sleep(SETTLE_SECONDS)
            inputs.append(level)
            readings.append(self._raw_mean())

        count = len(inputs)
        mean_x = sum(inputs) / count
        mean_y = sum(readings) / count
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(inputs, readings, strict=True))
        denominator = sum((x - mean_x) ** 2 for x in inputs)
        gain = numerator / denominator if denominator else float("nan")
        intercept = mean_y - gain * mean_x
        return gain, intercept

    def _measure_point(self, point: dict) -> dict:
        scale = float(point["scale"])
        impedance = point.get("impedance", "1M")
        vertical_div = float(self.profile.get("vertical_div", 8))
        full_scale = scale * vertical_div
        offset_nominal = OFFSET_DIV * scale

        self._apply_impedance(impedance)
        self._write_osc("set_vertical_scale", self.channel, scale)
        self._write_osc("set_coupling", self.channel, "DC")
        self._set_timebase(1e-3)
        if "set_vertical_position" in self.cmd_osc.get("actions", {}):
            self._write_osc("set_vertical_position", self.channel, 0.0)
        if "set_record_length" in self.cmd_osc.get("actions", {}):
            self._write_osc("set_record_length", SWEEP_SAMPLES)

        # 零点：d₀ = 0 时原始码值拟合出的截距即零点误差
        self._set_offset(0.0)
        gain_zero, intercept_zero = self._sweep(scale)
        zero_reading = -intercept_zero

        # 偏置：d₀ ≠ 0 时截距 = −(d₀ + ε)
        self._set_offset(offset_nominal)
        gain_offset, intercept_offset = self._sweep(scale)
        offset_measured = -intercept_offset
        offset_error = offset_measured - offset_nominal
        gain_d = offset_measured / offset_nominal if offset_nominal else float("nan")

        zero_m1, measured_m1, error_m1, gain_m1 = self._method_one(scale)

        return {
            "channel": self.channel,
            "impedance": impedance,
            "scale": scale,
            "full_scale_v": full_scale,
            "zero_reading_v": zero_reading,
            "offset_nominal_v": offset_nominal,
            "offset_measured_v": offset_measured,
            "offset_error_v": offset_error,
            "error_pct": 100.0 * offset_error / full_scale if full_scale else float("nan"),
            "gain": gain_d,
            "dc_gain_zero": gain_zero,
            "dc_gain_offset": gain_offset,
            "zero_reading_v_m1": zero_m1,
            "offset_nominal_v_m1": OFFSET_DIV * scale,
            "offset_measured_v_m1_raw": measured_m1,
            "offset_measured_v_m1": measured_m1,
            "offset_error_v_m1": error_m1,
            "error_m1_pct": 100.0 * error_m1 / full_scale if full_scale else float("nan"),
            "gain_m1": gain_m1,
            "method1_note": "激励取同号 d0（规范原文为 -d0，实际会把波形推出屏幕）",
        }

    @ensure_output_off
    def run(self):
        self.print_title(self.title)
        self.init_devices()
        self.setup_channel()
        self.setup_measurement("meas_mean")

        if not self.points:
            console.print("[yellow]⚠ 本轮没有可执行的校准点[/yellow]")
            return

        table = self.make_table(
            "直流偏置校准结果",
            [
                {"name": "序号"},
                {"name": "通道", "justify": "center"},
                {"name": "阻抗", "justify": "center"},
                {"name": "挡位(V/div)"},
                {"name": "零点(mV)"},
                {"name": "d₀(V)"},
                {"name": "d_r(V)"},
                {"name": "方法一 Δd(mV)"},
                {"name": "方法一 G"},
                {"name": "d_c(V)"},
                {"name": "方法二 Δd(mV)"},
                {"name": "方法二 G"},
            ],
        )

        with Progress() as progress:
            task = progress.add_task("直流偏置", total=len(self.points))
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
                        f"{record['zero_reading_v_m1'] * 1e3:+.2f}",
                        f"{record['offset_nominal_v_m1']:.4g}",
                        f"{record['offset_measured_v_m1_raw']:.5f}",
                        f"{record['offset_error_v_m1'] * 1e3:+.2f}",
                        f"{record['gain_m1']:.4f}",
                        f"{record['offset_measured_v']:.5f}",
                        f"{record['offset_error_v'] * 1e3:+.2f}",
                        f"{record['gain']:.4f}",
                    ],
                )
                progress.update(task, advance=1)
        console.print(table)
