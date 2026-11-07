"""校准点解析器：把「校准方案 + 规范口径 + 硬件特征 + 标准器能力」合成为可执行点表。

输入四方数据，缺一不可：
- `schemes/*.json`：本轮方案的方法选择、取点策略、屏占比、比值、基准频率；
- `specs/*.json`：规范要求的条款号与参考指标（供点参数与报告使用）；
- `characteristics/*.json`：被校示波器的硬件特征（通道数、格线、档位集合、标称带宽）；
- `calibrators/*.json`：标准器的输出能力（电压/频率上限、探头边沿速度）。

输出一份纯 JSON 可序列化的计划，含每个点的具体数值、所选方法与**被跳过的点及原因**。
解析过程不连接任何仪器，可用 `osccal plan` 离线核对。

不做隐式降级：某个点如果超出标准器能力，一定记进 `skipped` 并说明理由，
不会静默少跑一个点。
"""

from __future__ import annotations

from osccal.core.methods import method_output_shape

SHAPE_TO_OUTPUT = {
    "DC": "DC",
    "SQU": "SQU",
    "SIN": "SIN",
    "EDGE": "EDGE",
}

# 取点策略的说明，供 `osccal plan` 与文档共用。
IMPEDANCE_LABELS = {"1M": "1 MΩ", "50": "50 Ω"}

STRATEGY_DESCRIPTIONS = {
    "scale_list": "按垂直/水平档位列表逐档取点",
    "bw_ratio": "相对标称带宽的比例频点 + 固定基准",
    "derived": "现场读回后按规范公式计算（不在配置里写死）",
    "fixed": "固定条件点",
    "channel_x_impedance": "每通道 × 每种阻抗状态",
    "channel_x_edge_speed": "每通道 × 每个边沿速度档",
}

#: 计划表的短标签。
STRATEGY_LABELS = {
    "scale_list": "档位列表",
    "bw_ratio": "带宽比例",
    "derived": "现场计算",
    "fixed": "固定点",
    "channel_x_impedance": "通道×阻抗",
    "channel_x_edge_speed": "通道×边沿",
}


def _num(value) -> float:
    return float(value)


def _output_limits(calibrator: dict, shape: str, impedance: str) -> dict:
    """返回某波形在指定阻抗下的输出能力；未声明视为无限制。"""
    key = SHAPE_TO_OUTPUT.get(shape, shape)
    table = calibrator.get("output_limits", {}).get(key)
    if not isinstance(table, dict):
        return {}
    limits = table.get(impedance)
    return limits if isinstance(limits, dict) else {}


def _impedance_supported(characteristics: dict, impedance: str) -> bool:
    if impedance == "50":
        return bool(characteristics.get("imp_has_50"))
    return True


def _vertical_scales_for(characteristics: dict, impedance: str) -> list[float]:
    """返回某阻抗状态下可设置的垂直挡位。

    50 Ω 输入的垂直挡位上限通常低于 1 MΩ（MDO3000 系列为 1 V/div），由
    `characteristics.max_vertical_scale_50` 声明；未声明时按全挡位处理。
    """
    scales = [_num(v) for v in characteristics.get("vertical_scales") or []]
    if impedance != "50":
        return scales
    cap = characteristics.get("max_vertical_scale_50")
    if cap is None:
        return scales
    return [scale for scale in scales if scale <= _num(cap) + 1e-12]


def _check_amplitude(
    amplitude_vpp: float, calibrator: dict, shape: str, impedance: str
) -> str | None:
    """返回跳过原因；可用则返回 None。"""
    limits = _output_limits(calibrator, shape, impedance)
    if not limits:
        return None
    label = IMPEDANCE_LABELS.get(impedance, impedance)
    unit = "V" if shape == "DC" else "Vpp"
    lo = limits.get("min_vpp", limits.get("min_v"))
    hi = limits.get("max_vpp", limits.get("max_v"))
    if hi is not None and amplitude_vpp > _num(hi):
        return f"标准值 {amplitude_vpp:.4g} {unit} 超出 {label} 上限 {_num(hi):.4g} {unit}"
    if lo is not None and amplitude_vpp < _num(lo):
        return f"标准值 {amplitude_vpp:.4g} {unit} 低于 {label} 下限 {_num(lo):.4g} {unit}"
    return None


