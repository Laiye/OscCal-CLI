"""配置结构校验：加载时（config.py）与测试（test_all_configs.py）共用同一套规则。

每个校验函数返回错误消息列表；空列表表示配置合法。
"""

from __future__ import annotations

import math
import re
from typing import TypeGuard

REQUIRED_COMMAND_KEYS = {"name", "description", "type", "series", "feature", "keyword", "actions"}
# 必需 keyword；其余 keyword（如 meas_pos_overshoot、meas_freq）按机型能力可选。
# 省略 meas_pos_overshoot 表示机型没有正过冲测量：瞬态项目只记录上升时间，
# 过冲列记为"不适用"（例：泰克 TBS1000/TDS1000/TDS2000/TPS2000 系列的基本测量类型组）。
REQUIRED_KEYWORDS = {
    "imp_fif",
    "imp_meg",
    "acquisition_mode_average",
    "meas_amp",
    "meas_period",
    "meas_mean",
    "meas_risetime",
    "meas_max",
    "meas_min",
    "acquire_stop_after_single",
}
VALID_COMM_TYPES = {"pyvisa", "socket"}
VALID_MEAS_MODES = {"merge", "split"}
VALID_ACTION_TYPES = {"write", "query"}

# profiles/ 只声明硬件事实：校准点来自 specs/，标准器能力来自 calibrators/，
# 参考指标来自 specs.reference_limits。Profile 里不再允许出现 points / calibration_limits。
REQUIRED_PROFILE_KEYS = {
    "name",
    "description",
    "factor",
    "series",
    "channels",
    "imp_has_50",
    "bandwidth_hz",
    "vertical_div",
    "horizontal_div",
    "vertical_scales",
    "horizontal_scales",
    "probe_default",
    "init_time",
}
DEPRECATED_PROFILE_KEYS = {"points", "calibration_limits", "bandwidth", "bd_step", "bd_scan"}

# ── 校准规范配置（specs/*.json）──
# 规范只声明"口径"，硬件能力来自 profiles/、标准器能力来自 calibrators/。
REQUIRED_SPEC_KEYS = {"name", "spec_code", "items", "deviations"}
# 规范项目键：既允许规范自身的条目名，也允许与 registry 同名的项目键。
VALID_SPEC_ITEM_KEYS = {
    "visual_check",
    "input_impedance",
    "dc_gain",
    "dc_offset",
    "freq_response_bandwidth",
    "enob",
    "rise_time",
    "timebase_error",
    "self_cal_signal",
    "delta_v",
    "delta_t",
    "random_noise",
    "amp",
    "delta_time",
    "bandwidth",
    "transient",
}
# 取点策略：见 specs/ 中各项的 points.strategy。
VALID_POINT_STRATEGIES = {
    "explicit",
    "screen_fraction",
    "scale_list",
    "bw_ratio",
    "derived",
    "fixed",
    "channel_x_impedance",
    "channel_x_edge_speed",
}
# 规范表 1 注明"技术指标仅供参考，不作为符合性判定依据"。
VALID_LIMIT_SEMANTICS = {"reference_only"}

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


_MANUFACTURER_ALIASES = {"TEK": "TEKTRONIX", "ZHIYUAN": "ZLG"}


def normalize_token(value: object) -> str:
    """型号/厂商归一化：转大写并去除非字母数字字符。

    同一型号在不同固件里的 *IDN? 写法可能不同（例如泰克 TBS1102 会上报
    "TBS 1102"），因此执行前校验与 --auto 自动识别共用这一条归一化规则。
    """
    if not isinstance(value, str):
        return ""
    return "".join(c for c in value.upper() if c.isalnum())


def manufacturer_matches(expected: str, actual: str) -> bool:
    """兼容已支持设备的厂商简写，拒绝跨厂商配对。"""
    a = _MANUFACTURER_ALIASES.get(normalize_token(expected), normalize_token(expected))
    b = _MANUFACTURER_ALIASES.get(normalize_token(actual), normalize_token(actual))
    return bool(a and b and (a in b or b in a))


