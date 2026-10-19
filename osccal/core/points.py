"""校准点解析器：把「规范口径 + 硬件能力 + 标准器能力」合成为可执行的校准点表。

输入三方数据，缺一不可：
- `specs/*.json`：规范要求的取点策略、屏占比、比值、基准频率、条款号；
- `profiles/*.json`：被校示波器的硬件事实（通道数、格线、档位集合、标称带宽）；
- `calibrators/*.json`：标准器的输出能力（电压/频率上限、探头边沿速度）。

输出一份纯 JSON 可序列化的计划，含每个点的具体数值与**被跳过的点及原因**。
解析过程不连接任何仪器，可用 `osccal plan` 离线核对。

不做隐式降级：某个点如果超出标准器能力，一定记进 `skipped` 并说明理由，
不会静默少跑一个点。
"""

from __future__ import annotations

SHAPE_TO_OUTPUT = {
    "DC": "DC",
    "SQU": "SQU",
    "SIN": "SIN",
    "EDGE": "EDGE",
}

# 取点策略的说明，供 `osccal plan` 与文档共用。
IMPEDANCE_LABELS = {"1M": "1 MΩ", "50": "50 Ω"}

STRATEGY_DESCRIPTIONS = {
    "explicit": "配置里的绝对点表",
    "screen_fraction": "按屏占比换算标准值",
    "scale_list": "按垂直/水平档位列表逐档取点",
    "bw_ratio": "相对标称带宽的比例频点 + 固定基准",
    "derived": "现场读回后按规范公式计算（不在配置里写死）",
    "fixed": "固定条件点",
    "channel_x_impedance": "每通道 × 每种阻抗状态",
    "channel_x_edge_speed": "每通道 × 每个边沿速度档",
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


def _impedance_supported(profile: dict, impedance: str) -> bool:
    if impedance == "50":
        return bool(profile.get("imp_has_50"))
    return True


def _check_amplitude(
    amplitude_vpp: float, calibrator: dict, shape: str, impedance: str
) -> str | None:
    """返回跳过原因；可用则返回 None。"""
    limits = _output_limits(calibrator, shape, impedance)
    if not limits:
        return None
    label = IMPEDANCE_LABELS.get(impedance, impedance)
    lo = limits.get("min_vpp", limits.get("min_v"))
    hi = limits.get("max_vpp", limits.get("max_v"))
    if hi is not None and amplitude_vpp > _num(hi):
        return f"标准值 {amplitude_vpp:.4g} Vpp 超出 {label} 上限 {_num(hi):.4g} Vpp"
    if lo is not None and amplitude_vpp < _num(lo):
        return f"标准值 {amplitude_vpp:.4g} Vpp 低于 {label} 下限 {_num(lo):.4g} Vpp"
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


def _resolve_channel_x_impedance(item: dict, profile: dict, channels: list[str]) -> dict:
    wanted = item.get("points", {}).get("impedances", ["1M", "50"])
    points, skipped = [], []
    for channel in channels:
        for impedance in wanted:
            if not _impedance_supported(profile, impedance):
                skipped.append({"channel": channel, "reason": f"机型不支持 {impedance} 输入阻抗"})
                continue
            points.append(_point({"channel": channel, "impedance": impedance}))
    return {"points": points, "skipped": skipped}


def _resolve_scale_list(item: dict, profile: dict, calibrator: dict, channels: list[str]) -> dict:
    rule = item.get("points", {})
    shape = item.get("stimulus", {}).get("shape", "DC")
    fraction = rule.get("screen_fraction")
    vertical_scales = rule.get("scales_v_per_div")
    horizontal_scales = rule.get("horizontal_scales_s_per_div")
    wanted_impedances = rule.get("impedances", ["1M"])
    vertical_div = _num(profile.get("vertical_div", 8))
    horizontal_div = _num(profile.get("horizontal_div", 10))

    points: list[dict] = []
    skipped: list[dict] = []

    if vertical_scales is not None:
        available = set(_num(v) for v in profile.get("vertical_scales", []))
        for channel in channels:
            for scale in vertical_scales:
                scale = _num(scale)
                if available and scale not in available:
                    skipped.append(
                        {"channel": channel, "scale": scale, "reason": "机型无此垂直档位"}
                    )
                    continue
                std = float(fraction) * vertical_div * scale if fraction is not None else None
                for impedance in wanted_impedances:
                    if not _impedance_supported(profile, impedance):
                        skipped.append(
                            {
                                "channel": channel,
                                "scale": scale,
                                "reason": f"机型不支持 {impedance} 输入阻抗",
                            }
                        )
                        continue
                    reason = None
                    if std is not None:
                        reason = _check_amplitude(std, calibrator, shape, impedance)
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
        available = set(_num(v) for v in profile.get("horizontal_scales", []))
        periods = _num(rule.get("periods_on_screen", 3))
        for channel in channels:
            for scale in horizontal_scales:
                scale = _num(scale)
                if available and scale not in available:
                    skipped.append(
                        {"channel": channel, "scale_s_per_div": scale, "reason": "机型无此水平档位"}
                    )
                    continue
                period = scale * horizontal_div / periods
                freq = 1.0 / period if period > 0 else 0.0
                reason = _check_frequency(freq, calibrator, "1M", "SIN")
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


def _resolve_bw_ratio(item: dict, profile: dict, calibrator: dict, channels: list[str]) -> dict:
    rule = item.get("points", {})
    reference = _num(rule.get("reference_hz", 50000))
    ratios = [_num(r) for r in rule.get("ratios", [])]
    bandwidth = _num(profile.get("bandwidth_hz", 0))
    frequencies = [reference] + [bandwidth * ratio for ratio in ratios]

    points, skipped = [], []
    for channel in channels:
        for freq in frequencies:
            reason = _check_frequency(freq, calibrator, "1M", "SIN")
            if reason:
                skipped.append({"channel": channel, "frequency_hz": freq, "reason": reason})
                continue
            points.append(_point({"channel": channel, "frequency_hz": freq}))
    return {"points": points, "skipped": skipped}


def _resolve_derived(item: dict, channels: list[str]) -> dict:
    rule = item.get("points", {})
    note = rule.get("note", "现场按规范公式计算")
    points = [
        _point(
            {
                "channel": channel,
                "runtime": True,
                "samples_n": rule.get("samples_n"),
                "integer_cycles_n": rule.get("integer_cycles_n"),
                "note": note,
            }
        )
        for channel in channels
    ]
    return {"points": points, "skipped": []}


def _resolve_fixed(item: dict, profile: dict, channels: list[str]) -> dict:
    scales = profile.get("vertical_scales") or []
    smallest = min(_num(v) for v in scales) if scales else None
    points = [_point({"channel": channel, "vertical_scale": smallest}) for channel in channels]
    skipped = []
    if smallest is None:
        skipped.append({"reason": "Profile 未声明 vertical_scales"})
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
    profile: dict,
    calibrator: dict,
    probe: str,
    channels: list[str],
) -> dict:
    """解析单个校准项目，返回 {name, clause, title, method, strategy, points, skipped}。"""
    if not spec_item.get("automatable"):
        return {
            "name": name,
            "clause": spec_item.get("clause", ""),
            "title": spec_item.get("title", ""),
            "method": spec_item.get("method", ""),
            "strategy": None,
            "status": "manual",
            "points": [],
            "skipped": [{"reason": "规范定为人工执行，程序不实现"}],
        }

    rule = spec_item.get("points", {})
    strategy = rule.get("strategy")

    if strategy == "channel_x_impedance":
        resolved = _resolve_channel_x_impedance(spec_item, profile, channels)
    elif strategy == "scale_list":
        resolved = _resolve_scale_list(spec_item, profile, calibrator, channels)
    elif strategy == "bw_ratio":
        resolved = _resolve_bw_ratio(spec_item, profile, calibrator, channels)
    elif strategy == "derived":
        resolved = _resolve_derived(spec_item, channels)
    elif strategy == "fixed":
        resolved = _resolve_fixed(spec_item, profile, channels)
    elif strategy == "channel_x_edge_speed":
        resolved = _resolve_edge_speed(spec_item, calibrator, probe, channels)
    else:
        resolved = {
            "points": [],
            "skipped": [{"reason": f"暂不支持取点策略 {strategy!r}"}],
        }

    return {
        "name": name,
        "clause": spec_item.get("clause", ""),
        "title": spec_item.get("title", ""),
        "method": spec_item.get("method", ""),
        "strategy": strategy,
        "status": "planned",
        "points": resolved["points"],
        "skipped": resolved["skipped"],
    }


def build_plan(
    spec: dict,
    profile: dict,
    calibrator: dict,
    probe: str,
    channels: list[str],
) -> dict:
    """生成完整计划：逐项解析 + 汇总统计。"""
    items = []
    for name, spec_item in spec.get("items", {}).items():
        items.append(resolve_item(name, spec_item, profile, calibrator, probe, channels))

    total_points = sum(len(item["points"]) for item in items)
    total_skipped = sum(len(item["skipped"]) for item in items)
    return {
        "spec_code": spec.get("spec_code", ""),
        "spec_effective": spec.get("effective", ""),
        "profile_series": profile.get("series", ""),
        "calibrator": calibrator.get("name", ""),
        "probe": probe,
        "channels": channels,
        "items": items,
        "total_points": total_points,
        "total_skipped": total_skipped,
    }