def _check_frequency(freq_hz: float, calibrator: dict, impedance: str, shape: str) -> str | None:
    limits = _output_limits(calibrator, shape, impedance)
    if not limits:
        return None
    hi = limits.get("max_freq_hz")
    lo = limits.get("min_freq_hz")
    if hi is not None and freq_hz > _num(hi):
        return f"{freq_hz:.4g} Hz 超出输出上限 {_num(hi):.4g} Hz"
    if lo is not None and freq_hz < _num(lo):
        return f"{freq_hz:.4g} Hz 低于输出下限 {_num(lo):.4g} Hz"
    return None


def _point(values: dict, **extra) -> dict:
    point = dict(values)
    point.update(extra)
    return point


def _resolve_channel_x_impedance(
    item: dict, characteristics: dict, channels: list[str], reference_limits: dict
) -> dict:
    wanted = item.get("points", {}).get("impedances", ["1M", "50"])
    tolerance_limits = reference_limits.get("input_impedance") or {}
    points, skipped = [], []
    for channel in channels:
        for impedance in wanted:
            if not _impedance_supported(characteristics, impedance):
                skipped.append({"channel": channel, "reason": f"机型不支持 {impedance} 输入阻抗"})
                continue
            point = {"channel": channel, "impedance": impedance}
            # 参考指标来自规范（reference_limits），随点下发，避免 runner 里再写死一份
            key = "ohm_1m_pct" if impedance == "1M" else "ohm_50_pct"
            tolerance = tolerance_limits.get(key)
            if isinstance(tolerance, (int, float)) and not isinstance(tolerance, bool):
                point["tolerance_pct"] = float(tolerance)
            points.append(_point(point))
    return {"points": points, "skipped": skipped}


def _resolve_scale_list(
    item: dict,
    characteristics: dict,
    calibrator: dict,
    channels: list[str],
    shape: str | None = None,
) -> dict:
    rule = item.get("points", {})
    shape = shape or item.get("stimulus", {}).get("shape", "DC")
    fraction = rule.get("screen_fraction")
    vertical_scales = rule.get("scales_v_per_div")
    horizontal_scales = rule.get("horizontal_scales_s_per_div")
    wanted_impedances = rule.get("impedances", ["1M"])
    vertical_div = _num(characteristics.get("vertical_div", 8))
    horizontal_div = _num(characteristics.get("horizontal_div", 10))

    points: list[dict] = []
    skipped: list[dict] = []

    if vertical_scales is not None:
        available = set(_num(v) for v in characteristics.get("vertical_scales", []))
        nominal_divisions = rule.get("offset_nominal_divisions")
        for channel in channels:
            for scale in vertical_scales:
                scale = _num(scale)
                if available and scale not in available:
                    skipped.append(
                        {"channel": channel, "scale": scale, "reason": "机型无此垂直档位"}
                    )
                    continue
                std = float(fraction) * vertical_div * scale if fraction is not None else None
                # 直流偏置没有屏占比，但 50 Ω 下仍要按偏置标称值核对标准器输出上限。
                # 直流增益的两点/多点法用双极性直流电平，幅度上限看单侧电平（std/2），
                # 不能拿 Vpp 去卡 DC 输出的 ±V 上限。
                if std is not None:
                    limit_amplitude = std / 2.0 if shape == "DC" else std
                elif nominal_divisions is not None:
                    limit_amplitude = _num(nominal_divisions) * scale
                else:
                    limit_amplitude = None
                for impedance in wanted_impedances:
                    if not _impedance_supported(characteristics, impedance):
                        skipped.append(
                            {
                                "channel": channel,
                                "scale": scale,
                                "reason": f"机型不支持 {impedance} 输入阻抗",
                            }
                        )
                        continue
                    impedance_scales = _vertical_scales_for(characteristics, impedance)
                    if impedance_scales and scale not in impedance_scales:
                        cap = characteristics.get("max_vertical_scale_50")
                        reason = (
                            f"50 Ω 输入垂直挡位上限 {_num(cap):g} V/div"
                            if cap is not None
                            else "机型无此垂直档位"
                        )
                        skipped.append(
                            {
                                "channel": channel,
                                "scale": scale,
                                "impedance": impedance,
                                "reason": reason,
                            }
                        )
                        continue
                    reason = None
                    if limit_amplitude is not None:
                        reason = _check_amplitude(limit_amplitude, calibrator, shape, impedance)
                    if reason:
                        skipped.append(
                            {
                                "channel": channel,
                                "scale": scale,
                                "impedance": impedance,
                                "reason": reason,
                            }
                        )
                        continue
                    values = {"channel": channel, "scale": scale, "impedance": impedance}
                    if std is not None:
                        values["std_value_vpp"] = std
                    points.append(_point(values))
    elif horizontal_scales is not None:
        available = set(_num(v) for v in characteristics.get("horizontal_scales", []))
        # 两种水平取点口径：多周期测量（periods_m，按屏占比铺满）与
        # 时基误差（periods_on_screen，屏上显示 N 个周期）。
        if "periods_m" in rule:
            periods = _num(rule.get("periods_m", 2))
            coverage = _num(rule.get("screen_fraction", 1.0))
        else:
            periods = _num(rule.get("periods_on_screen", 3))
            coverage = 1.0
        for channel in channels:
            for scale in horizontal_scales:
                scale = _num(scale)
                if available and scale not in available:
                    skipped.append(
                        {"channel": channel, "scale_s_per_div": scale, "reason": "机型无此水平档位"}
                    )
                    continue
                period = coverage * horizontal_div * scale / periods
                freq = 1.0 / period if period > 0 else 0.0
                reason = _check_frequency(freq, calibrator, "1M", shape)
                if reason:
                    skipped.append({"channel": channel, "scale_s_per_div": scale, "reason": reason})
                    continue
                points.append(
                    _point(
                        {
                            "channel": channel,
                            "timebase_s_per_div": scale,
                            "period_on_screen_s": period,
                            "signal_freq_hz": freq,
                        }
                    )
                )
    return {"points": points, "skipped": skipped}


