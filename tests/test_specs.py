"""校准规范配置（specs/*.json）与版本号来源的守护用例。"""

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from osccal import __version__
from osccal.cli import cli
from osccal.core.config import load_spec, resolve_spec_path
from osccal.core.config_validation import validate_spec
from osccal.core.storage import spec_record

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPECS_DIR = PROJECT_ROOT / "specs"
SPEC_PATH = SPECS_DIR / "jjf1057_2026.json"

# 规范第 7 章共 12 个校准项目，条款号 7.2 ~ 7.13 各一。
EXPECTED_CLAUSES = {f"7.{n}" for n in range(2, 14)}
# 其中程序不实现的 2 项（人工执行）。
MANUAL_ITEMS = {"visual_check", "self_cal_signal"}


@pytest.fixture(scope="module")
def spec() -> dict:
    with open(SPEC_PATH, encoding="utf-8") as f:
        return json.load(f)


class TestShippedSpec:
    def test_spec_is_valid(self, spec):
        assert validate_spec(spec) == []

    def test_all_clauses_covered(self, spec):
        # 条款号可能带子条（如 7.4.2），只比较到二级。
        clauses = {".".join(item["clause"].split(".")[:2]) for item in spec["items"].values()}
        assert clauses == EXPECTED_CLAUSES, f"缺少条款: {sorted(EXPECTED_CLAUSES - clauses)}"

    def test_item_count(self, spec):
        assert len(spec["items"]) == 12

    def test_manual_items_are_not_automatable(self, spec):
        for key in MANUAL_ITEMS:
            assert spec["items"][key]["automatable"] is False
        autos = {k for k, v in spec["items"].items() if v["automatable"]}
        assert autos == set(spec["items"]) - MANUAL_ITEMS

    def test_automatable_items_declare_points_and_record(self, spec):
        for key, item in spec["items"].items():
            if not item["automatable"]:
                continue
            assert "strategy" in item["points"], f"{key} 缺少取点策略"
            assert re.match(r"^A\.\d+$", item["record_table"]), f"{key} 记录表号非法"

    def test_record_tables_are_unique(self, spec):
        tables = [item["record_table"] for item in spec["items"].values()]
        assert len(tables) == len(set(tables))

    def test_limits_are_reference_only(self, spec):
        assert spec["limits_semantics"]["kind"] == "reference_only"
        assert "不作" in spec["limits_semantics"]["note"]

    def test_deviations_declared(self, spec):
        deviations = spec["deviations"]
        assert len(deviations) == 3
        joined = "".join(deviations)
        assert "7.11" in joined and "7.12" in joined, "应声明 ΔV/Δt 采用自动测量的偏离"
        assert "不确定度" in joined

    def test_dc_gain_uses_method_two(self, spec):
        item = spec["items"]["dc_gain"]
        assert item["clause"] == "7.4.2"
        assert item["method"] == "square_amplitude"
        assert item["points"]["scales_v_per_div"] == [0.01, 0.1, 1.0, 10.0]
        assert item["points"]["screen_fraction"] == 0.8
        assert "Vr / V" in item["formula"]["gain"]

    def test_bandwidth_ratios_stop_at_one(self, spec):
        ratios = spec["items"]["freq_response_bandwidth"]["points"]["ratios"]
        assert ratios[-1] == 1.0
        assert ratios == sorted(ratios)

    def test_timebase_points(self, spec):
        scales = spec["items"]["timebase_error"]["points"]["horizontal_scales_s_per_div"]
        assert len(scales) == 4
        assert scales[0] == pytest.approx(10e-9)
        assert scales[-1] == pytest.approx(10e-3)

    def test_random_noise_pauses_for_load(self, spec):
        action = spec["items"]["random_noise"]["requires_user_action"]
        assert action["pause"] is True
        assert "50 Ω" in action["prompt"]


