"""配置结构校验：加载时（config.py）与测试（test_all_configs.py）共用同一套规则。

每个校验函数返回错误消息列表；空列表表示配置合法。
"""

from __future__ import annotations

import math
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

# 所有项目共用的动作；项目专用动作在执行前按所选项目检查。
OSC_ACTION_ARITIES = {
    "preset": 0,
    "set_channel": 2,
    "set_vertical_scale": 2,
    "set_trigger_source": 1,
    "set_horizontal_scale": 1,
    "set_acquisition_mode": 1,
    "set_number_of_acquisitions": 1,
    "set_vertical_position": 2,
    "set_probe_gain": 2,
    "set_impedance": 2,
    "set_meas_source": 1,
    "set_meas_type": 1,
    "get_value": 0,
    "get_value_from_item": 1,
    "get_value_from_item_and_source": 2,
    "set_meas_item_and_source": 2,
    "set_meas_vavg": 1,
    "get_value_vavg": 1,
    "set_acquire_stop_after": 1,
    "set_acquire_state": 1,
}
REQUIRED_OSC_ACTIONS = {
    "preset",
    "set_channel",
    "set_vertical_scale",
    "set_trigger_source",
    "set_horizontal_scale",
    "set_acquisition_mode",
    "set_number_of_acquisitions",
}
CAL_ACTION_ARITIES = {
    "preset": 0,
    "set_shap": 1,
    "set_freq": 1,
    "set_volt": 1,
    "set_output": 1,
    "set_impedance": 1,
    "set_squ_polarity": 1,
    "set_mark_period": 1,
    "set_edge_speed": 1,
}
ITEM_SIGNALS = {
    "amp": "SQU",
    "dc_gain": "DC",
    "delta_time": "MARK",
    "bandwidth": "SIN",
    "transient": "EDGE",
}


def manufacturer_matches(expected: str, actual: str) -> bool:
    """兼容已支持设备的厂商简写，拒绝跨厂商配对。"""

    def normalize(value):
        value = "".join(c for c in value.upper() if c.isalnum())
        return {"TEK": "TEKTRONIX", "ZHIYUAN": "ZLG"}.get(value, value)

    a, b = normalize(expected), normalize(actual)
    return bool(a and b and (a in b or b in a))


def validate_device_identity(config: dict, idn: dict, label: str) -> list[str]:
    """用识别查询结果核对配置；不发送设备设置指令。"""
    mfr, model = idn.get("manufacturer", ""), idn.get("model", "")
    if (
        not isinstance(mfr, str)
        or not mfr.strip()
        or not isinstance(model, str)
        or not model.strip()
    ):
        return [f"{label} 缺少有效厂商或型号，无法核对配置"]
    errors = []
    expected_mfr = config.get("manufacturer", config.get("factor", ""))
    if expected_mfr and not manufacturer_matches(expected_mfr, mfr):
        errors.append(f"{label} 厂商与配置不匹配: {mfr}")
    models = config.get("models")
    if models and model.strip().upper() not in [v.strip().upper() for v in models]:
        errors.append(f"{label} 型号 {model} 不在配置 models 中")
    if label == "校准仪" and not models:
        series = config.get("series", [config.get("name", "")])
        series = [series] if isinstance(series, str) else series
        if model.strip().upper() not in [v.strip().upper() for v in series]:
            errors.append(f"校准仪型号 {model} 与配置不匹配")
    return errors