def model_matches(expected: str, actual: str, min_prefix: int = 4) -> bool:
    """型号家族匹配：完全一致，或较短者为较长者的前缀且长度不低于 min_prefix。

    仅用于 series 回退比较，兼容同一型号在 *IDN? 中上报的变体（例如 Fluke 9500B
    既有上报 "9500B"、也有上报 "9500" 的固件）；配置存在 models 时仍按精确白名单比较。
    """
    a, b = normalize_token(actual), normalize_token(expected)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= min_prefix and long.startswith(short)


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
        errors.append(f"{label} 厂商与配置不匹配: {mfr}（配置: {expected_mfr}）")
    models = config.get("models")
    if models:
        supported = [v for v in models if isinstance(v, str) and v.strip()]
        if not any(normalize_token(v) == normalize_token(model) for v in supported):
            errors.append(
                f"{label} 型号 {model} 不在配置 models 中（支持: {', '.join(supported)}）"
            )
    elif label == "校准仪":
        series = config.get("series", [config.get("name", "")])
        series = [series] if isinstance(series, str) else series
        supported = [v for v in series if isinstance(v, str) and v.strip()]
        if not any(model_matches(v, model) for v in supported):
            errors.append(f"校准仪型号 {model} 与配置不匹配（配置支持: {', '.join(supported)}）")
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
        # 幅度测量换算系数：有效值类测量（CRMs，对称方波时等于幅度）需乘 2 才是
        # 标准值的峰峰值口径；峰峰值类测量（PK2pk/AMPlitude）不声明即为 1。
        if "meas_amp_scale" in feature and (
            not _is_number(feature["meas_amp_scale"]) or feature["meas_amp_scale"] <= 0
        ):
            errors.append("feature.meas_amp_scale 必须为有限正数")
        # 写入间隔（毫秒）：部分机型背靠背连续写入会静默丢指令，由指令集声明节流值。
        if "write_delay_ms" in feature and (
            not _is_number(feature["write_delay_ms"]) or not 0 <= feature["write_delay_ms"] <= 5000
        ):
            errors.append("feature.write_delay_ms 必须为 0~5000 的有限数值")

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


def _validate_scale_list(data: dict, field: str) -> list[str]:
    values = data.get(field)
    if not isinstance(values, list) or not values:
        return [f"{field} 必须为非空数值列表"]
    if not all(_is_number(v) and v > 0 for v in values):
        return [f"{field} 含非正数或非数值"]
    if values != sorted(values):
        return [f"{field} 未升序"]
    if len(values) != len(set(values)):
        return [f"{field} 有重复档位"]
    return []


