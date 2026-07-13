"""自动识别示波器和校准仪，匹配对应的指令集与特征配置文件。"""

from __future__ import annotations

import json
import os
from typing import Optional

from rich.console import Console
from rich.table import Table

console = Console()

# ── 品牌 → 文件名前缀映射（回退用） ─────────────────────────────────────
_BRAND_KEYWORDS: dict[str, str] = {
    "TEKTRONIX": "tektronix",
    "TEK": "tektronix",
    "RIGOL": "rigol",
    "SIGLENT": "siglent",
    "UNI-T": "unit",
    "UNIT": "unit",
    "ZLG": "zlg",
    "ZHIYUAN": "zlg",
}


def _identify_brand(manufacturer: str) -> Optional[str]:
    """根据 *IDN? 厂商字段返回配置文件名前缀，无法识别则返回 None。"""
    upper = manufacturer.strip().upper()
    for keyword, prefix in _BRAND_KEYWORDS.items():
        if keyword in upper:
            return prefix
    return None


def _fuzzy_match_series(
    model: str,
    candidates: dict[str, list[str] | str],
) -> Optional[str]:
    """模糊匹配型号到系列（series）字段。

    每个候选项可以有单个 series 字符串或 series 列表。
    返回最佳匹配的 key（文件名），无匹配则返回 None。
    """
    model_upper = model.strip().upper()

    best_key: Optional[str] = None
    best_score: int = 0

    for key, series_raw in candidates.items():
        series_list = series_raw if isinstance(series_raw, list) else [series_raw]
        for series in series_list:
            series_upper = series.strip().upper()
            score = 0

            if model_upper == series_upper:
                score = 100
            elif model_upper.startswith(series_upper):
                score = 85
            elif series_upper.startswith(model_upper):
                score = 80
            elif series_upper in model_upper:
                score = 70
            elif model_upper in series_upper:
                score = 65
            else:
                common = 0
                for a, b in zip(model_upper, series_upper):
                    if a == b:
                        common += 1
                    else:
                        break
                max_len = max(len(model_upper), len(series_upper))
                if max_len > 0:
                    score = int(common / max_len * 50)

            if score > best_score:
                best_score = score
                best_key = key

    return best_key if best_score >= 50 else None


