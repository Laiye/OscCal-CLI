"""auto_detect 配置匹配回归测试。

重点覆盖 P0 修复：空厂商字段曾因 `"" in "Tektronix"` 恒为真而匹配到
所有带 manufacturer 的配置文件。
"""

import json

import pytest

from osccal.core.auto_detect import _filter_by_manufacturer, _fuzzy_match_series, detect_configs


def _write(path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_empty_manufacturer_does_not_match_everything(tmp_path):
    """空厂商不应把仅有 manufacturer、没有 series 的文件当作候选。"""
    _write(tmp_path / "a.json", {"manufacturer": "Tektronix"})
    _write(tmp_path / "b.json", {"manufacturer": "Rigol", "series": "MSO5000"})

    candidates = _filter_by_manufacturer(str(tmp_path), "")

    assert "a.json" not in candidates
    assert candidates == {}


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


def test_empty_model_and_tied_series_are_rejected():
    candidates = {"a.json": ["MDO34"], "b.json": ["MDO34"]}
    assert _fuzzy_match_series("", candidates) is None
    assert _fuzzy_match_series("MDO34", candidates) is None


@pytest.mark.parametrize("invalid", ["actions", "profile", "duplicate", "empty_identity"])
def test_auto_detection_uses_runtime_validation(tmp_path, mdo3_commands, mdo34_profile, invalid):
    import copy

    commands = tmp_path / "commands"
    profiles = tmp_path / "profiles"
    commands.mkdir()
    profiles.mkdir()
    cmd, profile = copy.deepcopy(mdo3_commands), copy.deepcopy(mdo34_profile)
    if invalid == "actions":
        cmd["actions"] = {}
    if invalid == "profile":
        profile["vertical_div"] = "8"
    _write(commands / "a.json", cmd)
    _write(profiles / "a.json", profile)
    if invalid == "duplicate":
        _write(commands / "b.json", cmd)
    idn = {"manufacturer": "TEKTRONIX", "model": "" if invalid == "empty_identity" else "MDO34"}
    found_cmd, found_profile, _, _ = detect_configs(str(commands), str(profiles), idn)
    assert not found_cmd or not found_profile


def test_non_object_candidate_and_foreign_brand_are_ignored(tmp_path):
    _write(tmp_path / "bad.json", [])
    _write(tmp_path / "tektronix_wrong.json", {"manufacturer": "Rigol", "series": "MDO34"})
    assert _filter_by_manufacturer(str(tmp_path), "TEKTRONIX") == {}
