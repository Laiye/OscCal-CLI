"""正弦波形序列的最小二乘拟合（JJF 1057-2026 附录 E）。

模型：y(i) = A·cos(ω·i·Δt) + B·sin(ω·i·Δt) + D
     ≡ E·sin(ω·i·Δt + φ) + D，其中 E = √(A²+B²)、φ = atan2(A, B)。

做法与附录 E 一致：先由周期计点法给出频率初值，再在初值附近搜索使残差最小的 ω；
每个候选 ω 下的三参数问题（A、B、D）是线性的，有闭式解，因此搜索只需比较残差。

纯 Python 实现，不引入 numpy：1000 点 × 数百次候选评估仍是毫秒级。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: 黄金分割比例。
_GOLDEN = (math.sqrt(5.0) - 1.0) / 2.0


class FitError(RuntimeError):
    """输入数据不足以完成正弦拟合（点太少、无周期、非有限值等）。"""


@dataclass
class SineFit:
    """拟合结果。"""

    amplitude: float
    phase: float
    dc: float
    frequency: float
    omega: float
    rms_error: float
    samples: int


def _solve3(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """3×3 线性方程组（高斯消元，部分选主元）；奇异时返回 None。"""
    a = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda r: abs(a[r][column]))
        if abs(a[pivot][column]) < 1e-18:
            return None
        a[column], a[pivot] = a[pivot], a[column]
        for row in range(column + 1, 3):
            factor = a[row][column] / a[column][column]
            if factor == 0.0:
                continue
            for k in range(column, 4):
                a[row][k] -= factor * a[column][k]
    solution = [0.0, 0.0, 0.0]
    for row in (2, 1, 0):
        total = a[row][3] - sum(a[row][k] * solution[k] for k in range(row + 1, 3))
        solution[row] = total / a[row][row]
    return solution


def _linear_fit(times: list[float], values: list[float], omega: float):
    """固定 ω 的三参数最小二乘，返回 (A, B, D, sse)；无法求解时返回 None。"""
    count = len(times)
    scc = sss = scs = sc = ss = 0.0
    scy = ssy = sy = 0.0
    cos_w = math.cos
    sin_w = math.sin
    for t, y in zip(times, values, strict=False):
        phase = omega * t
        c = cos_w(phase)
        s = sin_w(phase)
        scc += c * c
        sss += s * s
        scs += c * s
        sc += c
        ss += s
        scy += c * y
        ssy += s * y
        sy += y
    matrix = [[scc, scs, sc], [scs, sss, ss], [sc, ss, float(count)]]
    solution = _solve3(matrix, [scy, ssy, sy])
    if solution is None:
        return None
    a, b, d = solution
    sse = 0.0
    for t, y in zip(times, values, strict=False):
        predicted = a * cos_w(omega * t) + b * sin_w(omega * t) + d
        diff = y - predicted
        sse += diff * diff
    return a, b, d, sse


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def estimate_frequency(times: list[float], values: list[float]) -> float:
    """周期计点法：用过均值的上升/下降穿越次数估计频率。

    穿越点做线性插值，比直接数采样点稳。
    """
    if len(times) < 3:
        raise FitError("样本点太少，无法估计频率")
    offset = _mean(values)
    crossings: list[float] = []
    prev_t, prev_v = times[0], values[0] - offset
    for t, value in zip(times[1:], values[1:], strict=False):
        cur = value - offset
        # 只统计真正的符号变化；整段都贴着均值时不算穿越。
        if prev_v != cur and ((prev_v <= 0.0 <= cur) or (cur <= 0.0 <= prev_v)):
            span = cur - prev_v
            ratio = 0.0 if span == 0.0 else -prev_v / span
            crossings.append(prev_t + ratio * (t - prev_t))
        prev_t, prev_v = t, cur
    if len(crossings) < 2:
        raise FitError("未检测到两个以上的周期穿越，无法估计频率")
    span = crossings[-1] - crossings[0]
    if span <= 0:
        raise FitError("时间轴非单调，无法估计频率")
    return (len(crossings) - 1) / (2.0 * span)


def fit_sine(
    times: list[float],
    values: list[float],
    *,
    freq_guess: float | None = None,
    search_span: float = 0.5,
    coarse_steps: int = 200,
    refine_steps: int = 80,
) -> SineFit:
    """四参数正弦拟合：粗搜频率 + 黄金分割细化。

    Args:
        times: 采样时刻（秒），需单调递增。
        values: 采样值（伏）。
        freq_guess: 频率初值；缺省用周期计点法估计。
        search_span: 相对搜索跨度（0.5 表示 ±50%）。
        coarse_steps: 粗搜步数。
        refine_steps: 细化迭代次数。
    """
    count = len(times)
    if count < 8 or count != len(values):
        raise FitError("样本点数量不足或时间轴与数值长度不一致")
    if any(not math.isfinite(v) for v in values):
        raise FitError("样本中含非有限值")
    if any(b <= a for a, b in zip(times, times[1:], strict=False)):
        raise FitError("时间轴必须严格递增")

    guess = freq_guess if freq_guess is not None else estimate_frequency(times, values)
    if guess <= 0:
        raise FitError("频率初值必须为正")

    low = guess * (1.0 - search_span)
    high = guess * (1.0 + search_span)
    if low <= 0:
        low = guess * 0.01

    def sse_at(freq: float) -> float:
        result = _linear_fit(times, values, 2.0 * math.pi * freq)
        return math.inf if result is None else result[3]

    # 粗搜：找到残差最低的频段
    step = (high - low) / max(coarse_steps, 1)
    best_freq = low
    best_sse = math.inf
    for index in range(coarse_steps + 1):
        freq = low + index * step
        value = sse_at(freq)
        if value < best_sse:
            best_sse, best_freq = value, freq

    # 黄金分割细化：在最佳点两侧各一个步长内继续
    left = max(low, best_freq - step)
    right = min(high, best_freq + step)
    c = right - _GOLDEN * (right - left)
    d = left + _GOLDEN * (right - left)
    fc, fd = sse_at(c), sse_at(d)
    for _ in range(max(refine_steps, 1)):
        if abs(right - left) <= 1e-12 * max(1.0, abs(high)):
            break
        if fc < fd:
            right, d, fd = d, c, fc
            c = right - _GOLDEN * (right - left)
            fc = sse_at(c)
        else:
            left, c, fc = c, d, fd
            d = left + _GOLDEN * (right - left)
            fd = sse_at(d)
    omega_freq = (left + right) / 2.0

    fitted = _linear_fit(times, values, 2.0 * math.pi * omega_freq)
    if fitted is None:
        raise FitError("拟合无法求解（数据退化）")
    a, b, d, sse = fitted
    amplitude = math.hypot(a, b)
    phase = math.atan2(a, b)
    return SineFit(
        amplitude=amplitude,
        phase=phase,
        dc=d,
        frequency=omega_freq,
        omega=2.0 * math.pi * omega_freq,
        rms_error=math.sqrt(sse / count),
        samples=count,
    )


def enob(fit: SineFit, full_scale_volts: float) -> float:
    """按 7.7 式 (15) 由拟合残差算动态有效位数。

    ENOB = log2(满量程 / (√12 × 噪声与失真均方根))
    """
    if fit.rms_error <= 0:
        raise FitError("残差为零，无法计算 ENOB")
    if full_scale_volts <= 0:
        raise FitError("满量程必须为正")
    return math.log2(full_scale_volts / (math.sqrt(12.0) * fit.rms_error))
