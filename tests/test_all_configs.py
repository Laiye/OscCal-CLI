"""全量配置结构测试：覆盖 commands/、profiles/、calibrators/ 下所有 JSON 配置。

校验规则与运行时的 osccal.core.config_validation 共用同一实现，
保证"加载即校验"与"测试即校验"行为一致（单一事实来源）。
"""

import json
from pathlib import Path

import pytest

from osccal.core.config_validation import (
    validate_calibrator,
    validate_commands,
    validate_profile,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMMANDS_DIR = PROJECT_ROOT / "commands"
PROFILES_DIR = PROJECT_ROOT / "profiles"
CALIBRATORS_DIR = PROJECT_ROOT / "calibrators"

COMMAND_FILES = sorted(COMMANDS_DIR.glob("*.json"))
PROFILE_FILES = sorted(PROFILES_DIR.glob("*.json"))
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


class TestAllProfiles:
    @pytest.mark.parametrize("fpath", PROFILE_FILES, ids=_basename)
    def test_json_valid(self, fpath):
        _load(fpath)

    @pytest.mark.parametrize("fpath", PROFILE_FILES, ids=_basename)
    def test_config_valid(self, fpath):
        errors = validate_profile(_load(fpath))
        assert errors == [], f"特征配置结构错误:\n{_format_errors(errors)}"


class TestAllCalibrators:
    @pytest.mark.parametrize("fpath", CALIBRATOR_FILES, ids=_basename)
    def test_json_valid(self, fpath):
        _load(fpath)

    @pytest.mark.parametrize("fpath", CALIBRATOR_FILES, ids=_basename)
    def test_config_valid(self, fpath):
        errors = validate_calibrator(_load(fpath))
        assert errors == [], f"校准仪配置结构错误:\n{_format_errors(errors)}"
