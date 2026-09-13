"""auto_detect 配置匹配回归测试。

重点覆盖 P0 修复：空厂商字段曾因 `"" in "Tektronix"` 恒为真而匹配到
所有带 manufacturer 的配置文件。
"""

import json

from osccal.core.auto_detect import _filter_by_manufacturer


def _write(path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_empty_manufacturer_does_not_match_everything(tmp_path):
    """空厂商不应把仅有 manufacturer、没有 series 的文件当作候选。"""
    _write(tmp_path / "a.json", {"manufacturer": "Tektronix"})
    _write(tmp_path / "b.json", {"manufacturer": "Rigol", "series": "MSO5000"})

    candidates = _filter_by_manufacturer(str(tmp_path), "")

    assert "a.json" not in candidates
    assert "b.json" in candidates


def test_manufacturer_field_match(tmp_path):
    _write(tmp_path / "a.json", {"manufacturer": "Tektronix"})
    _write(tmp_path / "b.json", {"manufacturer": "Rigol", "series": "MSO5000"})

    assert "a.json" in _filter_by_manufacturer(str(tmp_path), "Tektronix")
    assert "b.json" not in _filter_by_manufacturer(str(tmp_path), "Tektronix")
    assert "b.json" in _filter_by_manufacturer(str(tmp_path), "RIGOL")


def test_manufacturer_substring_match(tmp_path):
    """IDN 简写（如 TEK）应能匹配完整厂商名。"""
    _write(tmp_path / "a.json", {"manufacturer": "Tektronix"})
    assert "a.json" in _filter_by_manufacturer(str(tmp_path), "TEK")