def validate_selection(
    cmd: dict,
    profile: dict,
    calibrator: dict,
    channels: list[str],
    items: list[str],
    probe: str | None,
    bandwidth: float,
    bd_step: float,
) -> list[str]:
    """检查本轮通道、项目、探头及设备能力，供 CLI 在执行前统一调用。"""
    errors = []
    max_channels = profile.get("channels", 4)
    if not channels or any(
        not c.isdecimal() or c != str(int(c)) or not 1 <= int(c) <= max_channels for c in channels
    ):
        errors.append(f"通道必须为 1 至 {max_channels} 的整数")
    if len(channels) != len(set(channels)):
        errors.append("不能重复选择通道")
    if not items or any(i not in (*ITEM_SIGNALS, "all") for i in items):
        errors.append("存在未知或空的校准项目")
    if len(items) != len(set(items)) or ("all" in items and len(items) != 1):
        errors.append("项目不能重复，all 不能与其他项目混用")
    selected = list(ITEM_SIGNALS) if "all" in items else items
    if not _is_number(bandwidth) or bandwidth < 50e3:
        errors.append("带宽起点必须为至少 50 kHz 的有限数值")
    if not _is_number(bd_step) or bd_step < 1:
        errors.append("带宽步进必须为至少 1 Hz 的有限数值")
    if probe not in calibrator.get("probes", {}):
        errors.append(f"未知探头: {probe}")
        return errors
    rules = calibrator.get("impedance_rules", {}).get(probe, {})
    for item in selected:
        shape = ITEM_SIGNALS.get(item)
        if shape is None:
            continue
        supported = rules.get(shape, [])
        if not supported:
            errors.append(f"探头 {probe} 不支持项目 {item} 所需的 {shape} 模式")
        elif not profile.get("imp_has_50", False) and "1M" not in supported:
            errors.append(f"项目 {item} 存在阻抗不匹配：示波器仅支持 1MΩ，探头仅支持 50Ω")
    if profile.get("imp_has_50") and "set_impedance" not in cmd["actions"]:
        errors.append("Profile 支持 50Ω，但指令集缺少 set_impedance")
    if profile.get("probe_default", 1) != 1 and "set_probe_gain" not in cmd["actions"]:
        errors.append("默认探头倍率不是 1，但指令集缺少 set_probe_gain")
    if "transient" in selected:
        missing = {"set_vertical_position", "set_trigger_level", "set_acquire_stop_after"} - cmd[
            "actions"
        ].keys()
        if missing:
            errors.append(f"瞬态项目缺少 action: {sorted(missing)}")
    if "bandwidth" in selected:
        max_freq = calibrator["probes"][probe].get("max_frequency_hz", 0)
        if not _is_number(bandwidth) or not 50e3 <= bandwidth <= max_freq:
            errors.append("带宽起点须在 50 kHz 至探头最高频率之间")
    if calibrator.get("type") != "pyvisa":
        errors.append("当前 CLI 校准仪连接仅支持 pyvisa")
    return errors


def _is_number(value: object) -> TypeGuard[int | float]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_identity(data: dict) -> list[str]:
    errors = []
    for field in ("name", "description", "factor"):
        if field in data and (not isinstance(data[field], str) or not data[field].strip()):
            errors.append(f"{field} 必须为非空字符串")
    if "manufacturer" in data and (
        not isinstance(data["manufacturer"], str) or not data["manufacturer"].strip()
    ):
        errors.append("manufacturer 必须为非空字符串")
    if "models" in data:
        models = data["models"]
        if (
            not isinstance(models, list)
            or not models
            or not all(isinstance(v, str) and v.strip() for v in models)
        ):
            errors.append("models 必须为非空字符串列表")
    series = data.get("series")
    if "series" in data and not (
        isinstance(series, str)
        and series.strip()
        or isinstance(series, list)
        and series
        and all(isinstance(v, str) and v.strip() for v in series)
    ):
        errors.append("series 必须为非空字符串或字符串列表")
    return errors


