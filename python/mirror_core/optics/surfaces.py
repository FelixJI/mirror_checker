"""高度场表面族:独立正向仿真的真值表面(镜面参考系 M)。

所有表面表示为高度场 ``z = h(x, y)``,在镜面参考系 M 中定义:

- 原点为镜面名义参考点;``+z`` 指向相机一侧(与屏幕同侧);
- 法线约定 ``n = normalize(-dh/dx, -dh/dy, 1)``,即 ``+z`` 分量为正、
  朝向相机——与上游 OpenCSP ``slope_fitting_2d.calc_slopes`` 的
  ``slope = (-n.x/n.z, -n.y/n.z)``、``ProcessSofastAbstract`` 的
  ``[-slope_x, -slope_y, 1]`` 完全一致;
- Hessian 返回 ``((d2h/dx2, d2h/dxdy), (d2h/dydx, d2h/dy2))``,对称。

每个表面同时给出**名义基准平面** ``reference_plane``(点 + 单位法线):
它是求解端"外部给定的距离/姿态约束"所对应的平面(实施方案 §6.3:
单目偏折的深度-斜率耦合必须由外部约束固定)。平面与倾斜平面的基准
平面即自身;弯曲表面取其定义基面 ``z = 0``。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from mirror_core.optics.linalg import Vec3, vec_normalize

#: Hessian 的表示:(dxx, dxy), (dyx, dyy)
Hessian = tuple[tuple[float, float], tuple[float, float]]

#: 平面:(平面上的点, 单位法线)
Plane = tuple[Vec3, Vec3]


class HeightSurface:
    """高度场表面基类。子类必须实现 :meth:`height` 与 :meth:`gradient`。"""

    #: 表面类型标识(子类覆盖)
    kind = "abstract"

    def height(self, x: float, y: float) -> float:
        """表面高度 ``h(x, y)``(米)。"""
        raise NotImplementedError

    def gradient(self, x: float, y: float) -> tuple[float, float]:
        """解析梯度 ``(dh/dx, dh/dy)``。"""
        raise NotImplementedError

    def hessian(self, x: float, y: float) -> Hessian:
        """解析二阶导(默认由数值差分实现,子类可覆盖为精确值)。"""
        # 中心差分步长 1e-6 m(亚微米),对光滑表面截断误差 ~h'''·d²,
        # 本模块子类均覆盖为解析式,此实现仅作后备。
        d = 1e-6
        hx_p, _ = self.gradient(x + d, y)
        hx_m, _ = self.gradient(x - d, y)
        _, hy_p = self.gradient(x, y + d)
        _, hy_m = self.gradient(x, y - d)
        hxy_p = self.gradient(x + d, y + d)[1]
        hxy_m = self.gradient(x - d, y - d)[1]
        dxx = (hx_p - hx_m) / (2.0 * d)
        dyy = (hy_p - hy_m) / (2.0 * d)
        dxy = (hxy_p - hxy_m) / (2.0 * d)
        return ((dxx, dxy), (dxy, dyy))

    def normal(self, x: float, y: float) -> Vec3:
        """解析单位法线(朝相机,``+z`` 分量为正)。"""
        gx, gy = self.gradient(x, y)
        return vec_normalize((-gx, -gy, 1.0))

    @property
    def reference_plane(self) -> Plane:
        """名义基准平面(外部距离/姿态约束对应的平面)。"""
        return ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))


@dataclass(frozen=True)
class PlaneSurface(HeightSurface):
    """理想平面镜:``h = 0``。"""

    kind = "plane"

    def height(self, x: float, y: float) -> float:
        return 0.0

    def gradient(self, x: float, y: float) -> tuple[float, float]:
        return (0.0, 0.0)

    def hessian(self, x: float, y: float) -> Hessian:
        return ((0.0, 0.0), (0.0, 0.0))


@dataclass(frozen=True)
class TiltedPlaneSurface(HeightSurface):
    """倾斜平面:``h = slope_x * x + slope_y * y``。

    倾斜是绕 M 系 y/x 轴的刚体姿态,不引入任何曲率;本案例用于验收
    "平面倾斜不会生成假曲率"(实施方案 PR-02)。基准平面为其自身。
    """

    slope_x: float
    slope_y: float

    kind = "tilted_plane"

    def height(self, x: float, y: float) -> float:
        return self.slope_x * x + self.slope_y * y

    def gradient(self, x: float, y: float) -> tuple[float, float]:
        return (self.slope_x, self.slope_y)

    def hessian(self, x: float, y: float) -> Hessian:
        return ((0.0, 0.0), (0.0, 0.0))

    @property
    def reference_plane(self) -> Plane:
        return ((0.0, 0.0, 0.0), self.normal(0.0, 0.0))


@dataclass(frozen=True)
class CylinderSurface(HeightSurface):
    """柱面:母线沿 ``axis``,``h = sign * u^2 / (2 * radius)``,u 为弯曲轴坐标。

    ``sign=+1``:边缘朝 ``+z`` 抬升,凹面朝向相机;``sign=-1``:边缘后缩,
    凸面朝向相机(家用"胖镜"方向)。``axis="x"`` 时沿 x 弯曲、y 为母线
    方向;``axis="y"`` 旋转 90°,用于验收方向可识别性。
    """

    radius_m: float
    sign: float = 1.0
    axis: str = "x"

    kind = "cylinder"

    def __post_init__(self) -> None:
        if self.radius_m <= 0.0:
            raise ValueError(f"柱面半径必须为正,实际为 {self.radius_m!r}")
        if self.sign not in (1.0, -1.0):
            raise ValueError(f"sign 只能取 ±1,实际为 {self.sign!r}")
        if self.axis not in ("x", "y"):
            raise ValueError(f"axis 只能取 'x' 或 'y',实际为 {self.axis!r}")

    def _bend_coord(self, x: float, y: float) -> float:
        return x if self.axis == "x" else y

    def height(self, x: float, y: float) -> float:
        u = self._bend_coord(x, y)
        return self.sign * u * u / (2.0 * self.radius_m)

    def gradient(self, x: float, y: float) -> tuple[float, float]:
        u = self._bend_coord(x, y)
        du = self.sign * u / self.radius_m
        return (du, 0.0) if self.axis == "x" else (0.0, du)

    def hessian(self, x: float, y: float) -> Hessian:
        d = self.sign / self.radius_m
        return ((d, 0.0), (0.0, 0.0)) if self.axis == "x" else ((0.0, 0.0), (0.0, d))


@dataclass(frozen=True)
class SphereSurface(HeightSurface):
    """精确球面 sag:``h = sign * (R - sqrt(R^2 - x^2 - y^2))``。

    球心在 ``(0, 0, sign*R)``;``sign=+1`` 凹面朝相机、``sign=-1``
    凸面朝相机。曲率半径的绝对值为 ``radius_m``。孔径内
    ``x^2 + y^2 < R^2`` 才有定义。
    """

    radius_m: float
    sign: float = 1.0

    kind = "sphere"

    def __post_init__(self) -> None:
        if self.radius_m <= 0.0:
            raise ValueError(f"球面半径必须为正,实际为 {self.radius_m!r}")
        if self.sign not in (1.0, -1.0):
            raise ValueError(f"sign 只能取 ±1,实际为 {self.sign!r}")

    def _w(self, x: float, y: float) -> float:
        # w = sqrt(R^2 - x^2 - y^2) = R - |h|,孔径内恒为正
        w = math.sqrt(self.radius_m * self.radius_m - x * x - y * y)
        if w <= 0.0:
            raise ValueError(
                f"球面孔径外无定义:x^2+y^2={x * x + y * y!r},R={self.radius_m!r}"
            )
        return w

    def height(self, x: float, y: float) -> float:
        return self.sign * (self.radius_m - self._w(x, y))

    def gradient(self, x: float, y: float) -> tuple[float, float]:
        # dh/du = sign * u / w
        w = self._w(x, y)
        return (self.sign * x / w, self.sign * y / w)

    def hessian(self, x: float, y: float) -> Hessian:
        w = self._w(x, y)
        s = self.sign
        dxx = s * (1.0 / w + x * x / (w * w * w))
        dyy = s * (1.0 / w + y * y / (w * w * w))
        dxy = s * x * y / (w * w * w)
        return ((dxx, dxy), (dxy, dyy))


@dataclass(frozen=True)
class SaddleSurface(HeightSurface):
    """鞍形(双曲抛物面):``h = a * (x^2 - y^2)``。"""

    coefficient_a: float

    kind = "saddle"

    def height(self, x: float, y: float) -> float:
        return self.coefficient_a * (x * x - y * y)

    def gradient(self, x: float, y: float) -> tuple[float, float]:
        return (2.0 * self.coefficient_a * x, -2.0 * self.coefficient_a * y)

    def hessian(self, x: float, y: float) -> Hessian:
        d = 2.0 * self.coefficient_a
        return ((d, 0.0), (0.0, -d))


@dataclass(frozen=True)
class RippleSurface(HeightSurface):
    """低频二次项叠加横向波纹。

    ``h = quad_a * x^2 + ripple_amp * cos(2*pi*x/ripple_wavelength + phase)``

    用于验证低频整体弯曲与局部波纹同时存在时,求解端不因拟合把全局
    二次项当作可去趋势(实施方案 PR-02 验收)。
    """

    quad_a: float
    ripple_amp: float
    ripple_wavelength: float
    ripple_phase_rad: float = 0.0

    kind = "ripple"

    def __post_init__(self) -> None:
        if self.ripple_wavelength <= 0.0:
            raise ValueError(
                f"波纹波长必须为正,实际为 {self.ripple_wavelength!r}"
            )

    def _k(self) -> float:
        # 角频率 k = 2*pi / wavelength
        return 2.0 * math.pi / self.ripple_wavelength

    def height(self, x: float, y: float) -> float:
        return (
            self.quad_a * x * x
            + self.ripple_amp * math.cos(self._k() * x + self.ripple_phase_rad)
        )

    def gradient(self, x: float, y: float) -> tuple[float, float]:
        k = self._k()
        dh_dx = 2.0 * self.quad_a * x - self.ripple_amp * k * math.sin(
            k * x + self.ripple_phase_rad
        )
        return (dh_dx, 0.0)

    def hessian(self, x: float, y: float) -> Hessian:
        k = self._k()
        dxx = 2.0 * self.quad_a - self.ripple_amp * k * k * math.cos(
            k * x + self.ripple_phase_rad
        )
        return ((dxx, 0.0), (0.0, 0.0))