def validate_profile(data: dict) -> list[str]:
    """校验示波器 Profile：只允许声明硬件事实，返回错误列表。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["配置必须是 JSON 对象"]

    missing = REQUIRED_PROFILE_KEYS - set(data.keys())
    if missing:
        errors.append(f"缺少字段: {sorted(missing)}")
        return errors

    errors.extend(_validate_identity(data))
    if not isinstance(data.get("series"), str) or not data["series"].strip():
        errors.append("Profile series 必须为非空字符串")

    deprecated = sorted(DEPRECATED_PROFILE_KEYS & set(data.keys()))
    if deprecated:
        errors.append(f"已废弃字段: {deprecated}（校准点取自 specs/，限值取自规范参考指标）")

    channels = data.get("channels")
    if not _is_count(channels) or channels == 0:
        errors.append("channels 必须为正整数")
    for field, default in (("init_time", 2), ("probe_default", 1)):
        value = data.get(field, default)
        if not _is_number(value) or value < 0 or (field == "probe_default" and value == 0):
            errors.append(f"{field} 数值非法")
    if not isinstance(data.get("imp_has_50"), bool):
        errors.append("imp_has_50 必须为布尔值")
    for field, default in (("vertical_div", 8), ("horizontal_div", 10)):
        value = data.get(field, default)
        if not _is_number(value) or value <= 2:
            errors.append(f"{field} 必须为大于 2 的数值")
    bandwidth = data.get("bandwidth_hz")
    if not _is_number(bandwidth) or bandwidth <= 0:
        errors.append("bandwidth_hz 必须为有限正数")
    if "averages" in data and (
        not _is_count(data["averages"]) or not 2 <= data["averages"] <= 4096
    ):
        errors.append("averages 必须为 2~4096 的整数")
    if "skip_vertical_adjust" in data and not isinstance(data["skip_vertical_adjust"], bool):
        errors.append("skip_vertical_adjust 必须为布尔值")

    errors.extend(_validate_scale_list(data, "vertical_scales"))
    errors.extend(_validate_scale_list(data, "horizontal_scales"))
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


_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RECORD_TABLE_PATTERN = re.compile(r"^[AB]\.\d+$")


def validate_spec(data: dict) -> list[str]:
    """校验校准规范配置（specs/*.json），返回错误列表。

    只校验"口径"声明本身：条款号、取点策略、记录表号、偏离声明与参考指标语义。
    条目实际怎么测量由对应项目实现保证，不在此处校验。
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["配置必须是 JSON 对象"]

    missing = REQUIRED_SPEC_KEYS - set(data.keys())
    if missing:
        errors.append(f"缺少字段: {sorted(missing)}")
        return errors

    for field in ("name", "spec_code"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field} 必须为非空字符串")

    for field in ("issued", "effective"):
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, str) or not _DATE_PATTERN.match(value):
            errors.append(f"{field} 必须为 YYYY-MM-DD 格式")

    recall = data.get("recall_interval_months")
    if recall is not None and (not _is_count(recall) or recall == 0):
        errors.append("recall_interval_months 必须为正整数")

    deviations = data.get("deviations")
    if not isinstance(deviations, list) or not deviations:
        errors.append("deviations 必须为非空字符串列表")
    elif not all(isinstance(v, str) and v.strip() for v in deviations):
        errors.append("deviations 含空条目")

    semantics = data.get("limits_semantics")
    if semantics is not None:
        if not isinstance(semantics, dict):
            errors.append("limits_semantics 必须是对象")
        elif semantics.get("kind") not in VALID_LIMIT_SEMANTICS:
            errors.append(
                "limits_semantics.kind 必须为 reference_only（规范表 1 指标不作符合性判定依据）"
            )

    if "environment" in data and not isinstance(data["environment"], dict):
        errors.append("environment 必须是对象")

    items = data.get("items")
    if not isinstance(items, dict) or not items:
        errors.append("items 必须为非空对象")
        return errors

    unknown = sorted(set(items) - VALID_SPEC_ITEM_KEYS)
    if unknown:
        errors.append(f"items 含未知校准项目: {unknown}")

    for key, item in items.items():
        if not isinstance(item, dict):
            errors.append(f"items.{key} 必须是对象")
            continue
        clause = item.get("clause")
        if not isinstance(clause, str) or not clause.strip():
            errors.append(f"items.{key}.clause 必须为非空字符串")
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"items.{key}.title 必须为非空字符串")
        automatable = item.get("automatable")
        if not isinstance(automatable, bool):
            errors.append(f"items.{key}.automatable 必须为布尔值")
            continue
        if not automatable:
            continue
        points = item.get("points")
        if not isinstance(points, dict):
            errors.append(f"items.{key} 缺少 points 对象")
        else:
            strategy = points.get("strategy")
            if strategy not in VALID_POINT_STRATEGIES:
                errors.append(f"items.{key}.points.strategy 非法: {strategy!r}")
        record = item.get("record_table")
        if not isinstance(record, str) or not _RECORD_TABLE_PATTERN.match(record):
            errors.append(f"items.{key}.record_table 必须形如 A.3 或 B.4")
    return errors
