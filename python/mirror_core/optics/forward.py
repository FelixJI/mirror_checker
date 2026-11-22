"""独立正向光线模型:真值生成(镜面参考系 M)。

场景约定(全部在 M 系中,单位米/弧度):

- 相机为针孔模型,光心在 ``+z`` 一侧,沿 ``-z`` 观看镜面;
  像素 ``(i, j)`` 中 ``i`` 为列(向右,``+x``)、``j`` 为行(向下,
  ``-y``);相机视线方向按像素中心 ``(i + 0.5, j + 0.5)`` 生成;
- 屏幕为矩形平面 ``z = z_screen``,中心在光轴上,``+x``/``+y`` 与
  M 系一致;屏幕归一化坐标 ``u ∈ [0, 1]`` 自左向右、``v ∈ [0, 1]``
  自下向上,与米制坐标的关系 ``x = (u - 0.5) * W``、
  ``y = (v - 0.5) * H`` 对齐上游 ``DisplayShape``;
- 逐像素过程:相机射线 → 高度场求交(定步二分,确定性)→ 解析法线
  反射 → 与屏幕平面求交;反射点落在屏幕矩形内才计入活动像素。

输出的每个观测同时携带:射线方向、模型交点、解析法线、屏幕
``(u, v)`` 与两组条纹强度序列。这是"真值"一侧;求解端
(:mod:`mirror_core.optics.solve`)只允许使用射线、屏幕几何与强度
序列,不得直接读真值交点/法线。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from mirror_core.optics import fringes
from mirror_core.optics.linalg import (
    Vec3,
    line_plane_parameter,
    point_on_ray,
    vec_reflect,
)
from mirror_core.optics.surfaces import HeightSurface

#: 高度场求交的定步二分迭代数:区间 ~米级,2^-72 远小于双精度分辨
_BISECT_ITERATIONS = 72

#: 表面高度绝对值上界(米)。案例参数保证 |h| 远小于该值,用于确定
#: 二分包络;超出即视为参数错误。
_MAX_ABS_HEIGHT = 1.0


@dataclass(frozen=True)
class Camera:
    """针孔相机(M 系)。

    光心 ``center_m`` 在 ``+z`` 一侧,光轴沿 ``-z``;图像平面坐标
    与 M 系 ``+x``/``-y`` 对齐。``focal_length_px`` 为像素单位焦距。
    """

    center_m: Vec3
    image_width_px: int
    image_height_px: int
    focal_length_px: float

    def __post_init__(self) -> None:
        if self.image_width_px < 1 or self.image_height_px < 1:
            raise ValueError("图像宽高必须为正整数")
        if self.focal_length_px <= 0.0:
            raise ValueError("焦距必须为正")
        if self.center_m[2] <= 0.0:
            raise ValueError("相机光心必须在 +z 一侧(朝 -z 观看镜面)")

    def pixel_ray(self, column: int, row: int) -> Vec3:
        """像素 ``(column, row)`` 的视线方向(M 系单位向量)。

        像素按中心采样:``u_i = column + 0.5 - W/2``,
        ``v_j = row + 0.5 - H/2``,方向 ``(u_i, v_j, -f)`` 归一化。
        """
        if column not in range(self.image_width_px):
            raise ValueError(f"列序号越界:{column!r}")
        if row not in range(self.image_height_px):
            raise ValueError(f"行序号越界:{row!r}")
        u_i = column + 0.5 - self.image_width_px / 2.0
        v_j = row + 0.5 - self.image_height_px / 2.0
        d = (u_i, v_j, -self.focal_length_px)
        norm = (u_i * u_i + v_j * v_j + self.focal_length_px**2) ** 0.5
        return (d[0] / norm, d[1] / norm, d[2] / norm)


@dataclass(frozen=True)
class Screen:
    """矩形屏幕平面 ``z = center_m[2]``(M 系)。

    ``u ∈ [0, 1]`` 自左(−W/2)向右(+W/2),``v ∈ [0, 1]`` 自下
    (−H/2)向上(+H/2);米制映射与上游 ``DisplayShape`` 矩形模型一致。
    """

    center_m: Vec3
    width_m: float
    height_m: float

    def __post_init__(self) -> None:
        if self.width_m <= 0.0 or self.height_m <= 0.0:
            raise ValueError("屏幕宽高必须为正")
        if self.center_m[2] <= 0.0:
            raise ValueError("屏幕必须在 +z 一侧")

    def point_from_uv(self, u: float, v: float) -> Vec3:
        """屏幕分数坐标 → 米制点(M 系)。"""
        if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
            raise ValueError(f"屏幕分数坐标必须在 [0,1]:u={u!r}, v={v!r}")
        cx, cy, cz = self.center_m
        return (
            cx + (u - 0.5) * self.width_m,
            cy + (v - 0.5) * self.height_m,
            cz,
        )

    def uv_from_point(self, point: Vec3) -> tuple[float, float]:
        """米制点 → 屏幕分数坐标(不检查范围,掩膜另行判断)。"""
        cx, cy, _ = self.center_m
        return (
            (point[0] - cx) / self.width_m + 0.5,
            (point[1] - cy) / self.height_m + 0.5,
        )

    def contains(self, point: Vec3) -> bool:
        """点是否落在屏幕有效发光矩形内(边界含)。"""
        cx, cy, cz = self.center_m
        if abs(point[2] - cz) > 1e-12:
            return False
        return (
            abs(point[0] - cx) <= self.width_m / 2.0 + 1e-12
            and abs(point[1] - cy) <= self.height_m / 2.0 + 1e-12
        )


@dataclass(frozen=True)
class ForwardObservation:
    """一个活动像素的正向真值。"""

    pixel: tuple[int, int]
    #: 相机视线方向(M 系单位向量)
    ray_direction: Vec3
    #: 模型交点(M 系,米);求解端语义为 ``model_intersection``
    intersection_m: Vec3
    #: 解析表面法线(M 系)
    normal_m: Vec3
    #: 屏幕归一化对应坐标
    screen_uv: tuple[float, float]
    #: y 方向条纹强度序列(按上游帧序:周期升序、每周期 4 步相移)
    y_intensities: tuple[float, ...]
    #: x 方向条纹强度序列
    x_intensities: tuple[float, ...]


@dataclass(frozen=True)
class ForwardResult:
    """一次正向仿真的完整结果(行主序,仅活动像素)。"""

    camera: Camera
    screen: Screen
    surface_kind: str
    periods_x: tuple[float, ...]
    periods_y: tuple[float, ...]
    observations: tuple[ForwardObservation, ...]

    @property
    def active_pixel_count(self) -> int:
        return len(self.observations)


def intersect_height_field(
    origin: Vec3, direction: Vec3, surface: HeightSurface, where: str = "forward"
) -> Vec3:
    """射线与高度场 ``z = h(x, y)`` 的交点(定步二分,确定性)。

    要求射线沿 ``-z`` 前进且 ``|h| < 1 m``(案例参数保证);若两端点
    函数值同号,说明场景参数不满足前提,显式报错。
    """
    if direction[2] >= 0.0:
        raise ValueError(
            f"{where}: 射线必须朝 -z 前进,direction_z={direction[2]!r}"
        )

    def residual(t: float) -> float:
        point = point_on_ray(origin, direction, t)
        return point[2] - surface.height(point[0], point[1])

    # t=0 时相机在表面上方向,残差为正;取远端包络使 P_z < -1 m
    t_far = (origin[2] + _MAX_ABS_HEIGHT) / -direction[2]
    r_far = residual(t_far)
    if r_far >= 0.0:
        raise ValueError(
            f"{where}: 二分远端残差非负,高度场可能超出 ±{_MAX_ABS_HEIGHT} m 包络"
        )
    t_lo, t_hi = 0.0, t_far
    for _ in range(_BISECT_ITERATIONS):
        t_mid = (t_lo + t_hi) / 2.0
        if residual(t_mid) > 0.0:
            t_lo = t_mid
        else:
            t_hi = t_mid
    return point_on_ray(origin, direction, (t_lo + t_hi) / 2.0)


def trace_scene(
    surface: HeightSurface,
    camera: Camera,
    screen: Screen,
    periods_x: Sequence[float] | None = None,
    periods_y: Sequence[float] | None = None,
) -> ForwardResult:
    """逐像素正向追踪,生成带条纹编码的真值观测。"""

    if periods_x is None:
        periods_x = fringes.default_periods()
    if periods_y is None:
        periods_y = fringes.default_periods()
    px = tuple(float(p) for p in periods_x)
    py = tuple(float(p) for p in periods_y)

    screen_point = (screen.center_m[0], screen.center_m[1], screen.center_m[2])
    screen_normal = (0.0, 0.0, 1.0)
    observations: list[ForwardObservation] = []
    for row in range(camera.image_height_px):
        for column in range(camera.image_width_px):
            direction = camera.pixel_ray(column, row)
            hit = intersect_height_field(camera.center_m, direction, surface)
            normal = surface.normal(hit[0], hit[1])
            reflected = vec_reflect(direction, normal)
            if reflected[2] <= 0.0:
                continue  # 反射背离屏幕(远离光轴),非活动像素
            t_s = line_plane_parameter(
                hit, reflected, screen_point, screen_normal, where="forward.trace"
            )
            screen_hit = point_on_ray(hit, reflected, t_s)
            if not screen.contains(screen_hit):
                continue
            u, v = screen.uv_from_point(screen_hit)
            observations.append(
                ForwardObservation(
                    pixel=(column, row),
                    ray_direction=direction,
                    intersection_m=hit,
                    normal_m=normal,
                    screen_uv=(u, v),
                    y_intensities=tuple(fringes.encode_intensities(v, py)),
                    x_intensities=tuple(fringes.encode_intensities(u, px)),
                )
            )
    if not observations:
        raise ValueError("forward.trace: 没有活动像素,检查屏幕尺寸与表面参数")
    return ForwardResult(
        camera=camera,
        screen=screen,
        surface_kind=surface.kind,
        periods_x=px,
        periods_y=py,
        observations=tuple(observations),
    )
