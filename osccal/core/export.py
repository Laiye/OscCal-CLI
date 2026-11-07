"""Excel 报告导出：按 JJF 1057-2026 附录 A/B 的项目名称组织工作表。

- 每个校准项目一张工作表，标题用附录 A 的编号与名称（如「A.3 直流增益」）；
- 单元格按显示精度整理，与终端 `osccal show` 一致；
- **不再做合格/超差判定**：表 1 指标仅供参考，工作表末尾给出参考指标与免责说明；
- 校准信息表补充依据规范、实施日期、配置文件与逐条偏离声明。
"""

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from rich.console import Console

from osccal.core.methods import ITEM_METHODS
from osccal.core.storage import STATUS_LABELS
from osccal.core.table_configs import (
    LIMITS_DISCLAIMER,
    active_config,
    base_item_name,
    method_note,
    reference_text,
    row_values,
    select_rows,
)
from osccal.core.utils import prepare_excel_value

console = Console()


def export_to_excel(data: dict, output_path: str) -> str:
    wb = Workbook()

    metadata = data.get("metadata", {})
    results = data.get("results", {})
    limits = metadata.get("limits", {})

    _create_info_sheet(wb, metadata)

    # 按校准项目分组：同一项目的所有通道数据合并到同一个 sheet。
    # 失败项目的部分数据点不导出（失败原因写在校准信息表）。
    failed_keys = set(metadata.get("failures", {}))
    grouped: dict[str, list] = {}
    for item_name, rows in results.items():
        if not rows or item_name in failed_keys:
            continue
        base_name = base_item_name(item_name)
        grouped.setdefault(base_name, []).extend(rows)

    for base_name, rows in grouped.items():
        config = active_config(base_name, rows, metadata.get("scheme"))
        if not config:
            console.print(f"[yellow]⚠ 未知校准项目，跳过导出: {base_name}[/yellow]")
            continue
        data_rows = select_rows(config, rows)
        if data_rows:
            note = method_note(base_name, rows, metadata.get("scheme"))
            _create_data_sheet(wb, base_name, config, data_rows, limits, note)

    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    wb.save(output_path)
    console.print(f"[green]✓[/green] 报告已导出: [cyan]{output_path}[/cyan]")
    return output_path


