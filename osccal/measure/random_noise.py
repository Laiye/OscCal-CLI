"""随机噪声（JJF 1057-2026 7.13）。

规范条件：通道输入端连接**匹配负载**、置最小量程、非自动量程、直流耦合、
偏置为零、实时采样且采样速率最高。方法一读幅度有效值；方法二采集数据求标准差。

本实现采用方法二（读回波形后求标准差）：不依赖示波器是否有 RMS 测量项，
且标准差是噪声的直接估计。阅读负载是**人工动作**，程序在此处暂停等待确认，
确认后才继续——不静默跳过。
"""

import math
import time

import click
from rich.progress import Progress

from osccal.measure.base import BaseCalibrator, console, ensure_output_off

#: 噪声统计使用的采样点数。
SAMPLES = 1000


class RandomNoiseCalibrator(BaseCalibrator):
    """随机噪声：接匹配负载后按波形标准差评定。"""

    title = "随机噪声（7.13）"

    @staticmethod
    def _wait_for_load(channel: str) -> None:
        """规范要求输入端接匹配负载，程序无法代劳，必须人工确认。"""
        console.print(
            f"\n[yellow]请将 CH{channel} 输入端接入 50 Ω 匹配负载"
            f"（并断开校准仪输出），确认后继续[/yellow]"
        )
        click.prompt("  接好负载后按回车继续", default="", show_default=False)

    @staticmethod
    def standard_deviation(values: list[float]) -> float:
        """样本标准差（分母 n−1）。"""
        count = len(values)
        if count < 2:
            raise ValueError("样本点不足，无法计算标准差")
        mean = sum(values) / count
        variance = sum((value - mean) ** 2 for value in values) / (count - 1)
        return math.sqrt(variance)

    def _measure_point(self, point: dict) -> dict:
        scale = float(point["vertical_scale"])
        vertical_div = float(self.profile.get("vertical_div", 8))
        full_scale = scale * vertical_div

        self._write_calibrator("set_output", "OFF")
        self._write_osc("set_vertical_scale", self.channel, scale)
        self._write_osc("set_coupling", self.channel, "DC")
        # 规范要求"采样速率最高"：压到机型最快的水平档位
        scales = self.profile.get("horizontal_scales") or [1e-9]
        self._set_timebase(min(scales))
        if "set_vertical_position" in self.cmd_osc["actions"]:
            self._write_osc("set_vertical_position", self.channel, 0.0)
        if "set_acquisition_mode" in self.cmd_osc["actions"]:
            self._write_osc(
                "set_acquisition_mode", self.cmd_osc["keyword"]["acquisition_mode_sample"]
            )
        if "set_acquire_stop_after" in self.cmd_osc["actions"]:
            self._write_osc(
                "set_acquire_stop_after", self.cmd_osc["keyword"]["acquire_stop_after_single"]
            )
        time.sleep(1.0)

        wave = self._read_waveform(SAMPLES)
        noise_v = self.standard_deviation(wave.volts)
        return {
            "channel": self.channel,
            "vertical_scale": scale,
            "full_scale_v": full_scale,
            "samples": wave.samples,
            "noise_v": noise_v,
            "error_pct": 100.0 * noise_v / full_scale if full_scale else float("nan"),
        }

    @ensure_output_off
    def run(self):
        self.print_title(self.title)
        self.init_devices()
        self.setup_channel()

        if not self.points:
            console.print("[yellow]⚠ 本轮没有可执行的校准点[/yellow]")
            return

        self._wait_for_load(self.channel)

        table = self.make_table(
            "随机噪声校准结果",
            [
                {"name": "序号"},
                {"name": "通道", "justify": "center"},
                {"name": "挡位(V/div)"},
                {"name": "满量程(V)"},
                {"name": "样本数", "justify": "center"},
                {"name": "噪声(标准差, V)"},
                {"name": "占满量程(%)"},
            ],
        )

        with Progress() as progress:
            task = progress.add_task("随机噪声", total=len(self.points))
            for index, point in enumerate(self.points, start=1):
                record = self._measure_point(point)
                self.results.append({"index": index, **record})
                self.add_result_row(
                    table,
                    [
                        index,
                        f"CH{self.channel}",
                        f"{record['vertical_scale']:g}",
                        f"{record['full_scale_v']:.6g}",
                        record["samples"],
                        f"{record['noise_v']:.6g}",
                        f"{record['error_pct']:.4f}",
                    ],
                )
                progress.update(task, advance=1)
        console.print(table)
