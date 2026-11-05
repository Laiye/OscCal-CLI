"""校准方法目录：项目 -> 已实现的方法键与中文名。

方案（schemes/*.json）用这里的键声明"本项目跑哪些方法"；runner 用同一组键
判断是否执行某个方法。**只列已实现的方法**，规范里提到但程序未实现的方法
（如随机噪声的 RMS 读数法）不在此表，避免方案声明了却跑不了。

`PRIMARY_METHODS` 中的项目有"主记录值"概念：多个方法并列时，方案必须用
`primary` 指定哪一个填入报告的判定列；时基两法是规范并列方法，没有唯一值，
因此不在该集合中。
"""

from __future__ import annotations

ITEM_METHODS: dict[str, dict[str, str]] = {
    "input_impedance": {
        "calibrator_load_measure": "校准仪负载测量（7.3.1）",
    },
    "dc_gain": {
        "dc_two_point": "直流两点法（7.4.1）",
        "square_amplitude": "方波幅度法（7.4.2）",
        "multi_point_lsq": "多点最小二乘（7.4.3）",
    },
    "dc_offset": {
        "mean_readout": "平均值读数法（7.5.1）",
        "raw_lsq": "原始码值拟合（7.5.2）",
    },
    "freq_response_bandwidth": {
        "sine_sweep_half_power": "正弦扫频 + 半功率点（7.6）",
    },
    "enob": {
        "time_domain_lsq": "时域四参数最小二乘（7.7）",
    },
    "rise_time": {
        "fast_edge": "快沿 10%~90%（7.8）",
    },
    "timebase_error": {
        "frequency_readout": "频率读数法（7.9.1）",
        "waveform_fit": "波形拟合法（7.9.2）",
    },
    "delta_v": {
        "auto_amplitude": "自动幅度测量（7.11）",
    },
    "delta_t": {
        "auto_period": "自动周期测量（7.12）",
    },
    "random_noise": {
        "sample_stddev": "采样标准差（7.13 方法二）",
    },
}

#: 这些项目允许多方法并列，方案必须指定 primary 作为报告主记录值。
PRIMARY_METHODS = {"dc_gain", "dc_offset"}

#: 这些项目的方法在规范中是并列方法，不设 primary。
NO_PRIMARY_METHODS = {"timebase_error"}

#: 计划表用的短标签，避免终端表格被长条款/长名称挤到换行。
SHORT_LABELS = {
    "calibrator_load_measure": "负载测量",
    "dc_two_point": "直流两点",
    "square_amplitude": "方波幅度",
    "multi_point_lsq": "多点拟合",
    "mean_readout": "平均值",
    "raw_lsq": "码值拟合",
    "sine_sweep_half_power": "正弦扫频",
    "time_domain_lsq": "时域拟合",
    "fast_edge": "快沿",
    "frequency_readout": "频率读数",
    "waveform_fit": "波形拟合",
    "auto_amplitude": "自动幅度",
    "auto_period": "自动周期",
    "sample_stddev": "标准差",
}


def method_keys(item: str) -> set[str]:
    """返回某项目已实现的方法键集合。"""
    return set(ITEM_METHODS.get(item, {}))


def describe_methods(item: str, methods: list[str], primary: str | None = None) -> str:
    """把方法键列表渲染为终端/计划表用的中文文本。"""
    labels = ITEM_METHODS.get(item, {})
    text = " + ".join(labels.get(name, name) for name in methods) or "—"
    if primary:
        text += f"（主：{labels.get(primary, primary)}）"
    return text


def describe_methods_short(item: str, methods: list[str], primary: str | None = None) -> str:
    """计划表用的紧凑文本：单方法给短名，多方法给数量与主方法。"""

    def short(name: str) -> str:
        return SHORT_LABELS.get(name, name)

    if not methods:
        return "—"
    if len(methods) == 1:
        return short(methods[0])
    if primary:
        return f"{len(methods)}法·{short(primary)}"
    return f"{len(methods)}法并列"