def _resolve_bw_ratio(
    item: dict, characteristics: dict, calibrator: dict, channels: list[str]
) -> dict:
    rule = item.get("points", {})
    reference = _num(rule.get("reference_hz", 50000))
    ratios = [_num(r) for r in rule.get("ratios", [])]
    bandwidth = _num(characteristics.get("bandwidth_hz", 0))
    frequencies = [reference] + [bandwidth * ratio for ratio in ratios]

    points, skipped = [], []
    wanted = rule.get("impedances", ["1M"])
    for channel in channels:
        for impedance in wanted:
            if not _impedance_supported(characteristics, impedance):
                skipped.append({"channel": channel, "reason": f"机型不支持 {impedance} 输入阻抗"})
                continue
            for freq in frequencies:
                reason = _check_frequency(freq, calibrator, impedance, "SIN")
                if reason:
                    skipped.append(
                        {
                            "channel": channel,
                            "impedance": impedance,
                            "frequency_hz": freq,
                            "reason": reason,
                        }
                    )
                    continue
                points.append(
                    _point(
                        {
                            "channel": channel,
                            "impedance": impedance,
                            "frequency_hz": freq,
                        }
                    )
                )
    return {"points": points, "skipped": skipped}


def _resolve_derived(item: dict, characteristics: dict, channels: list[str]) -> dict:
    rule = item.get("points", {})
    note = rule.get("note", "现场按规范公式计算")
    wanted = rule.get("impedances", ["1M"])
    points, skipped = [], []
    for channel in channels:
        for impedance in wanted:
            if not _impedance_supported(characteristics, impedance):
                skipped.append({"channel": channel, "reason": f"机型不支持 {impedance} 输入阻抗"})
                continue
            points.append(
                _point(
                    {
                        "channel": channel,
                        "impedance": impedance,
                        "runtime": True,
                        "samples_n": rule.get("samples_n"),
                        "integer_cycles_n": rule.get("integer_cycles_n"),
                        "note": note,
                    }
                )
            )
    return {"points": points, "skipped": skipped}


def _resolve_fixed(item: dict, characteristics: dict, channels: list[str]) -> dict:
    scales = characteristics.get("vertical_scales") or []
    smallest = min(_num(v) for v in scales) if scales else None
    points = [_point({"channel": channel, "vertical_scale": smallest}) for channel in channels]
    skipped = []
    if smallest is None:
        skipped.append({"reason": "特征文件未声明 vertical_scales"})
        points = []
    return {"points": points, "skipped": skipped}


