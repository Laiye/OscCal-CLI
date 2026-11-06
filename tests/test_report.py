"""报告层（table_configs / show / export）的守护用例。

重点：按附录 A 的项目名组织、按 keys 取值、**不做合格判定**、偏离声明可见。
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from openpyxl import load_workbook

from osccal.cli import cli
from osccal.core.table_configs import (
    EXCEL_ITEM_CONFIGS,
    ITEM_CONFIGS,
    ITEM_PRECISION,
    LIMITS_DISCLAIMER,
    active_config,
    method_note,
    reference_text,
    row_values,
    select_rows,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _metadata() -> dict:
    return {
        "timestamp": "2026-10-21T10:00:00",
        "channel": "1",
        "probe": "9530",
        "status": "completed",
        "scpi_errors": 0,
        "failures": {},
        "oscilloscope": {
            "manufacturer": "TEKTRONIX",
            "model": "MDO3052",
            "serial": "SIM001",
            "firmware": "1.0",
        },
        "calibrator": {"manufacturer": "FLUKE", "model": "9500B"},
        "spec": {
            "name": "JJF 1057-2026",
            "spec_code": "JJF 1057-2026",
            "file": "jjf1057_2026.json",
            "sha256": "a" * 64,
            "deviations": ["ΔV、Δt 采用自动测量读数。", "不含测量不确定度。"],
            "limits_semantics": {"kind": "reference_only"},
        },
        "scheme": {
            "name": "JJF 1057-2026 默认校准方案",
            "file": "jjf1057_2026.json",
            "sha256": "b" * 64,
            "items": {"dc_gain": {"methods": ["square_amplitude"], "primary": "square_amplitude"}},
        },
    }


def _results() -> dict:
    return {
        "input_impedance": [
            {
                "index": 1,
                "channel": "1",
                "impedance": "1M",
                "nominal_ohm": 1e6,
                "resistance_ohm": 1.0005e6,
                "capacitance_f": 1.2e-11,
                "error_pct": 0.05,
                "tolerance_pct": 0.5,
            }
        ],
        "dc_gain": [
            {
                "index": 1,
                "channel": "1",
                "impedance": "1M",
                "scale": 0.1,
                "std_value_vpp": 0.64,
                "measured_vpp": 0.6464,
                "gain": 1.01,
                "error_pct": 1.0,
            }
        ],
        "freq_response_bandwidth": [
            {
                "index": 1,
                "channel": "1",
                "frequency_hz": 50000.0,
                "amplitude_vpp": 0.5,
                "response": 1.0,
                "note": "基准",
            },
            {"channel": "1", "summary": "bandwidth", "bandwidth_hz": 5e8},
        ],
    }


class TestTableConfigs:
    def test_every_item_has_matching_columns_and_keys(self):
        for name, config in ITEM_CONFIGS.items():
            assert len(config["columns"]) == len(config["keys"]), name
            assert len(config["precision"]) == len(config["columns"]), name
            assert len(ITEM_PRECISION[name]) == len(config["columns"]), name

    def test_titles_follow_appendix_a(self):
        for config in ITEM_CONFIGS.values():
            assert config["title"].startswith("A."), config["title"]

    def test_no_uncertainty_column(self):
        for config in ITEM_CONFIGS.values():
            assert not any("不确定度" in col for col in config["columns"])

    def test_every_item_declares_reference(self):
        for config in ITEM_CONFIGS.values():
            assert config["reference"].strip()

    def test_excel_configs_share_precision(self):
        for name, config in EXCEL_ITEM_CONFIGS.items():
            assert config["precision"] is ITEM_CONFIGS[name]["precision"]

    def test_single_method_config_drops_unused_columns(self):
        rows = [
            {
                "methods_selected": ["square_amplitude"],
                "primary_method": "square_amplitude",
            }
        ]
        config = active_config("dc_gain", rows)
        assert config is not None
        assert "方法一 G" not in config["columns"]
        assert "方法三 G" not in config["columns"]
        assert "增益 G" in config["columns"]
        assert "方波幅度法" in method_note("dc_gain", rows)

    def test_trial_config_keeps_all_method_columns(self):
        rows = [
            {
                "methods_selected": [
                    "square_amplitude",
                    "dc_two_point",
                    "multi_point_lsq",
                ],
                "primary_method": "square_amplitude",
            }
        ]
        config = active_config("dc_gain", rows)
        assert config is not None
        assert "方法一 G" in config["columns"]
        assert "方法三 G" in config["columns"]
        assert len(config["columns"]) == len(ITEM_CONFIGS["dc_gain"]["columns"])

    def test_scheme_method_filters_without_row_metadata(self):
        scheme = {
            "items": {
                "timebase_error": {
                    "methods": ["frequency_readout", "waveform_fit"],
                    "method": "waveform_fit",
                }
            }
        }
        config = active_config("timebase_error", [], scheme)
        assert config is not None
        assert "方法一(ppm)" not in config["columns"]
        assert "方法二(ppm)" in config["columns"]
        assert "波形拟合法" in method_note("timebase_error", [], scheme)

    def test_freq_and_enob_table_include_vertical_scale(self):
        for name in ("freq_response_bandwidth", "enob"):
            config = ITEM_CONFIGS[name]
            assert "挡位(V/div)" in config["columns"]
            assert "vertical_scale" in config["keys"]
            assert len(config["columns"]) == len(config["keys"])
            assert len(config["precision"]) == len(config["columns"])

    def test_row_values_tolerates_missing_keys(self):
        row = {"index": 1, "channel": "1"}
        values = row_values(ITEM_CONFIGS["dc_gain"], row)
        assert values[0] == 1
        assert values[1] == "1"
        assert values[2:] == [""] * 11

    def test_row_values_formats_impedance_labels(self):
        values = row_values(ITEM_CONFIGS["delta_v"], {"impedance": "50"})
        assert values[2] == "50 Ω"
        values = row_values(ITEM_CONFIGS["delta_v"], {"impedance": "1M"})
        assert values[2] == "1 MΩ"

    def test_select_rows_filters_summary(self):
        rows = _results()["freq_response_bandwidth"]
        selected = select_rows(ITEM_CONFIGS["freq_response_bandwidth"], rows)
        assert len(selected) == 1
        assert "summary" not in selected[0]


class TestReferenceText:
    """参考指标只有规范一处来源：记录里的 limits 决定显示文本。"""

    def test_renders_from_record_limits(self):
        assert reference_text("dc_gain", {"dc_gain": {"mpe_pct": 2.0}}) == "最大允许误差 ±2%"
        text = reference_text(
            "input_impedance", {"input_impedance": {"ohm_50_pct": 1.0, "ohm_1m_pct": 0.5}}
        )
        assert text == "50 Ω ±1%，1 MΩ ±0.5%"

    def test_timebase_uses_scientific_notation(self):
        text = reference_text("timebase_error", {"timebase_rel_error": {"from": 1e-6, "to": 5e-9}})
        assert "10⁻⁶" in text and "10⁻⁹" in text

    def test_falls_back_without_limits(self):
        assert reference_text("dc_gain", None) == ITEM_CONFIGS["dc_gain"]["reference"]


class TestExport:
    def test_sheets_named_after_appendix(self, tmp_path):
        from osccal.core.export import export_to_excel

        data = {"metadata": _metadata(), "results": _results()}
        out = tmp_path / "report.xlsx"
        export_to_excel(data, str(out))

        wb = load_workbook(out)
        assert "校准信息" in wb.sheetnames
        assert "A.2 输入阻抗" in wb.sheetnames
        assert "A.3 直流增益" in wb.sheetnames

    def test_reference_and_disclaimer_present(self, tmp_path):
        from osccal.core.export import export_to_excel

        data = {"metadata": _metadata(), "results": _results()}
        out = tmp_path / "report.xlsx"
        export_to_excel(data, str(out))

        wb = load_workbook(out)
        text = " ".join(
            str(cell.value)
            for ws in wb.worksheets
            for row in ws.iter_rows()
            for cell in row
            if cell.value is not None
        )
        assert "参考指标" in text
        assert LIMITS_DISCLAIMER in text
        assert "ΔV、Δt 采用自动测量读数。" in text, "偏离声明应写入报告"

    def test_reference_cell_uses_record_limits(self, tmp_path):
        from osccal.core.export import export_to_excel

        metadata = _metadata()
        metadata["limits"] = {"dc_gain": {"mpe_pct": 2.0}}
        out = tmp_path / "report.xlsx"
        export_to_excel({"metadata": metadata, "results": _results()}, str(out))

        wb = load_workbook(out)
        text = " ".join(
            str(cell.value)
            for ws in wb.worksheets
            for row in ws.iter_rows()
            for cell in row
            if cell.value is not None
        )
        assert "最大允许误差 ±2%" in text, "参考指标文本应由记录里的规范限值渲染"

    def test_info_sheet_records_scheme_methods(self, tmp_path):
        from osccal.core.export import export_to_excel

        out = tmp_path / "report.xlsx"
        export_to_excel({"metadata": _metadata(), "results": _results()}, str(out))
        wb = load_workbook(out)
        try:
            values = {
                row[0]: row[1] for row in wb["校准信息"].iter_rows(min_row=3, values_only=True)
            }
            assert values["依据方案"] == "JJF 1057-2026 默认校准方案"
            assert "方波幅度法" in values["方案方法 dc_gain"]
        finally:
            wb.close()

    def test_data_sheet_footer_records_method(self, tmp_path):
        from osccal.core.export import export_to_excel

        out = tmp_path / "report.xlsx"
        export_to_excel({"metadata": _metadata(), "results": _results()}, str(out))
        wb = load_workbook(out)
        try:
            text = " ".join(
                str(cell.value)
                for row in wb["A.3 直流增益"].iter_rows()
                for cell in row
                if cell.value is not None
            )
            assert "执行方法" in text
            assert "方波幅度法" in text
        finally:
            wb.close()

    def test_no_pass_fail_wording(self, tmp_path):
        from osccal.core.export import export_to_excel

        data = {"metadata": _metadata(), "results": _results()}
        out = tmp_path / "report.xlsx"
        export_to_excel(data, str(out))

        wb = load_workbook(out)
        values = [
            str(cell.value)
            for ws in wb.worksheets
            for row in ws.iter_rows()
            for cell in row
            if isinstance(cell.value, str)
        ]
        joined = " ".join(values)
        assert "合格" not in joined
        assert "超差" not in joined

    def test_data_matches_keys(self, tmp_path):
        from osccal.core.export import export_to_excel

        data = {"metadata": _metadata(), "results": _results()}
        out = tmp_path / "report.xlsx"
        export_to_excel(data, str(out))

        ws = load_workbook(out)["A.3 直流增益"]
        assert ws.cell(row=1, column=1).value == "序号"
        assert ws.cell(row=2, column=1).value == 1
        assert ws.cell(row=2, column=8).value == pytest.approx(1.0)


class TestShow:
    def _write_record(self, tmp_path: Path) -> Path:
        path = tmp_path / "calibration.json"
        path.write_text(
            json.dumps(
                {"metadata": _metadata(), "results": _results()},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_show_renders_items_and_spec(self, tmp_path):
        path = self._write_record(tmp_path)
        result = CliRunner().invoke(cli, ["show", "--file", str(path)])
        assert result.exit_code == 0, result.output
        assert "A.2 输入阻抗" in result.output
        assert "A.3 直流增益" in result.output
        assert "JJF 1057-2026" in result.output
        assert "偏离声明" in result.output
        assert "不作为符合性判定依据" in result.output

    def test_show_skips_unknown_item_without_crash(self, tmp_path):
        data = {"metadata": _metadata(), "results": {"old_amp": [{"index": 1}]}}
        path = tmp_path / "old.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        result = CliRunner().invoke(cli, ["show", "--file", str(path)])
        assert result.exit_code == 0, result.output
        assert "未知校准项目" in result.output

    def test_skipped_points_visible_in_show_and_excel(self, tmp_path):
        from osccal.core.export import export_to_excel

        metadata = _metadata()
        metadata["skipped_points"] = [{"item": "直流增益", "reason": "标准值超出 50 Ω 上限"}]
        data = {"metadata": metadata, "results": _results()}
        path = tmp_path / "skipped.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        shown = CliRunner().invoke(cli, ["show", "--file", str(path)])
        assert shown.exit_code == 0, shown.output
        assert "跳过的校准点" in shown.output
        assert "标准值超出 50 Ω 上限" in shown.output

        output = tmp_path / "skipped.xlsx"
        export_to_excel(data, str(output))
        wb = load_workbook(output)
        try:
            text = " ".join(
                str(cell.value)
                for ws in wb.worksheets
                for row in ws.iter_rows()
                for cell in row
                if cell.value is not None
            )
        finally:
            wb.close()
        assert "跳过点 1" in text
        assert "标准值超出 50 Ω 上限" in text
