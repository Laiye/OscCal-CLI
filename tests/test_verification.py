"""验证台账的结构守护：确保 10 个项目齐全、状态合法、必需字段存在。"""

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEDGER = PROJECT_ROOT / "verification" / "jjf1057_2026.json"

ALLOWED_STATUS = {"verified", "verified_with_caveat", "deviation", "unverified"}
REQUIRED_KEYS = {"item", "clause", "status", "reference", "points", "measured", "record"}


@pytest.fixture(scope="module")
def ledger() -> dict:
    with open(LEDGER, encoding="utf-8") as handle:
        return json.load(handle)


def test_ledger_exists():
    assert LEDGER.exists(), "验证台账缺失"


def test_covers_all_items(ledger):
    from osccal.measure.registry import ITEM_ORDER

    recorded = [entry["item"] for entry in ledger["items"]]
    assert sorted(recorded) == sorted(ITEM_ORDER), "台账项目与 registry 不一致"
    assert len(recorded) == len(set(recorded)), "台账存在重复项目"


def test_entries_have_required_fields(ledger):
    for entry in ledger["items"]:
        missing = REQUIRED_KEYS - set(entry)
        assert not missing, f"{entry['item']} 缺少字段 {missing}"
        assert entry["status"] in ALLOWED_STATUS, f"{entry['item']} 状态非法"


def test_measured_data_present(ledger):
    for entry in ledger["items"]:
        assert entry["measured"], f"{entry['item']} 没有实测数据"
        assert entry["points"] >= 1


def test_hardware_and_spec_recorded(ledger):
    assert ledger["spec"]["code"] == "JJF 1057-2026"
    assert ledger["spec"]["limits_semantics"] == "reference_only"
    calibrator = ledger["hardware"]["calibrator"]
    assert calibrator["certificate"], "缺少标准器证书号"
    assert calibrator["certified_edges"]["fast_edge_ps"] > 0


def test_deviations_are_explained(ledger):
    """标记为 deviation 的项目必须写明偏离内容。"""
    for entry in ledger["items"]:
        if entry["status"] == "deviation":
            assert entry.get("deviations"), f"{entry['item']} 标为 deviation 但未说明偏离"
