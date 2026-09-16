"""设备身份核对测试：厂商/型号与配置的匹配规则。

覆盖本轮修复的场景：FLUKE 9500B 在不同固件下 *IDN? 分别上报 "9500B" 与 "9500"，
配置必须能同时接受两者，否则执行前校验会误报"型号不匹配"而中止校准。
"""

import json
from pathlib import Path

import pytest

from osccal.core.config_validation import (
    manufacturer_matches,
    model_matches,
    validate_device_identity,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CALIBRATOR_FILE = PROJECT_ROOT / "calibrators" / "fluke_9500b.json"


def _load_calibrator() -> dict:
    with open(CALIBRATOR_FILE, encoding="utf-8") as f:
        return json.load(f)


def _idn(manufacturer: str, model: str) -> dict:
    return {"manufacturer": manufacturer, "model": model, "serial": "471475627", "firmware": "4.12"}


# ── 型号家族匹配 ────────────────────────────────────────────────────────


class TestModelMatches:
    def test_exact_match(self):
        assert model_matches("9500B", "9500B")

    def test_case_and_separator_insensitive(self):
        assert model_matches("9500b", "9500-B")
        assert model_matches("MDO 3052", "mdo3052")

    def test_shorter_is_prefix_of_longer(self):
        """同家族变体：9500 / 9500B 互认。"""
        assert model_matches("9500B", "9500")
        assert model_matches("9500", "9500B")

    def test_too_short_prefix_is_rejected(self):
        """过短前缀不算同家族，避免把 950 误判为 9500B。"""
        assert not model_matches("9500B", "950")

    def test_prefix_parameter(self):
        assert model_matches("9500B", "950", min_prefix=3)
        assert not model_matches("9500B", "950", min_prefix=4)

    def test_different_family_rejected(self):
        assert not model_matches("9500B", "5500")
        assert not model_matches("MDO3052", "MSO3052")

    def test_empty_or_non_string(self):
        assert not model_matches("", "9500")
        assert not model_matches("9500", "")
        assert not model_matches(None, "9500")  # type: ignore[arg-type]


class TestManufacturerMatches:
    def test_alias_and_containment(self):
        assert manufacturer_matches("Tektronix", "TEK")
        assert manufacturer_matches("ZLG", "ZHIYUAN")
        assert manufacturer_matches("Fluke", "FLUKE")

    def test_cross_manufacturer_rejected(self):
        assert not manufacturer_matches("Tektronix", "FLUKE")
        assert not manufacturer_matches("Fluke", "RIGOL")

    def test_empty_rejected(self):
        assert not manufacturer_matches("", "FLUKE")
        assert not manufacturer_matches("Fluke", None)  # type: ignore[arg-type]


# ── 校准仪身份核对（本轮报错的回归用例） ────────────────────────────────


class TestCalibratorIdentity:
    def test_real_config_accepts_both_idn_variants(self):
        """真实配置须同时接受上报 9500B 与 9500 的同一台 9500B。"""
        calibrator = _load_calibrator()
        assert validate_device_identity(calibrator, _idn("Fluke", "9500B"), "校准仪") == []
        assert validate_device_identity(calibrator, _idn("Fluke", "9500"), "校准仪") == []
        assert validate_device_identity(calibrator, _idn("FLUKE", "9500"), "校准仪") == []

    def test_series_fallback_tolerates_model_variant(self):
        """未提供 models 的校准仪配置走 series 回退，也应按家族匹配。"""
        calibrator = {"name": "9500B", "series": ["9500B"]}
        assert validate_device_identity(calibrator, _idn("Fluke", "9500"), "校准仪") == []

    def test_series_fallback_rejects_other_model(self):
        calibrator = {"name": "9500B", "series": ["9500B"]}
        errors = validate_device_identity(calibrator, _idn("Fluke", "5500"), "校准仪")
        assert len(errors) == 1
        assert "5500" in errors[0]
        assert "9500B" in errors[0], "报错应列出配置支持的型号，便于排查"

    def test_models_whitelist_is_exact(self):
        """提供 models 时按白名单精确比较，不做前缀放宽。"""
        calibrator = {"name": "9500B", "models": ["9500B"]}
        assert validate_device_identity(calibrator, _idn("Fluke", "9500B"), "校准仪") == []
        errors = validate_device_identity(calibrator, _idn("Fluke", "9500"), "校准仪")
        assert len(errors) == 1
        assert "不在配置 models 中" in errors[0]
        assert "9500B" in errors[0]

    def test_manufacturer_mismatch_rejected(self):
        calibrator = _load_calibrator()
        calibrator["manufacturer"] = "Fluke"
        errors = validate_device_identity(calibrator, _idn("TEKTRONIX", "9500"), "校准仪")
        assert any("厂商与配置不匹配" in e for e in errors)


# ── 示波器身份核对 ──────────────────────────────────────────────────────


class TestOscilloscopeIdentity:
    def test_models_exact_match(self):
        commands = {"manufacturer": "Tektronix", "models": ["MDO32", "MDO34"]}
        assert validate_device_identity(commands, _idn("TEKTRONIX", "MDO34"), "示波器指令集") == []

    def test_unknown_model_reports_supported_list(self):
        commands = {"manufacturer": "Tektronix", "models": ["MDO32", "MDO34"]}
        errors = validate_device_identity(commands, _idn("TEKTRONIX", "MDO3052"), "示波器指令集")
        assert len(errors) == 1
        assert "MDO3052" in errors[0]
        assert "MDO32" in errors[0] and "MDO34" in errors[0]

    def test_scope_configs_without_models_skip_series_check(self):
        """示波器配置缺 models 时只核对厂商，不套用校准仪的 series 回退。"""
        commands = {"manufacturer": "Tektronix", "series": ["MDO3000"]}
        assert (
            validate_device_identity(commands, _idn("TEKTRONIX", "MDO3052"), "示波器指令集") == []
        )


# ── 输入健壮性 ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "idn",
    [
        {},
        {"manufacturer": "", "model": "9500"},
        {"manufacturer": "Fluke", "model": ""},
        {"manufacturer": None, "model": "9500"},
        {"manufacturer": "Fluke", "model": 9500},
    ],
)
def test_invalid_idn_reports_error_without_raising(idn):
    errors = validate_device_identity(_load_calibrator(), idn, "校准仪")
    assert errors and "无法核对配置" in errors[0]
