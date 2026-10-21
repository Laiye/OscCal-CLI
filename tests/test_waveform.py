"""波形读回解析（core/waveform.py）与泰克指令集波形能力声明的守护用例。"""

import json
import math
import struct
from pathlib import Path

import pytest

from osccal.core.waveform import (
    WaveformError,
    WaveformPreamble,
    build_waveform,
    codes_to_volts,
    decode_ascii_codes,
    decode_codes,
    parse_block,
    parse_preamble,
    time_axis,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _block(payload: bytes) -> bytes:
    """构造 IEEE 488.2 定长块（长度位数取实际位数）。"""
    digits = str(len(payload))
    return b"#" + str(len(digits)).encode() + digits.encode() + payload


class TestParseBlock:
    def test_definite_length(self):
        payload = bytes(range(8))
        assert parse_block(_block(payload)) == payload

    def test_long_block(self):
        payload = b"\x01\x02" * 1000
        assert parse_block(_block(payload)) == payload

    def test_indefinite_block(self):
        assert parse_block(b"#031\r\n") == b"31"

    def test_skips_leading_noise(self):
        assert parse_block(b"\r\n" + _block(b"abcd")) == b"abcd"

    def test_missing_header(self):
        with pytest.raises(WaveformError, match="块头"):
            parse_block(b"no header here")

    def test_truncated_body(self):
        with pytest.raises(WaveformError, match="长度不符"):
            parse_block(b"#510000abcd")

    def test_rejects_non_bytes(self):
        with pytest.raises(WaveformError):
            parse_block("text")  # type: ignore[arg-type]


class TestDecodeCodes:
    def test_signed_1_byte(self):
        preamble = WaveformPreamble(byt_nr=1, encoding="RIBinary")
        body = struct.pack("3b", -128, 0, 127)
        assert decode_codes(body, preamble) == [-128, 0, 127]

    def test_unsigned_1_byte(self):
        preamble = WaveformPreamble(byt_nr=1, encoding="RPBinary")
        body = struct.pack("3B", 0, 127, 255)
        assert decode_codes(body, preamble) == [0, 127, 255]

    def test_signed_2_byte_msb_first(self):
        preamble = WaveformPreamble(byt_nr=2, encoding="RIBinary", byte_order="MSB")
        body = struct.pack(">2h", -32768, 12345)
        assert decode_codes(body, preamble) == [-32768, 12345]

    def test_signed_2_byte_lsb_first(self):
        preamble = WaveformPreamble(byt_nr=2, encoding="RIBinary", byte_order="LSB")
        body = struct.pack("<2h", -1, 1000)
        assert decode_codes(body, preamble) == [-1, 1000]

    def test_rejects_partial_sample(self):
        preamble = WaveformPreamble(byt_nr=2)
        with pytest.raises(WaveformError, match="整数倍"):
            decode_codes(b"\x01\x02\x03", preamble)

    def test_rejects_unsupported_width(self):
        with pytest.raises(WaveformError, match="字节数"):
            decode_codes(b"\x01", WaveformPreamble(byt_nr=3))


class TestScaling:
    def test_volts_follow_manual_formula(self):
        preamble = WaveformPreamble(y_mult=0.04, y_off=50.0, y_zero=0.1)
        volts = codes_to_volts([0, 50, 100], preamble)
        assert volts == pytest.approx([-1.9, 0.1, 2.1])

    def test_time_axis(self):
        preamble = WaveformPreamble(x_increment=1e-9, x_zero=-1e-7)
        assert time_axis(preamble, 3) == pytest.approx([-1e-7, -1e-7 + 1e-9, -1e-7 + 2e-9])

    def test_levels_per_div(self):
        assert WaveformPreamble(byt_nr=1).levels_per_div == 25
        assert WaveformPreamble(byt_nr=2).levels_per_div == 6400


class TestParsePreamble:
    def test_typical_response(self):
        text = (
            "WFMOutpre:BYT_Nr 2;BIT_Nr 16;ENCDG BINARY;BN_FMT RI;BYT_OR MSB;"
            "NR_Pt 1000;PT_FMT Y;YMUlt 40.0000E-3;YOFf 0.0000E+0;YZEro 0.0;"
            'XINcr 200.0000E-12;XZEro -1.0E-7;YUNit "V"'
        )
        preamble = parse_preamble(text)
        assert preamble.byt_nr == 2
        assert preamble.nr_pt == 1000
        assert preamble.y_mult == pytest.approx(0.04)
        assert preamble.encoding == "BINARY"
        assert preamble.byte_order == "MSB"
        assert preamble.pt_fmt == "Y"
        assert preamble.y_unit == "V"
        assert preamble.x_increment == pytest.approx(200e-12)

    def test_ignores_garbage_tokens(self):
        preamble = parse_preamble(";;;bad token;NR_Pt notanumber;XINcr 1e-9")
        assert preamble.nr_pt == 0
        assert preamble.x_increment == pytest.approx(1e-9)

    def test_parses_abbreviated_tek_response(self):
        """MDO3052 实机返回的是缩写助记符，必须能正确解析（否则换算系数退化为 1）。"""
        text = (
            ":WFMO:BYT_N 2;BIT_N 16;ENC BIN;BN_F RI;BYT_O MSB;"
            'WFI "Ch1, DC coupling, 100.0mV/div, 10.00ms/div, 10000 points, Sample mode";'
            'NR_P 1000;PT_F Y;PT_OR LINEA;XUN "s";XIN 10.0000E-6;XZE -50.0000E-3;PT_O 0;'
            'YUN "V";YMU 15.6250E-6;YOF 0.0E+0;YZE 0.0E+0;DOM TIM;WFMTYP ANALOG'
        )
        preamble = parse_preamble(text)
        assert preamble.byt_nr == 2
        assert preamble.bit_nr == 16
        assert preamble.nr_pt == 1000
        assert preamble.y_mult == pytest.approx(15.625e-6)
        assert preamble.x_increment == pytest.approx(10e-6)
        assert preamble.x_zero == pytest.approx(-50e-3)
        assert preamble.encoding == "BIN"
        assert preamble.byte_order == "MSB"
        assert preamble.pt_fmt == "Y"
        assert preamble.y_unit == "V"


class TestBuildWaveform:
    def _preamble(self, nr_pt: int) -> WaveformPreamble:
        return WaveformPreamble(
            y_mult=0.04,
            y_off=0.0,
            y_zero=0.0,
            x_increment=1e-9,
            x_zero=0.0,
            nr_pt=nr_pt,
            byt_nr=2,
            encoding="RIBinary",
            byte_order="MSB",
        )

    def test_binary_round_trip(self):
        codes = [0, 25, 50, -25]
        body = struct.pack(">4h", *codes)
        wave = build_waveform(body, self._preamble(4))
        assert wave.codes == codes
        assert wave.volts == pytest.approx([c * 0.04 for c in codes])
        assert wave.samples == 4

    def test_ascii_round_trip(self):
        body = b"0,25,50,-25\n"
        wave = build_waveform(body, self._preamble(4), ascii_encoding=True)
        assert wave.codes == [0, 25, 50, -25]

    def test_rejects_env_format(self):
        preamble = self._preamble(4)
        preamble.pt_fmt = "ENV"
        with pytest.raises(WaveformError, match="包络"):
            build_waveform(struct.pack(">4h", 0, 1, 2, 3), preamble)

    def test_rejects_point_count_mismatch(self):
        with pytest.raises(WaveformError, match="点数不符"):
            build_waveform(struct.pack(">2h", 0, 1), self._preamble(4))

    def test_rejects_empty(self):
        with pytest.raises(WaveformError, match="为空"):
            build_waveform(b"", self._preamble(0))

    def test_ascii_decoding_rejects_text(self):
        with pytest.raises(WaveformError, match="ASCII"):
            decode_ascii_codes(b"1,2,oops")


@pytest.fixture(scope="module")
def mdo_commands() -> dict:
    with open(PROJECT_ROOT / "commands" / "tektronix_mdo.json", encoding="utf-8") as f:
        return json.load(f)


class TestCommandSetDeclaration:
    def test_waveform_capability_declared(self, mdo_commands):
        caps = mdo_commands["capabilities"]
        assert caps["waveform_readback"] is True
        assert caps["waveform_verified"] is False, "实机验证前不得声称已验证"

    @pytest.mark.parametrize(
        "action",
        [
            "set_wave_source",
            "set_wave_encoding",
            "set_wave_width",
            "set_wave_start",
            "set_wave_stop",
            "query_wave_preamble",
            "query_wave_data",
        ],
    )
    def test_waveform_actions_declared(self, mdo_commands, action):
        assert action in mdo_commands["actions"]

    def test_queries_are_query_type(self, mdo_commands):
        for name in ("query_wave_preamble", "query_wave_data"):
            assert mdo_commands["actions"][name]["type"] == "query"
            assert mdo_commands["actions"][name]["commands_num"] == 1

    def test_only_mdo_declares_waveform(self):
        """其余指令集未声明波形能力，视为 unverified。"""
        declared = []
        for path in sorted((PROJECT_ROOT / "commands").glob("*.json")):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            caps = data.get("capabilities") or {}
            if caps.get("waveform_readback"):
                declared.append(path.name)
        assert declared == ["tektronix_mdo.json"]


def test_scaling_matches_documented_levels():
    """1 V/div、1 字节数据 → YMUlt 应为 40 mV/级（手册示例）。"""
    levels = WaveformPreamble(byt_nr=1).levels_per_div
    assert math.isclose(1.0 / levels, 0.04)