def _validate_actions(actions: object, required: set[str], arities: dict[str, int]) -> list[str]:
    errors: list[str] = []
    if not isinstance(actions, dict):
        return ["actions 必须是对象"]
    missing = required - actions.keys()
    if missing:
        errors.append(f"缺少必需 action: {sorted(missing)}")
    for name, act in actions.items():
        if not isinstance(act, dict):
            errors.append(f"action {name}: 必须为对象")
            continue
        if act.get("name") != name:
            errors.append(f"action {name}: name 与 key 不一致")
        if act.get("type") not in ("write", "query"):
            errors.append(f"action {name}: 非法类型")
        if name in arities:
            if act.get("args_num") != arities[name]:
                errors.append(f"action {name}: args_num 应为 {arities[name]}")
            expected_type = "query" if name.startswith("get_") else "write"
            if act.get("type") != expected_type:
                errors.append(f"action {name}: type 应为 {expected_type}")
        commands = act.get("commands")
        if (
            not isinstance(commands, list)
            or not commands
            or not all(isinstance(v, str) for v in commands)
        ):
            errors.append(f"action {name}: commands 必须为非空字符串片段列表")
        elif not any(v.strip() for v in commands):
            errors.append(f"action {name}: commands 不能全为空白")
        elif not _is_count(act.get("commands_num")) or act["commands_num"] != len(commands):
            errors.append(f"action {name}: commands_num 与 commands 长度不一致")
        args = act.get("args")
        if not isinstance(args, list):
            errors.append(f"action {name}: args 必须为列表")
        elif not _is_count(act.get("args_num")) or act["args_num"] != len(args):
            errors.append(f"action {name}: args_num 与 args 长度不一致")
        elif not all(
            isinstance(v, list) and v and all(isinstance(x, str) and x for x in v) for v in args
        ):
            errors.append(f"action {name}: args 元素必须为非空字符串候选值列表")
        if isinstance(commands, list) and isinstance(args, list) and len(args) > len(commands):
            errors.append(f"action {name}: commands 片段不足，参数会被丢弃")
    return errors


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

    errors.extend(_validate_identity(data))
    if data.get("type") not in tuple(VALID_COMM_TYPES):
        errors.append(f"非法通信类型: {data.get('type')}")

    feature = data.get("feature")
    if not isinstance(feature, dict):
        errors.append("feature 必须是对象")
    elif feature.get("meas") not in tuple(VALID_MEAS_MODES):
        errors.append(f"非法测量模式: {feature.get('meas')}")
    else:
        if not _is_count(feature.get("return_value_index", 0)):
            errors.append("return_value_index 必须为非负整数")
        if feature.get("get_value", "ByItemAndSource") not in (
            "Direct",
            "ByItem",
            "ByItemAndSource",
            "ByChannelItem",
        ):
            errors.append("非法 get_value 模式")
        if feature.get("set_meas", "Channel") not in ("Channel", "ItemChannel"):
            errors.append("非法 set_meas 模式")

    keyword = data.get("keyword")
    if not isinstance(keyword, dict):
        errors.append("keyword 必须是对象")
        keyword = {}
    missing_kw = REQUIRED_KEYWORDS - set(keyword.keys())
    if missing_kw:
        errors.append(f"缺少必需 keyword: {sorted(missing_kw)}")
    if not all(isinstance(v, str) and v.strip() for v in keyword.values()):
        errors.append("keyword 的值必须为非空字符串")

    actions = data.get("actions")
    if not isinstance(actions, dict):
        errors.append("actions 必须是对象")
        return errors

    # 存在 set_acquire_state action 时必须提供 acquire_state_run keyword
    if "set_acquire_state" in actions and "acquire_state_run" not in keyword:
        errors.append("存在 set_acquire_state 但缺少 acquire_state_run keyword")

    errors.extend(_validate_actions(actions, REQUIRED_OSC_ACTIONS, OSC_ACTION_ARITIES))
    if isinstance(feature, dict):
        if feature.get("meas") == "merge":
            required_measurement = {"set_meas_source", "set_meas_type", "get_value"}
        else:
            required_measurement = {
                "get_value_from_item"
                if feature.get("get_value") == "ByItem"
                else "get_value_from_item_and_source",
                "set_meas_item_and_source"
                if feature.get("set_meas") == "ItemChannel"
                else "set_meas_source",
            }
        missing_measurement = required_measurement - actions.keys()
        if missing_measurement:
            errors.append(f"测量模式缺少 action: {sorted(missing_measurement)}")
    if (
        "set_trigger_level" in actions
        and isinstance(actions["set_trigger_level"], dict)
        and actions["set_trigger_level"].get("args_num") not in (1, 2)
    ):
        errors.append("set_trigger_level 的 args_num 必须为 1 或 2")
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

    errors.extend(_validate_identity(data))
    channels = data.get("channels", 4)
    if not isinstance(data.get("series"), str) or not data["series"].strip():
        errors.append("Profile series 必须为非空字符串")
    if "skip_vertical_adjust" in data and not isinstance(data["skip_vertical_adjust"], bool):
        errors.append("skip_vertical_adjust 必须为布尔值")
    if not _is_count(channels) or channels == 0:
        errors.append("channels 必须为正整数")
    for field, default in (("init_time", 2), ("probe_default", 1)):
        value = data.get(field, default)
        if not _is_number(value) or value < 0 or (field == "probe_default" and value == 0):
            errors.append(f"{field} 数值非法")
    for field in ("bandwidth", "bd_step"):
        if field in data and (not _is_number(data[field]) or data[field] <= 0):
            errors.append(f"{field} 必须为有限正数")
    if not isinstance(data.get("imp_has_50"), bool):
        errors.append("imp_has_50 必须为布尔值")
    if not _is_number(data.get("vertical_div")) or data["vertical_div"] <= 0:
        errors.append("vertical_div 必须为正数")
    if not _is_number(data.get("horizontal_div", 10)) or data.get("horizontal_div", 10) <= 0:
        errors.append("horizontal_div 必须为正数")
    for field, default in (("vertical_div", 8), ("horizontal_div", 10)):
        if _is_number(data.get(field, default)) and data.get(field, default) <= 2:
            errors.append(f"{field} 必须大于 2，保证标准值非零")
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
                elif pts != sorted(pts):
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

    errors.extend(_validate_identity(data))
    if data.get("type") not in tuple(VALID_COMM_TYPES):
        errors.append("非法校准仪通信类型")
    errors.extend(
        _validate_actions(data.get("actions"), set(CAL_ACTION_ARITIES), CAL_ACTION_ARITIES)
    )
    keyword = data.get("keyword")
    if not isinstance(keyword, dict):
        errors.append("keyword 必须是对象")
    elif "imp_fif" not in keyword or "imp_meg" not in keyword:
        errors.append("keyword 缺少 imp_fif/imp_meg")
    elif not all(isinstance(v, str) and v.strip() for v in keyword.values()):
        errors.append("keyword 的值必须为非空字符串")

    probes = data.get("probes")
    if not isinstance(probes, dict) or not probes:
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
            if shape not in tuple(ITEM_SIGNALS.values()):
                errors.append(f"{probe}/{shape} 信号模式非法")
            if not isinstance(supported, list) or not supported:
                errors.append(f"{probe}/{shape} 规则为空")
            elif not all(isinstance(v, str) and v in VALID_IMPEDANCES for v in supported):
                errors.append(f"{probe}/{shape} 含非法阻抗: {supported}")

    for probe, info in probes.items():
        if probe not in rules_root:
            errors.append(f"探头 {probe} 缺少 impedance_rules")
        if not isinstance(info, dict):
            errors.append(f"探头 {probe} 配置必须为对象")
            continue
        times = info.get("edge_rise_times")
        if not isinstance(times, list) or not times:
            errors.append(f"探头 {probe} 缺 edge_rise_times")
        elif not all(_is_number(t) and t > 0 for t in times):
            errors.append(f"探头 {probe} 上升时间非法")
        max_freq = info.get("max_frequency_hz", 0)
        if not _is_number(max_freq) or max_freq < 0:
            errors.append(f"探头 {probe} max_frequency_hz 必须为非负有限数值")
    return errors
