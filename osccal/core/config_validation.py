"""配置结构校验：加载时（config.py）与测试（test_all_configs.py）共用同一套规则。

每个校验函数返回错误消息列表；空列表表示配置合法。
"""

from __future__ import annotations

from typing import TypeGuard

REQUIRED_COMMAND_KEYS = {"name", "description", "type", "series", "feature", "keyword", "actions"}
REQUIRED_KEYWORDS = {
    "imp_fif",
    "imp_meg",
    "acquisition_mode_average",
    "meas_amp",
    "meas_period",
    "meas_mean",
    "meas_risetime",
    "meas_pos_overshoot",
    "meas_max",
    "meas_min",
    "acquire_stop_after_single",
}
VALID_COMM_TYPES = {"pyvisa", "socket"}
VALID_MEAS_MODES = {"merge", "split"}
VALID_ACTION_TYPES = {"write", "query"}

REQUIRED_PROFILE_KEYS = {
    "name",
    "description",
    "factor",
    "series",
    "imp_has_50",
    "vertical_div",
    "probe_default",
    "init_time",
    "calibration_limits",
    "points",
}
REQUIRED_LIMIT_ITEMS = {"amp", "dc_gain", "delta_time", "bandwidth", "transient"}
REQUIRED_POINT_TABLES = {"bandwidth", "delta_amp", "dc_gain", "delta_time"}

REQUIRED_CALIBRATOR_KEYS = {
    "name",
    "description",
    "type",
    "keyword",
    "probes",
    "impedance_rules",
    "actions",
}
VALID_IMPEDANCES = {"1M", "50"}


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_commands(data: dict) -> list[str]:
    """校验指令集配置结构，返回错误列表。

    全程使用 .get + 类型判断，畸形 JSON（字段缺失/类型错误）只返回错误消息，
    不抛异常，保证"加载即校验、指出具体字段"。
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["配置必须是 JSON 对象"]

    missing = REQUIRED_COMMAND_KEYS - set(data.keys())
    if missing:
        errors.append(f"缺少顶层字段: {sorted(missing)}")
        return errors

    if data.get("type") not in VALID_COMM_TYPES:
        errors.append(f"非法通信类型: {data.get('type')}")

    feature = data.get("feature")
    if not isinstance(feature, dict):
        errors.append("feature 必须是对象")
    elif feature.get("meas") not in VALID_MEAS_MODES:
        errors.append(f"非法测量模式: {feature.get('meas')}")

    keyword = data.get("keyword")
    if not isinstance(keyword, dict):
        errors.append("keyword 必须是对象")
        keyword = {}
    missing_kw = REQUIRED_KEYWORDS - set(keyword.keys())
    if missing_kw:
        errors.append(f"缺少必需 keyword: {sorted(missing_kw)}")

    actions = data.get("actions")
    if not isinstance(actions, dict):
        errors.append("actions 必须是对象")
        return errors

    # 存在 set_acquire_state action 时必须提供 acquire_state_run keyword
    if "set_acquire_state" in actions and "acquire_state_run" not in keyword:
        errors.append("存在 set_acquire_state 但缺少 acquire_state_run keyword")

    for aname, act in actions.items():
        if not isinstance(act, dict):
            errors.append(f"action {aname}: 必须为对象")
            continue
        if act.get("name") != aname:
            errors.append(f"action {aname}: name={act.get('name')!r} != key")
        if act.get("type") not in VALID_ACTION_TYPES:
            errors.append(f"action {aname}: 非法类型 {act.get('type')}")

        commands = act.get("commands")
        if not isinstance(commands, list) or not commands:
            errors.append(f"action {aname}: commands 为空或非列表")
        elif act.get("commands_num") != len(commands):
            errors.append(f"action {aname}: commands_num 与 commands 长度不一致")

        args = act.get("args")
        if not isinstance(args, list):
            errors.append(f"action {aname}: args 必须为列表")
        elif act.get("args_num") != len(args):
            errors.append(f"action {aname}: args_num 与 args 长度不一致")
        elif args and not all(isinstance(c, list) for c in args):
            errors.append(f"action {aname}: args 元素必须为候选值列表")
    return errors


def validate_profile(data: dict) -> list[str]:
    """校验特征配置结构，返回错误列表（畸形字段只报错不抛异常）。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["配置必须是 JSON 对象"]

    missing = REQUIRED_PROFILE_KEYS - set(data.keys())
    if missing:
        errors.append(f"缺少字段: {sorted(missing)}")
        return errors

    if not isinstance(data.get("imp_has_50"), bool):
        errors.append("imp_has_50 必须为布尔值")
    if not _is_number(data.get("vertical_div")) or data["vertical_div"] <= 0:
        errors.append("vertical_div 必须为正数")
    if not _is_number(data.get("horizontal_div", 10)) or data.get("horizontal_div", 10) <= 0:
        errors.append("horizontal_div 必须为正数")
    if data.get("bd_scan", "bisect") not in ("bisect", "linear"):
        errors.append(f"非法带宽扫描模式 bd_scan: {data.get('bd_scan')}")

    limits = data.get("calibration_limits")
    if not isinstance(limits, dict):
        errors.append("calibration_limits 必须是对象")
    else:
        missing_lim = REQUIRED_LIMIT_ITEMS - set(limits.keys())
        if missing_lim:
            errors.append(f"calibration_limits 缺少项: {sorted(missing_lim)}")
        else:
            for item in ("amp", "dc_gain", "delta_time"):
                lim = limits.get(item)
                if not isinstance(lim, dict):
                    errors.append(f"{item} 限值必须是对象")
                    continue
                lower, upper = lim.get("lower"), lim.get("upper")
                if not (_is_number(lower) and _is_number(upper)):
                    errors.append(f"{item} 限值 lower/upper 必须为数值")
                    continue
                if not lower < upper:
                    errors.append(f"{item} 限值区间非法")
                if abs(lower) > 20 or abs(upper) > 20:
                    errors.append(f"{item} 限值数量级异常")
            bw = limits.get("bandwidth")
            if (
                not isinstance(bw, dict)
                or not _is_number(bw.get("min_mhz", 0))
                or bw.get("min_mhz", 0) <= 0
            ):
                errors.append("bandwidth min_mhz 必须为正数")

    points = data.get("points")
    if not isinstance(points, dict):
        errors.append("points 必须是对象")
    else:
        missing_pts = REQUIRED_POINT_TABLES - set(points.keys())
        if missing_pts:
            errors.append(f"points 缺少点表: {sorted(missing_pts)}")
        else:
            for table in REQUIRED_POINT_TABLES:
                pts = points.get(table)
                if not isinstance(pts, list) or not pts:
                    errors.append(f"{table} 点表为空")
                    continue
                if not all(_is_number(v) and v > 0 for v in pts):
                    errors.append(f"{table} 含非正数")
                if pts != sorted(pts):
                    errors.append(f"{table} 未升序")
    return errors


