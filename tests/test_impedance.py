"""阻抗设置与回读校验的回归用例（P0）。

覆盖：
- `_apply_impedance` 必须调用 `_verify_impedance`（此前回读校验是死代码）；
- 示波器阻抗查询按接口声明的参数个数带通道号（MDO 为 CH<x>:IMPedance?）；
- 回读响应可能是文本（MEG/FIF）或数值（50/10000/1E+6），都要能判断；
- 指令集里的 query_impedance 必须带通道参数。
"""

import json
from pathlib import Path

from osccal.core.command import assemble_cmd
from osccal.measure.base import BaseCalibrator

ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str) -> dict:
    with open(ROOT / relative, encoding="utf-8") as handle:
        return json.load(handle)


class StubInstrument:
    def __init__(self):
        self.written: list[str] = []

    def write(self, cmd: str):
        self.written.append(cmd)

    def query(self, cmd: str) -> str:
        self.written.append(cmd)
        return ""


def _calibrator(channel: str = "2") -> BaseCalibrator:
    return BaseCalibrator(
        StubInstrument(),
        StubInstrument(),
        _load("commands/tektronix_mdo.json"),
        _load("calibrators/fluke_9500b.json"),
        _load("characteristics/tektronix_mdo3052.json"),
        channel,
        "9530",
    )


class TestApplyImpedanceVerifies:
    def test_apply_impedance_verifies_readback(self):
        calibrator = _calibrator()
        calls: list[str] = []
        calibrator._verify_impedance = lambda label: calls.append(label)

        calibrator._apply_impedance("50")

        assert calls == ["50"], "设置阻抗后必须回读校验（否则接错也不会发现）"

    def test_scope_query_carries_channel(self):
        calibrator = _calibrator("2")
        calls: list[tuple] = []

        def query(action, *args):
            calls.append((action, args))
            return "MEG"

        calibrator._query_osc = query
        calibrator._query_calibrator = lambda action, *args: "10000"

        calibrator._verify_impedance("1M")

        assert calls == [("query_impedance", ("2",))], "回读必须针对当前通道，不能写死 CH1"


class TestImpedanceParsing:
    def test_text_and_numeric_responses(self):
        parse = BaseCalibrator._impedance_is_high
        assert parse("MEG\n") is True
        assert parse(":CH1:IMPEDANCE FIFty") is False
        assert parse("1.0E+6") is True
        assert parse("10000") is True
        assert parse("50") is False
        assert parse("?") is None


class TestMdoCommandSet:
    def test_query_impedance_is_channel_aware(self):
        action = _load("commands/tektronix_mdo.json")["actions"]["query_impedance"]
        assert action["args_num"] == 1
        assert assemble_cmd(action, "2") == "CH2:TERmination?"