def _create_info_sheet(wb, metadata):
    ws = wb.active
    ws.title = "校准信息"

    label_font = Font(bold=True, size=11)
    normal_font = Font(size=11)
    border = Border(bottom=Side(style="thin"))

    ws["A1"] = "示波器校准报告"
    ws["A1"].font = Font(bold=True, size=18)
    ws.merge_cells("A1:D1")

    row = 3
    info_items = [
        ("校准时间", metadata.get("timestamp", "")),
        ("校准状态", STATUS_LABELS.get(metadata.get("status"), "未记录")),
        ("SCPI 失败次数", metadata.get("scpi_errors", "未记录")),
        ("通道", f"CH{metadata.get('channel', '')}"),
        ("探头", metadata.get("probe", "")),
    ]
    characteristics_file = metadata.get("characteristics_file") or metadata.get("profile_file")
    if characteristics_file:
        info_items.append(("特征文件", characteristics_file))

    spec = metadata.get("spec") or {}
    if spec:
        info_items.extend(
            [
                ("依据规范", spec.get("name", "")),
                ("规范代号", spec.get("spec_code", "")),
                ("规范文件", spec.get("file", "")),
                ("规范摘要(sha256)", spec.get("sha256", "")),
            ]
        )

    scheme = metadata.get("scheme") or {}
    if scheme:
        info_items.extend(
            [
                ("依据方案", scheme.get("name", "")),
                ("方案文件", scheme.get("file", "")),
                ("方案摘要(sha256)", scheme.get("sha256", "")),
            ]
        )
        for item_name, selection in (scheme.get("items") or {}).items():
            labels = ITEM_METHODS.get(item_name, {})
            methods = [labels.get(name, name) for name in selection.get("methods", [])]
            method = selection.get("method")
            primary = selection.get("primary")
            if method:
                # 单方法方案：只写实际执行的方法，不能再把候选集当成本轮方法。
                text = labels.get(method, method)
            else:
                text = " + ".join(methods)
                if primary and len(methods) > 1:
                    text += f"（主：{labels.get(primary, primary)}）"
            info_items.append((f"方案方法 {item_name}", text))

    for name, failure in metadata.get("failures", {}).items():
        info_items.append((f"失败项目 {name}", failure.get("message", "")))

    osc = metadata.get("oscilloscope", {})
    info_items.extend(
        [
            ("示波器厂家", osc.get("manufacturer", "")),
            ("示波器型号", osc.get("model", "")),
            ("示波器序列号", osc.get("serial", "")),
            ("示波器固件版本", osc.get("firmware", "")),
        ]
    )

    cal = metadata.get("calibrator", {})
    info_items.extend(
        [
            ("校准仪厂家", cal.get("manufacturer", "")),
            ("校准仪型号", cal.get("model", "")),
        ]
    )

    deviations = spec.get("deviations", []) if spec else []
    for index, deviation in enumerate(deviations, start=1):
        info_items.append((f"偏离声明 {index}", deviation))

    for index, note in enumerate(metadata.get("skipped_points", []), start=1):
        info_items.append((f"跳过点 {index}", f"{note.get('item', '')}：{note.get('reason', '')}"))

    for label, value in info_items:
        ws.cell(row=row, column=1, value=label).font = label_font
        ws.cell(row=row, column=2, value=value).font = normal_font
        ws.cell(row=row, column=1).border = border
        ws.cell(row=row, column=2).border = border
        row += 1

    ws.cell(row=row + 1, column=1, value=LIMITS_DISCLAIMER).font = Font(italic=True, size=10)
    ws.merge_cells(start_row=row + 1, start_column=1, end_row=row + 1, end_column=4)

    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 60


def _create_data_sheet(wb, name, config, rows, limits, note=""):
    ws = wb.create_sheet(title=config["title"])

    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    center_align = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    headers = config.get("headers") or config["columns"]
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_align
        cell.border = thin_border

    precision_specs = config.get("precision") or []
    row_idx = 2
    for row_data in rows:
        values = row_values(config, row_data)
        for col_idx, val in enumerate(values, 1):
            # 单元格按显示精度整理：与终端表格位数一致，仍是数值单元格
            spec = precision_specs[col_idx - 1] if col_idx <= len(precision_specs) else None
            cell_value, number_format = prepare_excel_value(val, spec)
            cell = ws.cell(row=row_idx, column=col_idx, value=cell_value)
            if number_format:
                cell.number_format = number_format
            cell.alignment = center_align
            cell.border = thin_border
        row_idx += 1

    # 表尾：执行方法 + 参考指标 + 免责说明（不做合格判定）
    note_row = row_idx + 1
    if note:
        ws.cell(row=note_row, column=1, value="执行方法").font = Font(bold=True, size=10)
        ws.cell(row=note_row, column=2, value=note).font = Font(size=10)
        ws.merge_cells(
            start_row=note_row, start_column=2, end_row=note_row, end_column=len(headers)
        )
        note_row += 1
    ws.cell(row=note_row, column=1, value="参考指标").font = Font(bold=True, size=10)
    ws.cell(row=note_row, column=2, value=reference_text(name, limits)).font = Font(size=10)
    ws.merge_cells(start_row=note_row, start_column=2, end_row=note_row, end_column=len(headers))
    ws.cell(row=note_row + 1, column=1, value=LIMITS_DISCLAIMER).font = Font(italic=True, size=10)
    ws.merge_cells(
        start_row=note_row + 1, start_column=1, end_row=note_row + 1, end_column=len(headers)
    )

    for col_idx in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 20
