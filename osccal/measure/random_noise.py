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


def _parse_scalar(raw) -> float:
    """从 `:HOR:SAMPLER 2.5000E+9` 这类带助记符的响应里取出数值。"""
    for token in reversed(str(raw).replace("\n", " ").split()):
        try:
            return float(token)
        except ValueError:
            continue
    raise ValueError(f"无法解析数值: {raw!r}")


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

    def _timebase_for_max_sample_rate(self) -> float:
        """反算让示波器跑到最高采样率的水平挡位。

        记录长度 R 点、水平 H 格、目标采样率 f_max：时基 = R / f_max / H。
        结果吸附到机型实际支持的挡位（取不大于计算值的最近档位）。
        """
        horizontal_div = float(self.profile.get("horizontal_div", 10))
        max_sample_rate = float(self.profile.get("max_sample_rate_hz", 0) or 0)
        scales = sorted(self.profile.get("horizontal_scales") or [1e-9])
        if max_sample_rate <= 0 or "query_record_length" not in self.cmd_osc.get("actions", {}):
            return min(scales)
        try:
            record_length = float(_parse_scalar(str(self._query_osc("query_record_length"))))
        except Exception:  # noqa: BLE001 - 读不到就退回最快档
            return min(scales)
        if record_length <= 0:
            return min(scales)
        target = record_length / max_sample_rate / horizontal_div
        candidates = [scale for scale in scales if scale <= target]
        return max(candidates) if candidates else min(scales)

    def _read_sample_rate(self) -> float:
        if "query_sample_rate" not in self.cmd_osc.get("actions", {}):
            return 0.0
        try:
            return float(_parse_scalar(str(self._query_osc("query_sample_rate"))))
        except Exception:  # noqa: BLE001 - 读不到采样率不影响噪声统计
            return 0.0

    def _measure_point(self, point: dict) -> dict:
        scale = float(point["vertical_scale"])
        vertical_div = float(self.profile.get("vertical_div", 8))
        full_scale = scale * vertical_div
        max_sample_rate = float(self.profile.get("max_sample_rate_hz", 0) or 0)

        self._write_calibrator("set_output", "OFF")
        self._write_osc("set_vertical_scale", self.channel, scale)
        self._write_osc("set_coupling", self.channel, "DC")
        # 规范 7.13 要求"采样速率最高"。不能简单压到最快时基：记录长度固定时，
        # 时基太快会让记录只覆盖极短时间、示波器仍按较低速率采样。正确做法是按
        # "记录长度 ÷ 最大采样率 ÷ 水平格数"反算时基，再回读采样率做校验。
        timebase = self._timebase_for_max_sample_rate()
        self._set_timebase(timebase)
        sample_rate = self._read_sample_rate()
        if max_sample_rate > 0 and sample_rate < 0.9 * max_sample_rate:
            console.print(
                f"[yellow]⚠ 采样率 {sample_rate / 1e6:.3g} MS/s 低于机型上限 "
                f"{max_sample_rate / 1e6:.3g} MS/s（时基 {timebase:g} s/div）[/yellow]"
            )
        if "set_vertical_position" in self.cmd_osc["actions"]:
            self._write_osc("set_vertical_position", self.channel, 0.0)
        if "set_acquisition_mode" in self.cmd_osc["actions"]:
            self._write_osc(
                "set_acquisition_mode", self.cmd_osc["keyword"]["acquisition_mode_sample"]
            )
        # 噪声测量时校准仪输出是关的、信号为平直基线，边沿触发可能永远等不到
        # 触发点。这里让示波器自由连续运行，等基线稳定后直接取当前记录，
        # 不走"单次采集 + 等触发"（否则会拿到空白记录，噪声恒为 0）。
        if "set_acquire_stop_after" in self.cmd_osc["actions"]:
            self._write_osc(
                "set_acquire_stop_after",
                self.cmd_osc["keyword"].get("acquire_stop_after_run_stop", "RUNSTop"),
            )
        if "set_acquire_state" in self.cmd_osc["actions"]:
            self._write_osc("set_acquire_state", self.cmd_osc["keyword"]["acquire_state_run"])
        time.sleep(1.0)

        wave = self._read_waveform(SAMPLES, fresh=False)
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