def _load_json_silently(filepath: str) -> dict:
    """加载 JSON，失败返回空 dict。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _exact_model_match(
    model: str,
    candidates: dict[str, list[str]],
) -> Optional[str]:
    """在候选项的 models 列表中精确匹配型号，返回文件名。"""
    model_upper = model.strip().upper()
    for fname, models in candidates.items():
        if any(m.strip().upper() == model_upper for m in models):
            return fname
    return None


def _filter_by_manufacturer(
    directory: str,
    idn_manufacturer: str,
) -> dict[str, dict]:
    """扫描目录，返回 manufacturer 匹配的候选文件及其 JSON 数据。

    优先匹配 JSON 中新增的 `manufacturer` 字段；
    若没有匹配到，回退到文件名前缀匹配（_identify_brand）。
    """
    candidates: dict[str, dict] = {}
    brand = _identify_brand(idn_manufacturer)
    idn_mfr_upper = idn_manufacturer.strip().upper()

    if not os.path.isdir(directory):
        return candidates

    for fname in sorted(os.listdir(directory)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(directory, fname)
        data = _load_json_silently(fpath)

        # 优先用 manufacturer 字段匹配
        file_mfr = data.get("manufacturer", "")
        if file_mfr and file_mfr.strip().upper() in idn_mfr_upper:
            candidates[fname] = data
        elif file_mfr and idn_mfr_upper in file_mfr.strip().upper():
            candidates[fname] = data

    # manufacturer 字段没匹配到，回退到文件名前缀
    if not candidates and brand:
        for fname in sorted(os.listdir(directory)):
            if not fname.endswith(".json"):
                continue
            if fname.startswith(brand):
                fpath = os.path.join(directory, fname)
                data = _load_json_silently(fpath)
                if data.get("series"):
                    candidates[fname] = data

    # 再回退：全部文件
    if not candidates:
        for fname in sorted(os.listdir(directory)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(directory, fname)
            data = _load_json_silently(fpath)
            if data.get("series"):
                candidates[fname] = data

    return candidates


def detect_configs(
    commands_dir: str,
    profiles_dir: str,
    oscilloscope_idn: dict,
) -> tuple[Optional[dict], Optional[dict], Optional[str], Optional[str]]:
    """根据示波器 *IDN? 匹配指令集和特征配置。

    匹配优先级：
      1. models 字段精确匹配（新增字段）
      2. series 字段模糊匹配（回退）

    Returns:
        (cmd_osc, profile_data, cmd_filepath, profile_filepath)
        匹配失败则对应位置为 None。
    """
    model = oscilloscope_idn.get("model", "")
    manufacturer = oscilloscope_idn.get("manufacturer", "")

    # ── 指令集匹配 ──
    cmd_candidates = _filter_by_manufacturer(commands_dir, manufacturer)

    # 优先级 1：models 精确匹配
    cmd_models: dict[str, list[str]] = {}
    for fname, data in cmd_candidates.items():
        models = data.get("models", [])
        if isinstance(models, list) and models:
            cmd_models[fname] = models

    matched_cmd = _exact_model_match(model, cmd_models)

    # 优先级 2：series 模糊匹配（回退）
    if not matched_cmd:
        cmd_series: dict[str, list[str]] = {}
        for fname, data in cmd_candidates.items():
            series = data.get("series", [])
            if isinstance(series, str):
                series = [series]
            if series:
                cmd_series[fname] = series
        matched_cmd = _fuzzy_match_series(model, cmd_series)

    if not matched_cmd:
        console.print(
            f"[yellow]⚠[/yellow] 未找到与型号 [cyan]{model}[/cyan] 匹配的指令集"
        )

    # ── 特征配置匹配 ──
    profile_candidates = _filter_by_manufacturer(profiles_dir, manufacturer)

    # 优先级 1：models 精确匹配
    profile_models: dict[str, list[str]] = {}
    for fname, data in profile_candidates.items():
        models = data.get("models", [])
        if isinstance(models, list) and models:
            profile_models[fname] = models

    matched_profile = _exact_model_match(model, profile_models)

    # 优先级 2：series 模糊匹配（回退）
    if not matched_profile:
        profile_series: dict[str, str] = {}
        for fname, data in profile_candidates.items():
            series = data.get("series", "")
            if series:
                profile_series[fname] = series
        matched_profile = _fuzzy_match_series(model, profile_series)

    if not matched_profile:
        console.print(
            f"[yellow]⚠[/yellow] 未找到与型号 [cyan]{model}[/cyan] 匹配的特征配置"
        )

    cmd_osc = None
    profile_data = None
    cmd_filepath = None
    profile_filepath = None

    if matched_cmd:
        cmd_filepath = os.path.join(commands_dir, matched_cmd)
        cmd_osc = _load_json_silently(cmd_filepath)
    if matched_profile:
        profile_filepath = os.path.join(profiles_dir, matched_profile)
        profile_data = _load_json_silently(profile_filepath)

    return cmd_osc, profile_data, cmd_filepath, profile_filepath


def print_auto_detection_summary(
    idn_osc: dict,
    idn_cal: dict,
    cmd_file: Optional[str],
    profile_file: Optional[str],
    cal_file: Optional[str],
    probe: Optional[str],
) -> None:
    """打印自动识别的配置摘要，供用户确认。"""
    table = Table(title="[bold green]自动识别结果[/bold green]", show_lines=True)
    table.add_column("项目", style="cyan bold")
    table.add_column("内容", style="white")

    osc_info = idn_osc.get("manufacturer", "?") + " " + idn_osc.get("model", "?")
    cal_info = idn_cal.get("manufacturer", "?") + " " + idn_cal.get("model", "?")

    table.add_row("示波器", osc_info)
    table.add_row("示波器序列号", idn_osc.get("serial", "?"))
    table.add_row("校准仪", cal_info)
    table.add_row("校准仪序列号", idn_cal.get("serial", "?"))
    table.add_row("指令集配置", os.path.basename(cmd_file) if cmd_file else "[red]未匹配[/red]")
    table.add_row("特征配置", os.path.basename(profile_file) if profile_file else "[red]未匹配[/red]")
    table.add_row("校准仪配置", os.path.basename(cal_file) if cal_file else "[red]未匹配[/red]")
    table.add_row("探头", probe or "（待选择）")

    console.print()
    console.print(table)
