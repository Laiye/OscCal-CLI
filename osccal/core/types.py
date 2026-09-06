"""配置类型定义（TypedDict），为配置加载与校验提供类型提示。

所有 TypedDict 均使用 total=False：JSON 配置允许缺省字段，
且加载失败时返回的空 dict 在类型上合法。
"""

from __future__ import annotations

from typing import TypedDict


class ActionConfig(TypedDict, total=False):
    name: str
    type: str
    commands_num: int
    args_num: int
    commands: list[str]
    args: list[list[str]]


class FeatureConfig(TypedDict, total=False):
    meas: str
    return_value_index: int
    get_value: str
    set_meas: str


# 关键字映射：keyword 名 -> SCPI 助记符
KeywordConfig = dict[str, str]


class CommandConfig(TypedDict, total=False):
    name: str
    description: str
    manufacturer: str
    models: list[str]
    type: str
    series: list[str]
    feature: FeatureConfig
    keyword: KeywordConfig
    actions: dict[str, ActionConfig]


class CalibrationLimits(TypedDict, total=False):
    lower: float
    upper: float
    min_mhz: float


class PointsConfig(TypedDict, total=False):
    bandwidth: list[float]
    delta_amp: list[float]
    dc_gain: list[float]
    delta_time: list[float]


class ProfileConfig(TypedDict, total=False):
    name: str
    description: str
    manufacturer: str
    models: list[str]
    factor: str
    series: str
    channels: int
    imp_has_50: bool
    vertical_div: int
    horizontal_div: int
    probe_default: int
    init_time: float
    calibration_limits: dict[str, CalibrationLimits]
    points: PointsConfig
    bandwidth: int
    bd_step: int
    bd_scan: str
    skip_vertical_adjust: bool


class ProbeConfig(TypedDict, total=False):
    name: str
    description: str
    max_frequency: str
    max_frequency_hz: float
    edge_rise_times: list[float]


# 阻抗规则：探头 -> 信号模式 -> 支持的阻抗列表（"1M"/"50"）
ImpedanceRules = dict[str, dict[str, list[str]]]


class CalibratorConfig(TypedDict, total=False):
    name: str
    description: str
    type: str
    series: list[str]
    keyword: KeywordConfig
    probes: dict[str, ProbeConfig]
    impedance_rules: ImpedanceRules
    actions: dict[str, ActionConfig]