def _resolve_edge_speed(item: dict, calibrator: dict, probe: str, channels: list[str]) -> dict:
    info = (calibrator.get("probes") or {}).get(probe, {})
    speeds = [_num(v) for v in info.get("edge_rise_times", [])]
    points = [
        _point({"channel": channel, "edge_rise_time_s": speed})
        for channel in channels
        for speed in speeds
    ]
    skipped = []
    if not speeds:
        skipped.append({"reason": f"探头 {probe} 未声明 edge_rise_times"})
    return {"points": points, "skipped": skipped}


def resolve_item(
    name: str,
    spec_item: dict,
    scheme_item: dict | None,
    characteristics: dict,
    calibrator: dict,
    probe: str,
    channels: list[str],
    reference_limits: dict | None = None,
) -> dict:
    """解析单个校准项目。

    返回 {name, clause, title, methods, method, primary, strategy, status, points, skipped}。
    规范中未实现的人工项返回 manual；方案未列入的项目返回 not_in_scheme。
    """
    clause = spec_item.get("clause", "")
    title = spec_item.get("title", "")
    if not spec_item.get("automatable"):
        return {
            "name": name,
            "clause": clause,
            "title": title,
            "methods": [],
            "primary": None,
            "strategy": None,
            "status": "manual",
            "points": [],
            "skipped": [{"reason": "规范定为人工执行，程序不实现"}],
        }

    if scheme_item is None:
        return {
            "name": name,
            "clause": clause,
            "title": title,
            "methods": [],
            "primary": None,
            "strategy": None,
            "status": "not_in_scheme",
            "points": [],
            "skipped": [{"reason": "方案未列入该项目"}],
        }

    rule = scheme_item.get("points", {})
    strategy = rule.get("strategy")
    selected = scheme_item.get("method")

    if strategy == "channel_x_impedance":
        resolved = _resolve_channel_x_impedance(
            scheme_item, characteristics, channels, reference_limits or {}
        )
    elif strategy == "scale_list":
        resolved = _resolve_scale_list(
            scheme_item,
            characteristics,
            calibrator,
            channels,
            shape=method_output_shape(name, selected),
        )
    elif strategy == "bw_ratio":
        resolved = _resolve_bw_ratio(scheme_item, characteristics, calibrator, channels)
    elif strategy == "derived":
        resolved = _resolve_derived(scheme_item, characteristics, channels)
    elif strategy == "fixed":
        resolved = _resolve_fixed(scheme_item, characteristics, channels)
    elif strategy == "channel_x_edge_speed":
        resolved = _resolve_edge_speed(scheme_item, calibrator, probe, channels)
    else:
        resolved = {
            "points": [],
            "skipped": [{"reason": f"暂不支持取点策略 {strategy!r}"}],
        }

    declared = list(scheme_item.get("methods", []))
    executed = [selected] if selected else declared
    primary = (
        selected if selected and name in {"dc_gain", "dc_offset"} else scheme_item.get("primary")
    )

    return {
        "name": name,
        "clause": clause,
        "title": title,
        "methods": executed,
        "method": selected,
        "primary": primary,
        "strategy": strategy,
        "status": "planned",
        "points": resolved["points"],
        "skipped": resolved["skipped"],
    }


def build_plan(
    spec: dict,
    scheme: dict,
    characteristics: dict,
    calibrator: dict,
    probe: str,
    channels: list[str],
) -> dict:
    """生成完整计划：逐项解析 + 汇总统计。

    规范里的全部 12 项都会出现在计划中：方案列入的 10 项为 planned，
    人工项为 manual，方案未列入的为 not_in_scheme。
    """
    items = []
    reference_limits = spec.get("reference_limits", {})
    scheme_items = scheme.get("items", {})
    for name, spec_item in spec.get("items", {}).items():
        items.append(
            resolve_item(
                name,
                spec_item,
                scheme_items.get(name),
                characteristics,
                calibrator,
                probe,
                channels,
                reference_limits,
            )
        )

    total_points = sum(len(item["points"]) for item in items)
    total_skipped = sum(len(item["skipped"]) for item in items)
    return {
        "spec_code": spec.get("spec_code", ""),
        "spec_effective": spec.get("effective", ""),
        "scheme_name": scheme.get("name", ""),
        "scheme_spec": scheme.get("spec", ""),
        "characteristics_series": characteristics.get("series", ""),
        "calibrator": calibrator.get("name", ""),
        "probe": probe,
        "channels": channels,
        "items": items,
        "total_points": total_points,
        "total_skipped": total_skipped,
    }
