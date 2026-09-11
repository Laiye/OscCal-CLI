import math
import os
import sys
from contextlib import suppress


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


def format_with_fixed_precision(number, precision):
    if number == 0:
        return "0." + "0" * (precision - 1)
    order = math.floor(math.log10(abs(number)))
    decimals = precision - 1 - order
    format_string = "{:." + str(max(0, decimals)) + "f}"
    formatted_number = format_string.format(number)
    parts = formatted_number.rstrip("0").split(".")
    integer_part = parts[0]
    decimal_part = parts[1] if len(parts) > 1 else ""
    if decimals > 0:
        decimal_part += "0" * (decimals - len(decimal_part))
    else:
        decimal_part = ""
    formatted_number = integer_part if not decimal_part else f"{integer_part}.{decimal_part}"
    return formatted_number
