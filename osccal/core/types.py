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
    meas_amp_scale: float
    write_delay_ms: float


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
    bandwidth_hz: float
    max_sample_rate_hz: float
    vertical_scales: list[float]
    horizontal_scales: list[float]


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
    models: list[str]
    keyword: KeywordConfig
    probes: dict[str, ProbeConfig]
    impedance_rules: ImpedanceRules
    actions: dict[str, ActionConfig]


class SpecPointRule(TypedDict, total=False):
    """校准点取点规则：策略 + 该策略下的参数。"""

    strategy: str
    screen_fraction: float
    scales_v_per_div: list[float]
    horizontal_scales_s_per_div: list[float]
    ratios: list[float]
    reference_hz: float
    impedances: list[str]
    samples_n: int
    integer_cycles_n: int
    periods_m: int
    periods_on_screen: int
    zero_point: bool
    offset_nominal_divisions: int
    require_coprime: bool
    crossing: dict[str, object]


class SpecItem(TypedDict, total=False):
    """单个校准项目的规范口径（来自 specs/*.json）。"""

    clause: str
    title: str
    automatable: bool
    method: str
    record_table: str
    record_fields: list[str]
    stimulus: dict[str, object]
    points: SpecPointRule
    formula: dict[str, str]
    deviations: list[str]
    invalid_sentinel: float
    requires_user_action: dict[str, object]
    pending_confirm: str
    fallback_note: str
    note: str
    notes: list[str]
    conditions: list[str]


class SpecConfig(TypedDict, total=False):
    """校准规范配置（specs/*.json）：只声明规范口径，不含硬件能力。"""

    name: str
    spec_code: str
    title: str
    replaces: str
    issued: str
    effective: str
    recall_interval_months: int
    description: str
    environment: dict[str, object]
    deviations: list[str]
    limits_semantics: dict[str, str]
    reference_limits: dict[str, object]
    items: dict[str, SpecItem]
    verification: dict[str, object]
