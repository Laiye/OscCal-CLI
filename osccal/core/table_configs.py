"""校准结果表格配置：终端（ITEM_CONFIGS）与 Excel（EXCEL_ITEM_CONFIGS）各一份。

列的**取值来源**由 `keys` 显式声明（对应各项目 runner 写入记录里的字段名），
不再依赖 dict 的插入顺序；`precision` 指向 `ITEM_PRECISION`，与导出共用同一套
显示精度：("sig", n) 保留 n 位有效数字、("dec", n) 保留 n 位小数、None 原样输出。

表标题沿用 JJF 1057-2026 附录 A 的原始记录编号与名称；`reference` 是该项目的
**参考指标文本**——规范表 1 明确"技术指标仅供参考，不作为符合性判定依据"，
因此终端与 Excel 都只做参考比对，不出具合格/不合格结论。

`filter_key` 用于跳过不适合进表格的辅助记录（例如频带宽度汇总行）。
"""

# 各校准项目的显示精度，按列顺序排列
ITEM_PRECISION = {
    "input_impedance": [None, None, None, ("sig", 4), ("sig", 4), ("sig", 3), ("dec", 3), None],
    "dc_gain": [
        None,
        None,
        None,
        ("sig", 3),
        ("sig", 3),
        ("sig", 3),
        ("dec", 6),
        ("dec", 3),
        ("dec", 4),
        ("dec", 3),
        ("dec", 4),
        ("dec", 3),
        ("dec", 6),
    ],
    "dc_offset": [
        None,
        None,
        ("sig", 3),
        ("sig", 3),
        ("sig", 3),
        ("sig", 3),
        ("sig", 3),
        ("sig", 3),
        ("dec", 3),
        ("dec", 6),
        ("dec", 6),
        ("dec", 4),
    ],
    "freq_response_bandwidth": [None, None, ("sig", 4), ("sig", 4), ("dec", 4), None],
    "enob": [None, None, None, ("sig", 3), ("sig", 4), ("sig", 3), ("sig", 3), ("dec", 2), None],
    "rise_time": [None, None, ("sig", 3), ("sig", 4), ("dec", 2), ("sig", 3)],
    "timebase_error": [None, None, ("sig", 3), ("sig", 4), ("sig", 4), ("dec", 2), ("dec", 2)],
    "delta_v": [None, None, None, ("sig", 3), ("sig", 3), ("sig", 3), ("dec", 3)],
    "delta_t": [None, None, ("sig", 3), None, ("sig", 4), ("sig", 4), ("dec", 3)],
    "random_noise": [None, None, ("sig", 3), ("sig", 3), None, ("sig", 3), ("dec", 4)],
}

