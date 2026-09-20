import math
import os
import sys
from contextlib import suppress
from typing import Any

# 显示精度规格：("sig", n) 保留 n 位有效数字（与校准时的终端表格同一规则），
# ("dec", n) 保留 n 位小数，None 表示原样输出。规格表见 core/table_configs.py。
PrecisionSpec = tuple[str, int] | None


def enable_utf8_output() -> None:
    """将标准输出/错误切换为 UTF-8，避免输出编码导致的崩溃。

    Windows 中文控制台在输出被重定向到文件或管道时，Python 会用 GBK（cp936）
    编码标准输出，而表格边框（│─┌）、`✓`/`⚠`、`Δ`/`Ω` 等符号不在 GBK 字符集内，
    会抛 UnicodeEncodeError 导致命令中断。此处统一改为 UTF-8 输出。

    若用户显式设置了 PYTHONIOENCODING，则尊重用户选择不做修改。
    非文本流（无 reconfigure 方法）会被安全跳过。
    """
    if os.environ.get("PYTHONIOENCODING"):
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with suppress(ValueError, OSError, AttributeError):
            reconfigure(encoding="utf-8", errors="replace")


def fixed_precision_decimals(number, precision: int) -> int:
    """保留 precision 位有效数字所需的小数位数。"""
    if number == 0:
        return max(0, precision - 1)
    order = math.floor(math.log10(abs(number)))
    return max(0, precision - 1 - order)


def format_with_fixed_precision(number, precision):
    decimals = fixed_precision_decimals(number, precision)
    return f"{number:.{decimals}f}"


def _as_number(value: Any) -> float | None:
    """把数值型值转成 float；非数值（含 bool、字符串）与非有限值返回 None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def format_display_value(value: Any, spec: PrecisionSpec) -> str:
    """按精度规格生成终端显示文本（`osccal show` 的表格用）。"""
    if spec is None:
        return str(value)
    number = _as_number(value)
    if number is None:
        return str(value)
    kind, precision = spec
    if kind == "sig":
        return format_with_fixed_precision(number, precision)
    return f"{number:.{precision}f}"


def prepare_excel_value(value: Any, spec: PrecisionSpec) -> tuple[Any, str | None]:
    """按精度规格整理 Excel 单元格，返回 (数值, 数字格式)。

    数值按显示精度四舍五入，与终端表格的有效位数一致；未舍入的原始读数保存在
    JSON 记录中。数字格式保证单元格显示同样位数（含末尾零），且仍是数值单元格。
    """
    if spec is None:
        return value, None
    number = _as_number(value)
    if number is None:
        return value, None
    kind, precision = spec
    decimals = fixed_precision_decimals(number, precision) if kind == "sig" else precision
    number_format = "0" if decimals <= 0 else "0." + "0" * decimals
    return round(number, decimals), number_format


def relative_error(measured: float, standard: float) -> float:
    """按原始精度计算相对误差，禁止无效值进入判定与存储。"""
    if not math.isfinite(measured) or not math.isfinite(standard) or standard == 0:
        raise ValueError("测量值和标准值必须有限，标准值不能为零")
    error = 100 * (measured - standard) / standard
    if not math.isfinite(error):
        raise ValueError("相对误差计算结果非有限数值")
    return error
