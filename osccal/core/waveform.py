"""示波器波形读回：IEEE 488.2 定长块解析 + 前导信息换算。

波形数据**直接走现有的 VISA 连接读取**，不需要 U 盘或文件导出。泰克 MDO3000
（以及 MDO4000/MSO/DPO4000B）的读回流程见编程手册 077-0510-08：

    DATa:SOUrce CH1        # 选数据源（该波形必须处于开启状态）
    DATa:ENCdg RIBinary    # 编码：ASCii / RIBinary / RPBinary / FAStest ...
    DATa:WIDth 2           # 每点字节数 1 或 2
    DATa:STARt 1 / DATa:STOP 1000
    WFMOutpre?             # 取换算系数与点数
    CURVe?                 # 取数据（定长二进制块）

电压换算（手册原文，dl = digitizing level）：

    V = (code - YOFf) * YMUlt + YZEro

1 字节数据每垂直格 25 个数字化级、2 字节每格 6400 级；RIBINARY 以屏幕中心为 0。

本模块只做"字节 → 码值 → 物理量"的解析，不发送任何 SCPI —— 让它可以完全离线
用构造数据测试；I/O 由测量层负责。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

# 每垂直格对应的数字化级数（手册 WFMInpre:YOFf 条目）。
DIGITIZING_LEVELS_PER_DIV = {1: 25, 2: 6400}


class WaveformError(RuntimeError):
    """波形数据块的格式或长度不符合 IEEE 488.2 定长块约定。"""


@dataclass
class WaveformPreamble:
    """`WFMOutpre?` 的换算参数。"""

    y_mult: float = 1.0
    y_off: float = 0.0
    y_zero: float = 0.0
    x_increment: float = 0.0
    x_zero: float = 0.0
    y_unit: str = "V"
    nr_pt: int = 0
    byt_nr: int = 2
    bit_nr: int = 16
    encoding: str = "RIBinary"
    byte_order: str = "MSB"
    pt_fmt: str = "Y"
    bn_fmt: str = ""

    @property
    def levels_per_div(self) -> int | None:
        return DIGITIZING_LEVELS_PER_DIV.get(self.byt_nr)

    @property
    def signed(self) -> bool:
        """是否按有符号解码：以 BN_Fmt（RI/RP）为准，回退看编码名。"""
        fmt = (self.bn_fmt or "").upper()
        if fmt.startswith("RI"):
            return True
        if fmt.startswith("RP"):
            return False
        return "RI" in self.encoding.upper()

    @property
    def big_endian(self) -> bool:
        return self.byte_order.upper().startswith("MSB")


@dataclass
class Waveform:
    """一次读回的波形：原始码值 + 电压 + 时间轴。"""

    codes: list[int]
    volts: list[float]
    seconds: list[float]
    preamble: WaveformPreamble
    extra: dict = field(default_factory=dict)

    @property
    def samples(self) -> int:
        return len(self.codes)


def parse_block(raw: bytes) -> bytes:
    """解析 IEEE 488.2 定长块，返回块内的数据部分。

    支持 `#<n><n 位长度><数据>` 与 `#0<数据><换行>`（不定长）两种形式。
    块前的任何杂质（如回显或多行响应）都会跳过。
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise WaveformError("波形数据必须是 bytes")
    data = bytes(raw)
    start = data.find(b"#")
    if start < 0:
        raise WaveformError("响应中找不到 IEEE 488.2 块头 '#'")
    if start + 1 >= len(data):
        raise WaveformError("块头不完整：缺少长度指示位")
    digits = data[start + 1] - 0x30
    if not 0 <= digits <= 9:
        raise WaveformError(f"非法块头长度指示位: {chr(data[start + 1])!r}")
    if digits == 0:
        body = data[start + 2 :]
        return body.rstrip(b"\r\n")
    header_end = start + 2 + digits
    if header_end > len(data):
        raise WaveformError("块头不完整：长度字段被截断")
    try:
        length = int(data[start + 2 : header_end])
    except ValueError as exc:
        raise WaveformError(f"块头长度字段不是数字: {data[start + 2 : header_end]!r}") from exc
    body = data[header_end : header_end + length]
    if len(body) != length:
        raise WaveformError(f"数据块长度不符：块头声明 {length} 字节，实际收到 {len(body)} 字节")
    return body