ITEM_CONFIGS = {
    "input_impedance": {
        "title": "A.2 输入阻抗",
        "columns": [
            "序号",
            "通道",
            "阻抗状态",
            "标称值(Ω)",
            "实测电阻(Ω)",
            "实测电容(F)",
            "电阻误差(%)",
            "参考指标(±%)",
        ],
        "keys": [
            "index",
            "channel",
            "impedance",
            "nominal_ohm",
            "resistance_ohm",
            "capacitance_f",
            "error_pct",
            "tolerance_pct",
        ],
        "precision": ITEM_PRECISION["input_impedance"],
        "reference": "50 Ω ±1%，1 MΩ ±0.5%",
    },
    "dc_gain": {
        "title": "A.3 直流增益",
        "columns": [
            "序号",
            "通道",
            "阻抗",
            "挡位(V/div)",
            "标准值(Vpp)",
            "被校示值(Vpp)",
            "增益 G",
            "增益误差(%)",
            "方法一 G",
            "方法一误差(%)",
            "方法三 G",
            "方法三误差(%)",
            "截距 d(V)",
        ],
        "keys": [
            "index",
            "channel",
            "impedance",
            "scale",
            "std_value_vpp",
            "measured_vpp",
            "gain",
            "error_pct",
            "gain_m1",
            "error_m1_pct",
            "gain_m3",
            "error_m3_pct",
            "intercept_m3_v",
        ],
        "precision": ITEM_PRECISION["dc_gain"],
        "reference": "最大允许误差 ±1%",
    },
    "dc_offset": {
        "title": "A.4 直流偏置",
        "columns": [
            "序号",
            "通道",
            "挡位(V/div)",
            "满量程(V)",
            "零点读数(V)",
            "偏置标称(V)",
            "偏置实测(V)",
            "偏置误差(V)",
            "误差(%FS)",
            "偏置增益 G",
            "方法一 Δd(V)",
            "方法一 G",
        ],
        "keys": [
            "index",
            "channel",
            "scale",
            "full_scale_v",
            "zero_reading_v",
            "offset_nominal_v",
            "offset_measured_v",
            "offset_error_v",
            "error_pct",
            "gain",
            "offset_error_v_m1",
            "gain_m1",
        ],
        "precision": ITEM_PRECISION["dc_offset"],
        "reference": "最大允许误差 ±(1%×满量程)",
    },
    "freq_response_bandwidth": {
        "title": "A.5 频率响应、频带宽度",
        "columns": ["序号", "通道", "频率(Hz)", "幅值(Vpp)", "相对响应 G", "备注"],
        "keys": ["index", "channel", "frequency_hz", "amplitude_vpp", "response", "note"],
        "precision": ITEM_PRECISION["freq_response_bandwidth"],
        "reference": "带内幅度波动 ±3 dB 以内；半功率点 0.707",
        "filter_key": "summary",
    },
    "enob": {
        "title": "A.6 动态有效位数",
        "columns": [
            "序号",
            "通道",
            "阻抗",
            "量程(V)",
            "信号频率(Hz)",
            "信号幅度(Vpp)",
            "残差均方根(V)",
            "ENOB(bits)",
            "备注",
        ],
        "keys": [
            "index",
            "channel",
            "impedance",
            "full_scale_v",
            "signal_freq_hz",
            "signal_amplitude_vpp",
            "rms_error_v",
            "enob",
            "note",
        ],
        "precision": ITEM_PRECISION["enob"],
        "reference": "12 bits",
    },
    "rise_time": {
        "title": "A.7 上升时间",
        "columns": ["序号", "通道", "探头边沿(s)", "上升时间(s)", "过冲(%)", "脉冲幅度(Vpp)"],
        "keys": [
            "index",
            "channel",
            "edge_rise_time_s",
            "rise_time_s",
            "overshoot_pct",
            "amplitude_vpp",
        ],
        "precision": ITEM_PRECISION["rise_time"],
        "reference": "规范仅规定可测下限 >10 ps",
    },
    "timebase_error": {
        "title": "A.8 时基（采集速率）误差",
        "columns": [
            "序号",
            "通道",
            "时基挡位(s/div)",
            "信号频率(Hz)",
            "测得频率(Hz)",
            "方法一(ppm)",
            "方法二(ppm)",
        ],
        "keys": [
            "index",
            "channel",
            "timebase_s_per_div",
            "signal_freq_hz",
            "measured_freq_hz",
            "rel_ppm",
            "fit_ppm",
        ],
        "precision": ITEM_PRECISION["timebase_error"],
        "reference": "最大允许误差 ±1×10⁻⁶ ~ ±5×10⁻⁹",
    },
    "delta_v": {
        "title": "A.10 ΔV（幅度）测量",
        "columns": [
            "序号",
            "通道",
            "阻抗",
            "挡位(V/div)",
            "标称值(Vpp)",
            "实测值(Vpp)",
            "相对误差(%)",
        ],
        "keys": [
            "index",
            "channel",
            "impedance",
            "scale",
            "std_value_vpp",
            "measured_vpp",
            "error_pct",
        ],
        "precision": ITEM_PRECISION["delta_v"],
        "reference": "最大允许误差 ±(1%×读值±1 个量化阶梯)",
    },
    "delta_t": {
        "title": "A.11 Δt（时间）测量",
        "columns": [
            "序号",
            "通道",
            "时基挡位(s/div)",
            "周期数 M",
            "标准值(s)",
            "被测值(s)",
            "相对误差(%)",
        ],
        "keys": [
            "index",
            "channel",
            "timebase_s_per_div",
            "periods_m",
            "time_standard_s",
            "time_measured_s",
            "error_pct",
        ],
        "precision": ITEM_PRECISION["delta_t"],
        "reference": "最大允许误差 ±(0.2%×读值+1 个量化间隔)",
    },
    "random_noise": {
        "title": "A.12 随机噪声",
        "columns": [
            "序号",
            "通道",
            "挡位(V/div)",
            "满量程(V)",
            "样本数",
            "噪声(标准差, V)",
            "占满量程(%)",
        ],
        "keys": [
            "index",
            "channel",
            "vertical_scale",
            "full_scale_v",
            "samples",
            "noise_v",
            "error_pct",
        ],
        "precision": ITEM_PRECISION["random_noise"],
        "reference": "±(0.1%×满量程)",
    },
}

EXCEL_ITEM_CONFIGS = {
    name: {
        "title": config["title"],
        "headers": config["columns"],
        "keys": config["keys"],
        "precision": config["precision"],
        "reference": config["reference"],
        "filter_key": config.get("filter_key"),
    }
    for name, config in ITEM_CONFIGS.items()
}

