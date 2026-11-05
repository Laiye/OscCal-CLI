"""全量配置结构测试：覆盖 commands/、characteristics/、specs/、schemes/、calibrators/。

校验规则与运行时的 osccal.core.config_validation 共用同一实现，
保证"加载即校验"与"测试即校验"行为一致（单一事实来源）。
"""

import json
from pathlib import Path

import pytest

from osccal.core.config_validation import (
    validate_calibrator,
    validate_characteristics,
    validate_commands,
    validate_scheme,
    validate_spec,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMMANDS_DIR = PROJECT_ROOT / "commands"
CHARACTERISTICS_DIR = PROJECT_ROOT / "characteristics"
SPECS_DIR = PROJECT_ROOT / "specs"
SCHEMES_DIR = PROJECT_ROOT / "schemes"
CALIBRATORS_DIR = PROJECT_ROOT / "calibrators"

COMMAND_FILES = sorted(COMMANDS_DIR.glob("*.json"))
CHARACTERISTICS_FILES = sorted(CHARACTERISTICS_DIR.glob("*.json"))
SPEC_FILES = sorted(SPECS_DIR.glob("*.json"))
SCHEME_FILES = sorted(SCHEMES_DIR.glob("*.json"))
CALIBRATOR_FILES = sorted(CALIBRATORS_DIR.glob("*.json"))


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _basename(path: Path) -> str:
    return path.name


def _format_errors(errors: list[str]) -> str:
    return "\n".join(f"  - {e}" for e in errors)


class TestAllCommands:
    @pytest.mark.parametrize("fpath", COMMAND_FILES, ids=_basename)
    def test_json_valid(self, fpath):
        _load(fpath)

    @pytest.mark.parametrize("fpath", COMMAND_FILES, ids=_basename)
    def test_config_valid(self, fpath):
        errors = validate_commands(_load(fpath))
        assert errors == [], f"指令集结构错误:\n{_format_errors(errors)}"


class TestAllCharacteristics:
    @pytest.mark.parametrize("fpath", CHARACTERISTICS_FILES, ids=_basename)
    def test_json_valid(self, fpath):
        _load(fpath)

    @pytest.mark.parametrize("fpath", CHARACTERISTICS_FILES, ids=_basename)
    def test_config_valid(self, fpath):
        errors = validate_characteristics(_load(fpath))
        assert errors == [], f"特征配置结构错误:\n{_format_errors(errors)}"

    @pytest.mark.parametrize("fpath", CHARACTERISTICS_FILES, ids=_basename)
    def test_has_no_points(self, fpath):
        data = _load(fpath)
        for forbidden in ("points", "calibration_limits", "method", "methods"):
            assert forbidden not in data, f"特征文件不应包含 {forbidden}"


class TestAllSpecs:
    @pytest.mark.parametrize("fpath", SPEC_FILES, ids=_basename)
    def test_json_valid(self, fpath):
        _load(fpath)

    @pytest.mark.parametrize("fpath", SPEC_FILES, ids=_basename)
    def test_config_valid(self, fpath):
        errors = validate_spec(_load(fpath))
        assert errors == [], f"规范配置结构错误:\n{_format_errors(errors)}"

    @pytest.mark.parametrize("fpath", SPEC_FILES, ids=_basename)
    def test_has_no_scheme_fields(self, fpath):
        data = _load(fpath)
        for item in data["items"].values():
            for forbidden in ("method", "points", "stimulus"):
                assert forbidden not in item, f"规范文件不应包含方案字段 {forbidden}"


class TestAllSchemes:
    @pytest.mark.parametrize("fpath", SCHEME_FILES, ids=_basename)
    def test_json_valid(self, fpath):
        _load(fpath)

    @pytest.mark.parametrize("fpath", SCHEME_FILES, ids=_basename)
    def test_config_valid(self, fpath):
        errors = validate_scheme(_load(fpath))
        assert errors == [], f"方案配置结构错误:\n{_format_errors(errors)}"


class TestSchemeReferences:
    @pytest.mark.parametrize("fpath", SCHEME_FILES, ids=_basename)
    def test_spec_reference_exists_and_covers_items(self, fpath):
        scheme = _load(fpath)
        spec_path = SPECS_DIR / f"{scheme['spec']}.json"
        assert spec_path.exists(), f"方案引用的规范不存在: {spec_path}"
        spec_items = _load(spec_path)["items"]
        for name in scheme["items"]:
            assert name in spec_items, f"方案项目 {name} 不在规范中"
            assert spec_items[name]["automatable"] is True, f"人工项 {name} 不应写入方案"


class TestAllCalibrators:
    @pytest.mark.parametrize("fpath", CALIBRATOR_FILES, ids=_basename)
    def test_json_valid(self, fpath):
        _load(fpath)

    @pytest.mark.parametrize("fpath", CALIBRATOR_FILES, ids=_basename)
    def test_config_valid(self, fpath):
        errors = validate_calibrator(_load(fpath))
        assert errors == [], f"校准仪配置结构错误:\n{_format_errors(errors)}"
