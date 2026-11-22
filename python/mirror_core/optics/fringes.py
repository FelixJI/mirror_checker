"""SOFAST 条纹图案与相位解包(上游 OpenCSP 公式移植)。

移植来源(固定提交 ``356e3a98eeb880146b57955112b1a9759692531f``,
Apache License 2.0;本文件为公式移植,未复制上游代码文件):

- ``opencsp/app/sofast/lib/Fringes.py``
  - ``from_num_periods``:周期序列 ``[4^0 - 0.1, 4^1, ..., 4^(n-1)]``,
    每周期 4 步相移;
  - ``get_sinusoids``:条纹幅角沿图案坐标**反向**增大,
    ``argument = (1 - s) * period * 2*pi``,第 k 步相移 ``k*pi/2``;
  - ``get_frames``:y 方向条纹先于 x 方向;
- ``opencsp/app/sofast/lib/image_processing.py``
  - ``unwrap_phase``:``phase = atan2(c2 - c4, c1 - c3)``,
    ``w = mod(phase, 2*pi) / (period * 2*pi)``,再做多频解缠。

与上游的差异(记录于 docs/upstream.md):上游对 y 轴应用
``uy = 1 - unwrapped``、x 轴直接取 unwrapped,该翻转与其相机—屏幕
成像几何(经镜面反射观看屏幕,一轴镜像)绑定;本仓库的正向模型按
真实光路编码,屏幕坐标与图案坐标的关系对两轴统一为
``coord = 1 - unwrapped``,几何翻转由光线追踪自然产生。

单位约定:``s`` 与解包结果均为无量纲屏幕分数(有效发光矩形内的
归一化坐标);相位为弧度;强度为 ``[0, 1]`` 归一化灰度(显示端的
值域缩放在采集侧另行应用,解码对线性缩放与常数偏置不敏感)。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

#: 上游约定的相移步数(4 步:0、π/2、π、3π/2)
PHASE_SHIFTS = 4

#: 上游 ``from_num_periods`` 的默认周期级数
DEFAULT_NUM_PERIODS = 4


def default_periods(num_periods: int = DEFAULT_NUM_PERIODS) -> tuple[float, ...]:
    """上游默认条纹周期序列(单位:屏幕宽度的分数)。

    ``[4^0 - 0.1, 4^1, ..., 4^(num_periods-1)]``;首项减 0.1 保证
    最粗一级不满一整周期,解包结果落在 ``[0, 1)``。
    """
    if num_periods < 1:
        raise ValueError(f"周期级数至少为 1,实际为 {num_periods!r}")
    periods = [float(4**idx) for idx in range(num_periods)]
    periods[0] -= 0.1
    return tuple(periods)


def fringe_value(s: float, period: float, shift_index: int) -> float:
    """单个条纹帧在图案坐标 ``s`` 处的归一化强度。

    上游 ``get_sinusoids`` 公式:``cos((1 - s) * period * 2*pi -
    shift_index * pi/2)`` 后映射到 ``[0, 1]``。``s`` 是沿图案坐标轴的
    归一化位置(0 到 1)。
    """
    if shift_index not in range(PHASE_SHIFTS):
        raise ValueError(f"相移序号必须在 0..{PHASE_SHIFTS - 1},实际为 {shift_index!r}")
    argument = (1.0 - s) * period * 2.0 * math.pi - shift_index * math.pi / 2.0
    return math.cos(argument) / 2.0 + 0.5


def frame_count(periods_x: Sequence[float], periods_y: Sequence[float]) -> int:
    """整组条纹帧数:y 方向与 x 方向各 ``周期数 * 4`` 帧。"""
    return (len(periods_x) + len(periods_y)) * PHASE_SHIFTS


def frame_value(
    frame_index: int,
    u: float,
    v: float,
    periods_x: Sequence[float],
    periods_y: Sequence[float],
) -> float:
    """按上游 ``get_frames`` 的帧序返回某帧在屏幕 ``(u, v)`` 的强度。

    帧序:y 方向各周期 4 帧在前,x 方向在后;y 帧随 ``v`` 变化,
    x 帧随 ``u`` 变化。
    """
    num_y = len(periods_y) * PHASE_SHIFTS
    total = num_y + len(periods_x) * PHASE_SHIFTS
    if frame_index not in range(total):
        raise ValueError(f"帧序号必须在 0..{total - 1},实际为 {frame_index!r}")
    if frame_index < num_y:
        period = periods_y[frame_index // PHASE_SHIFTS]
        shift = frame_index % PHASE_SHIFTS
        return fringe_value(v, period, shift)
    idx = frame_index - num_y
    period = periods_x[idx // PHASE_SHIFTS]
    shift = idx % PHASE_SHIFTS
    return fringe_value(u, period, shift)


def encode_intensities(s: float, periods: Sequence[float]) -> list[float]:
    """一个观测点在单方向全部帧上的强度序列。

    顺序:周期 0 的 4 步相移、周期 1 的 4 步相移……与上游
    ``unwrap_phase`` 期望的信号排列一致。
    """
    return [
        fringe_value(s, period, shift)
        for period in periods
        for shift in range(PHASE_SHIFTS)
    ]


def _mod(value: float, modulus: float) -> float:
    """NumPy 风格取余:结果与模数同号,落在 ``[0, modulus)``。"""
    return value - modulus * math.floor(value / modulus)


def unwrap_phase(intensities: Sequence[float], periods: Sequence[float]) -> float:
    """四步相移 + 多频解包,返回图案坐标位置(屏幕宽度分数)。

    上游 ``image_processing.unwrap_phase`` 的逐点移植:

    - ``phase = atan2(c2 - c4, c1 - c3)``(弧度,主值);
    - ``w = mod(phase, 2*pi) / (period * 2*pi)``;
    - 多频修正 ``f = 1/period;A = x - f/2;wa = mod(A + f, f);
      x = A + mod(w - wa + f, f)``。

    输出为沿图案坐标轴的位置(即 ``(1 - s)``,见模块 docstring);
    常数偏置与线性缩放不影响结果。
    """
    if len(intensities) != len(periods) * PHASE_SHIFTS:
        raise ValueError(
            f"强度序列长度 {len(intensities)} 与周期数 "
            f"{len(periods)} * {PHASE_SHIFTS} 不匹配"
        )
    x = 0.0
    for idx, period in enumerate(periods):
        c1 = intensities[PHASE_SHIFTS * idx]
        c2 = intensities[PHASE_SHIFTS * idx + 1]
        c3 = intensities[PHASE_SHIFTS * idx + 2]
        c4 = intensities[PHASE_SHIFTS * idx + 3]
        phase = math.atan2(c2 - c4, c1 - c3)
        w = _mod(phase, 2.0 * math.pi) / (period * 2.0 * math.pi)
        if idx == 0:
            x = w
        else:
            f = 1.0 / period
            a = x - f / 2.0
            wa = _mod(a + f, f)
            x = a + _mod(w - wa + f, f)
    return x


def screen_fraction_from_unwrapped(unwrapped: float) -> float:
    """解包结果 → 屏幕归一化坐标:``coord = 1 - unwrapped``。

    上游图案幅角沿图案坐标反向增大(``linspace(1, 0)`` 约定),
    解包返回的是图案坐标 ``1 - s``;本模型两轴统一翻回屏幕坐标。
    """
    return 1.0 - unwrapped