def decode_codes(body: bytes, preamble: WaveformPreamble) -> list[int]:
    """把二进制块解成原始码值；字节序与有/无符号按前导信息决定。"""
    byt_nr = preamble.byt_nr
    if byt_nr not in (1, 2):
        raise WaveformError(f"不支持的每点字节数: {byt_nr}")
    if len(body) % byt_nr:
        raise WaveformError(f"数据长度 {len(body)} 不是 {byt_nr} 字节的整数倍")
    signed = preamble.signed
    if byt_nr == 1:
        prefix = ""
        code_char = "b" if signed else "B"
    else:
        prefix = ">" if preamble.big_endian else "<"
        code_char = "h" if signed else "H"
    count = len(body) // byt_nr
    try:
        return list(struct.unpack(f"{prefix}{count}{code_char}", body))
    except struct.error as exc:  # pragma: no cover - 长度已校验
        raise WaveformError(f"码值解包失败: {exc}") from exc


def decode_ascii_codes(body: bytes) -> list[int]:
    """解析 ASCII 编码的 `CURVe?` 响应（逗号分隔的有符号十进制整数）。"""
    text = body.decode("ascii", errors="strict").strip()
    if not text:
        return []
    try:
        return [int(float(token)) for token in text.replace("\n", "").split(",") if token.strip()]
    except ValueError as exc:
        raise WaveformError(f"ASCII 波形数据解析失败: {exc}") from exc


def codes_to_volts(codes: list[int], preamble: WaveformPreamble) -> list[float]:
    """按手册公式换算：(code − YOFf) × YMUlt + YZEro。"""
    mult, off, zero = preamble.y_mult, preamble.y_off, preamble.y_zero
    return [(code - off) * mult + zero for code in codes]


def time_axis(preamble: WaveformPreamble, samples: int) -> list[float]:
    """时间轴：首点时间 XZEro，步进 XINcr。"""
    incr, zero = preamble.x_increment, preamble.x_zero
    return [zero + index * incr for index in range(samples)]


def build_waveform(
    body: bytes, preamble: WaveformPreamble, *, ascii_encoding: bool = False
) -> Waveform:
    """把块数据 + 前导信息组合成完整波形。"""
    if preamble.pt_fmt.upper().startswith("ENV"):
        raise WaveformError("收到 ENV（包络）格式数据：应先关闭包络再读波形")
    codes = (
        decode_ascii_codes(body)
        if ascii_encoding or "ASCII" in preamble.encoding.upper()
        else decode_codes(body, preamble)
    )
    if not codes:
        raise WaveformError("波形数据为空")
    if preamble.nr_pt and len(codes) != preamble.nr_pt:
        raise WaveformError(f"点数不符：前导信息声明 {preamble.nr_pt}，实际 {len(codes)}")
    return Waveform(
        codes=codes,
        volts=codes_to_volts(codes, preamble),
        seconds=time_axis(preamble, len(codes)),
        preamble=preamble,
    )


#: `WFMOutpre?` 的字段：泰克按**缩写助记符**返回（BYT_N / ENC / YMU / YOF / YZE …），
#: 而手册与代码里写的是全称（BYT_Nr / ENCdg / YMUlt / YOFf / YZEro …）。
#: 因此按"键前缀"匹配，全称与缩写都能命中。
_PREAMBLE_FIELDS = {
    "BYT_N": ("byt_nr", int),
    "BIT_N": ("bit_nr", int),
    "NR_P": ("nr_pt", int),
    "XIN": ("x_increment", float),
    "XZE": ("x_zero", float),
    "YMU": ("y_mult", float),
    "YOF": ("y_off", float),
    "YZE": ("y_zero", float),
    "YUN": ("y_unit", str),
    "ENC": ("encoding", str),
    "BYT_O": ("byte_order", str),
    "BN_F": ("bn_fmt", str),
    "PT_F": ("pt_fmt", str),
}


def _match_preamble_field(key: str) -> tuple[str, type] | None:
    """按前缀匹配前导字段；长键优先，避免 YUN 与 YUNit 之类的歧义。"""
    for alias in sorted(_PREAMBLE_FIELDS, key=len, reverse=True):
        if key.startswith(alias):
            return _PREAMBLE_FIELDS[alias]
    return None


def parse_preamble(text: str) -> WaveformPreamble:
    """解析 `WFMOutpre?` 的响应（以分号分隔的 `键 值` 列表，键可为缩写）。"""
    preamble = WaveformPreamble()
    for token in text.replace("\n", " ").split(";"):
        parts = token.strip().split(None, 1)
        if len(parts) != 2:
            continue
        key = parts[0].split(":")[-1].upper()
        value = parts[1].strip().strip('"')
        field = _match_preamble_field(key)
        if field is None:
            continue
        attr, kind = field
        try:
            setattr(preamble, attr, kind(value))
        except ValueError:
            continue
    return preamble