def validate_calibrator(data: dict) -> list[str]:
    """校验校准仪配置结构，返回错误列表（畸形字段只报错不抛异常）。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["配置必须是 JSON 对象"]

    missing = REQUIRED_CALIBRATOR_KEYS - set(data.keys())
    if missing:
        errors.append(f"缺少字段: {sorted(missing)}")
        return errors

    keyword = data.get("keyword")
    if not isinstance(keyword, dict):
        errors.append("keyword 必须是对象")
    elif "imp_fif" not in keyword or "imp_meg" not in keyword:
        errors.append("keyword 缺少 imp_fif/imp_meg")

    probes = data.get("probes")
    if not isinstance(probes, dict):
        errors.append("probes 必须是对象")
        probes = {}

    rules_root = data.get("impedance_rules")
    if not isinstance(rules_root, dict):
        errors.append("impedance_rules 必须是对象")
        rules_root = {}

    for probe, rules in rules_root.items():
        if probe not in probes:
            errors.append(f"impedance_rules 引用了未定义的探头 {probe}")
            continue
        if not isinstance(rules, dict) or not rules:
            errors.append(f"探头 {probe} 无任何模式规则")
            continue
        for shape, supported in rules.items():
            if not isinstance(supported, list) or not supported:
                errors.append(f"{probe}/{shape} 规则为空")
            elif not set(supported) <= VALID_IMPEDANCES:
                errors.append(f"{probe}/{shape} 含非法阻抗: {supported}")

    for probe, info in probes.items():
        if not isinstance(info, dict):
            errors.append(f"探头 {probe} 配置必须为对象")
            continue
        times = info.get("edge_rise_times")
        if not isinstance(times, list) or not times:
            errors.append(f"探头 {probe} 缺 edge_rise_times")
        elif not all(_is_number(t) and t > 0 for t in times):
            errors.append(f"探头 {probe} 上升时间非法")
    return errors
