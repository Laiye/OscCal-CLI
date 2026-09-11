"""输出编码处理测试：标准输出在 GBK 环境下不应因 ✓/表格符号而崩溃。"""

import io
import sys

import pytest

from osccal.core.utils import enable_utf8_output


def _gbk_stream():
    """构造一个 GBK 编码的文本流（模拟 Windows 中文控制台重定向输出）。"""
    raw = io.BytesIO()
    return raw, io.TextIOWrapper(raw, encoding="gbk", errors="strict")


class _NoReconfigure:
    """无 reconfigure 方法的流（用于验证安全跳过）。"""

    def write(self, s):
        return len(s)

    def flush(self):
        pass


def test_gbk_stream_write_symbol_raises():
    """记录原始问题：GBK 流无法编码 ✓。"""
    _, stream = _gbk_stream()
    with pytest.raises(UnicodeEncodeError):
        stream.write("✓")
        stream.flush()


def test_enable_utf8_output_reconfigures_streams(monkeypatch):
    """修复后：GBK 流被切换为 UTF-8，✓ 与中文均可正常写出。"""
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    raw, stdout = _gbk_stream()
    _, stderr = _gbk_stream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    enable_utf8_output()

    assert stdout.encoding.lower().replace("-", "") == "utf8"
    assert stderr.encoding.lower().replace("-", "") == "utf8"

    stdout.write("✓ 校准完成 ΔV Ω\n")
    stdout.flush()
    assert "✓ 校准完成 ΔV Ω".encode() in raw.getvalue()


def test_enable_utf8_output_respects_pythonioencoding(monkeypatch):
    """用户显式设置 PYTHONIOENCODING 时不做修改。"""
    monkeypatch.setenv("PYTHONIOENCODING", "gbk")
    _, stdout = _gbk_stream()
    _, stderr = _gbk_stream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    enable_utf8_output()

    assert stdout.encoding.lower() in ("gbk", "cp936")


def test_enable_utf8_output_skips_streams_without_reconfigure(monkeypatch):
    """非文本流（无 reconfigure）应被安全跳过，不抛异常。"""
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.setattr(sys, "stdout", _NoReconfigure())
    monkeypatch.setattr(sys, "stderr", _NoReconfigure())

    enable_utf8_output()


def test_cli_main_enables_utf8_before_running(monkeypatch):
    """CLI 入口应先设置输出编码，再执行命令。"""
    import osccal.cli as cli_mod
    import osccal.core.utils as utils_mod

    calls: list[str] = []
    monkeypatch.setattr(utils_mod, "enable_utf8_output", lambda: calls.append("utf8"))
    monkeypatch.setattr(cli_mod, "cli", lambda: calls.append("cli"))

    cli_mod.main()

    assert calls == ["utf8", "cli"]