#: 参考指标的统一说明，终端与 Excel 报告都会输出。
LIMITS_DISCLAIMER = "以上参考指标取自 JJF 1057-2026 表 1，仅供参照，不作为符合性判定依据。"

_SUPERSCRIPT = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def _number(value: object) -> float | None:
    """把配置里的数值转成 float；非数值/布尔返回 None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _sci(value: float) -> str:
    """把 1e-6 写成 1×10⁻⁶（参考指标文本用）。"""
    mantissa, exponent = f"{value:.1e}".split("e")
    return f"{float(mantissa):g}×10{str(int(exponent)).translate(_SUPERSCRIPT)}"


def reference_text(name: str, limits: dict | None) -> str:
    """按记录里的规范参考指标（`metadata.limits`）生成参考指标文本。

    参考指标只有规范一处来源（`specs/*.json:reference_limits`），随记录保存为
    `metadata.limits`；本函数把它渲染成终端/Excel 的文本。旧记录没有 limits 时
    回退到 `ITEM_CONFIGS` 的静态文本，保证历史记录仍可显示。
    """
    config = ITEM_CONFIGS.get(name)
    fallback = config["reference"] if config else ""
    data = limits if isinstance(limits, dict) else {}

    if name == "input_impedance":
        entry = data.get("input_impedance") or {}
        fifty = _number(entry.get("ohm_50_pct"))
        meg = _number(entry.get("ohm_1m_pct"))
        if fifty is None or meg is None:
            return fallback
        return f"50 Ω ±{fifty:g}%，1 MΩ ±{meg:g}%"

    if name == "dc_gain":
        value = _number((data.get("dc_gain") or {}).get("mpe_pct"))
        return fallback if value is None else f"最大允许误差 ±{value:g}%"

    if name == "dc_offset":
        value = _number((data.get("dc_offset") or {}).get("mpe_pct_of_full_scale"))
        return fallback if value is None else f"最大允许误差 ±({value:g}%×满量程)"

    if name == "freq_response_bandwidth":
        value = _number((data.get("freq_response_db") or {}).get("max_ripple_db"))
        if value is None:
            return fallback
        return f"带内波动 ±{value:g} dB；半功率点 0.707"

    if name == "enob":
        value = _number(data.get("enob_bits"))
        return fallback if value is None else f"{value:g} bits"

    if name == "rise_time":
        value = _number((data.get("rise_time_ps") or {}).get("min"))
        return fallback if value is None else f"可测下限 >{value:g} ps"

    if name == "timebase_error":
        entry = data.get("timebase_rel_error") or {}
        start = _number(entry.get("from"))
        stop = _number(entry.get("to"))
        if start is None or stop is None:
            return fallback
        return f"最大允许误差 ±{_sci(start)} ~ ±{_sci(stop)}"

    if name == "delta_v":
        entry = data.get("delta_v") or {}
        percent = _number(entry.get("mpe_pct_of_reading"))
        lsb = _number(entry.get("extra_lsb"))
        if percent is None or lsb is None:
            return fallback
        return f"最大允许误差 ±({percent:g}%×读值 ± {lsb:g} 个量化阶梯)"

    if name == "delta_t":
        entry = data.get("delta_t") or {}
        percent = _number(entry.get("mpe_pct_of_reading"))
        lsb = _number(entry.get("extra_lsb"))
        if percent is None or lsb is None:
            return fallback
        return f"最大允许误差 ±({percent:g}%×读值 + {lsb:g} 个量化间隔)"

    if name == "random_noise":
        value = _number((data.get("random_noise") or {}).get("mpe_pct_of_full_scale"))
        return fallback if value is None else f"±{value:g}%×满量程"

    return fallback


def base_item_name(result_key: str) -> str:
    """把多通道结果键 `<item>_ch<N>` 还原为项目名。"""
    return result_key.split("_ch")[0]


def row_values(config: dict, row: dict) -> list:
    """按 `keys` 从记录行取值；缺失字段返回空串而不是崩溃。"""
    values = []
    for key in config["keys"]:
        value = row.get(key, "")
        if key == "impedance" and isinstance(value, str):
            value = {"1M": "1 MΩ", "50": "50 Ω"}.get(value, value)
        values.append(value)
    return values


def select_rows(config: dict, rows: list) -> list[dict]:
    """过滤辅助记录（如带宽汇总行），只保留真正的数据行。"""
    filter_key = config.get("filter_key")
    selected = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if filter_key and filter_key in row:
            continue
        selected.append(row)
    return selected
