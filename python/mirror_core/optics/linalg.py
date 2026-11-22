"""三维向量与小矩阵工具(仅标准库 ``math``)。

镜面检测光学核心的底层数学工具:向量用 ``tuple[float, float, float]``
表示,矩阵用 3x3 行主序嵌套 tuple 表示,与
:class:`mirror_core.transforms.Transform` 的表示一致。

所有函数不修改输入,返回新 tuple;对零长度向量归一化显式抛出
:class:`~mirror_core.contracts.ContractError`,不允许静默返回 NaN。
"""

from __future__ import annotations

import math

from mirror_core.contracts import ContractError

#: 三维向量类型别名
Vec3 = tuple[float, float, float]
#: 3x3 行主序矩阵类型别名
Mat3 = tuple[Vec3, Vec3, Vec3]

# 文档约定:本模块的报错位置前缀
_WHERE = "optics.linalg"


def vec_add(a: Vec3, b: Vec3) -> Vec3:
    """向量加法 ``a + b``。"""
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vec_sub(a: Vec3, b: Vec3) -> Vec3:
    """向量减法 ``a - b``。"""
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vec_scale(a: Vec3, k: float) -> Vec3:
    """向量数乘 ``k * a``。"""
    return (a[0] * k, a[1] * k, a[2] * k)


def vec_dot(a: Vec3, b: Vec3) -> float:
    """向量点积。"""
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vec_cross(a: Vec3, b: Vec3) -> Vec3:
    """向量叉积。"""
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def vec_norm(a: Vec3) -> float:
    """向量欧氏范数。"""
    return math.sqrt(vec_dot(a, a))


def vec_normalize(a: Vec3, where: str = _WHERE) -> Vec3:
    """返回单位向量 ``a / |a|``。

    零向量无法归一化,显式报错而非产生除零:
    调用方通常以此发现退化几何(如光线与镜面法线平行)。
    """
    norm = vec_norm(a)
    if norm == 0.0:
        raise ContractError(f"{where}: 无法归一化零长度向量,实际为 {a!r}")
    return (a[0] / norm, a[1] / norm, a[2] / norm)


def vec_reflect(direction: Vec3, normal: Vec3) -> Vec3:
    """把 ``direction`` 关于单位法线 ``normal`` 反射。

    要求 ``normal`` 已归一化;返回向量不保证归一化
    (输入为单位向量时输出亦为单位向量)。
    """
    # r = d - 2 (d·n) n
    return vec_sub(direction, vec_scale(normal, 2.0 * vec_dot(direction, normal)))


def vec_angle_between(a: Vec3, b: Vec3) -> float:
    """两向量夹角(弧度,``[0, pi]``)。

    用 ``atan2(|a×b|, a·b)`` 形式,避免接近平行时 ``acos`` 的精度损失;
    任一为零向量显式报错。
    """
    cross_norm = vec_norm(vec_cross(a, b))
    dot = vec_dot(a, b)
    if cross_norm == 0.0 and dot == 0.0:
        raise ContractError(f"{_WHERE}: 无法计算零向量夹角,实际为 {a!r} 与 {b!r}")
    return math.atan2(cross_norm, dot)


def mat_vec(m: Mat3, v: Vec3) -> Vec3:
    """矩阵乘列向量 ``m @ v``。"""
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def point_on_ray(origin: Vec3, direction: Vec3, t: float) -> Vec3:
    """射线取点 ``origin + t * direction``。"""
    return vec_add(origin, vec_scale(direction, t))


def line_plane_parameter(origin: Vec3, direction: Vec3, plane_point: Vec3, plane_normal: Vec3, where: str = _WHERE) -> float:
    """求射线与平面的交点参数 ``t``。

    平面由点 ``plane_point`` 与单位法线 ``plane_normal`` 定义;返回 ``t``
    使 ``origin + t * direction`` 落在平面上。射线方向与平面平行
    (``|direction · normal|`` 接近零)时显式报错。
    """
    denom = vec_dot(direction, plane_normal)
    if abs(denom) < 1e-15:
        raise ContractError(
            f"{where}: 射线与平面平行,无交点(direction·normal={denom!r})"
        )
    return vec_dot(vec_sub(plane_point, origin), plane_normal) / denom