class TestValidateSpec:
    def test_rejects_non_object(self):
        assert validate_spec([]) == ["配置必须是 JSON 对象"]

    def test_reports_missing_fields(self):
        errors = validate_spec({"name": "x"})
        assert any("缺少字段" in e for e in errors)

    @pytest.mark.parametrize("field", ["name", "spec_code"])
    def test_rejects_blank_identity(self, spec, field):
        data = json.loads(json.dumps(spec))
        data[field] = "  "
        errors = validate_spec(data)
        assert any(field in e for e in errors)

    def test_rejects_bad_date(self, spec):
        data = json.loads(json.dumps(spec))
        data["effective"] = "2027/02/21"
        assert any("effective" in e for e in validate_spec(data))

    def test_rejects_empty_deviations(self, spec):
        data = json.loads(json.dumps(spec))
        data["deviations"] = []
        assert any("deviations" in e for e in validate_spec(data))

    def test_rejects_unknown_item(self, spec):
        data = json.loads(json.dumps(spec))
        data["items"]["not_a_clause"] = {"clause": "1", "title": "x", "automatable": False}
        assert any("未知校准项目" in e for e in validate_spec(data))

    def test_rejects_bad_strategy(self, spec):
        data = json.loads(json.dumps(spec))
        data["items"]["dc_gain"]["points"]["strategy"] = "guess"
        assert any("strategy" in e for e in validate_spec(data))

    def test_rejects_conformity_semantics(self, spec):
        data = json.loads(json.dumps(spec))
        data["limits_semantics"]["kind"] = "pass_fail"
        assert any("reference_only" in e for e in validate_spec(data))

    def test_rejects_bad_record_table(self, spec):
        data = json.loads(json.dumps(spec))
        data["items"]["dc_gain"]["record_table"] = "表3"
        assert any("record_table" in e for e in validate_spec(data))


class TestSpecLoading:
    def test_resolve_by_name(self):
        assert resolve_spec_path(str(SPECS_DIR), "jjf1057_2026") == str(SPEC_PATH)

    def test_resolve_by_name_with_suffix(self):
        assert resolve_spec_path(str(SPECS_DIR), "jjf1057_2026.json") == str(SPEC_PATH)

    def test_resolve_by_path(self):
        assert resolve_spec_path(str(SPECS_DIR), str(SPEC_PATH)) == str(SPEC_PATH)

    @pytest.mark.parametrize("value", [None, "", "no_such_spec"])
    def test_resolve_missing(self, value):
        assert resolve_spec_path(str(SPECS_DIR), value) is None

    def test_load_spec_returns_data(self):
        data = load_spec(str(SPEC_PATH))
        assert data["spec_code"] == "JJF 1057-2026"

    def test_load_spec_missing_file_returns_empty(self):
        assert load_spec(str(SPECS_DIR / "nope.json")) == {}

    def test_spec_record_carries_digest_and_deviations(self, spec):
        record = spec_record(spec, str(SPEC_PATH))
        assert record["spec_code"] == "JJF 1057-2026"
        assert record["file"] == "jjf1057_2026.json"
        assert len(record["sha256"]) == 64
        assert len(record["deviations"]) == 3
        assert record["limits_semantics"]["kind"] == "reference_only"
        assert record["applied"] is False


class TestVersionSingleSource:
    def test_module_version(self):
        assert re.match(r"^\d+\.\d+\.\d+$", __version__)

    def test_cli_version_matches_module(self):
        result = CliRunner().invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_pyproject_defers_to_module(self):
        text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert 'dynamic = ["version"]' in text
        assert 'attr = "osccal.__version__"' in text
        assert not re.search(r'^version = "', text, re.MULTILINE), "版本号不应再写死在 pyproject"


class TestCliSpecOption:
    def test_unknown_spec_aborts_before_any_device(self):
        result = CliRunner().invoke(cli, ["calibrate", "--spec", "no_such_spec"])
        assert result.exit_code == 2
        assert "找不到规范配置文件" in result.output

    def test_help_mentions_spec(self):
        result = CliRunner().invoke(cli, ["calibrate", "--help"])
        assert result.exit_code == 0
        assert "--spec" in result.output
