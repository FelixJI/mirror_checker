"""回放求解:屏幕对应 → 斜率/法线 → 低阶面形拟合(参考管线)。

对齐上游 OpenCSP(固定提交 ``356e3a9``)的数学过程:

- ``slope_fitting_2d.calc_slopes``:镜面点 X 处法线取
  ``n = normalize(normalize(C - X) + normalize(S - X))``
  (相机方向与屏幕方向两单位向量的角平分线),斜率
  ``slope = (-n.x/n.z, -n.y/n.z)``;
- ``propagate_rays_to_plane``:射线与平面求交;
- ``slope_fitting_2d.poly_terms / fit_slope_ls``:斜率按全阶 2 多项式
  最小二乘拟合(普通 LS,robust bisquare 不在首版);
- ``Surface2DParabolic.fit_slopes``:斜率系数积分合成为曲面系数
  ``z = z0 + cx*x + cy*y + cxx*x² + cxy*xy + cyy*y²(+ 高阶)``。

**显式近似(单目深度-斜率耦合)**:仅凭(相机射线, 屏幕对应)无法
确定镜面点在射线上的位置——任意位置都存在满足反射定律的法线。上游
通过迭代面形拟合与 ``DistanceOpticScreen`` 实测距离固定该自由度;
本模块首版把镜面点取在**名义基准平面**(案例声明的外部约束,见
:class:`mirror_core.optics.surfaces.HeightSurface.reference_plane`),
误差量级为 `` sag * slope / 距离``,由 ``verify`` 报告量化,不做隐藏
补偿。斜率拟合不扣除任何整体趋势;高度常数项由斜率不可观,固定为 0
并显式记录(实施方案 §6.3/§6.4)。
"""

from __future__ import annotations

from dataclasses import dataclass

from mirror_core.optics import fringes
from mirror_core.optics.forward import ForwardResult, intersect_height_field
from mirror_core.optics.linalg import (
    Vec3,
    line_plane_parameter,
    point_on_ray,
    vec_norm,
)
from mirror_core.optics.surfaces import HeightSurface, Plane

#: 斜率多项式全阶默认值。2 阶(项 [1, x, x², y, xy, y²])等价于上游
#: ``Surface2DParabolic`` 的一阶斜率拟合 + 积分;4 阶进一步覆盖波纹
#: 案例的趋势项(实测纯二次面在 4 阶下同样精确恢复,高阶系数 ≈ 0,
#: 见 docs/optics.md)。**不要把阶数提到 6 以上**:小孔径(±0.07 m)
#: 下 ``x^12`` 量级 ~1e-14,法方程在双精度下病态。
DEFAULT_POLY_ORDER = 4

#: 迭代轮数:第 1 轮用名义基准平面,后续轮次用上一轮拟合面求交
#: (对齐上游 ``SlopeSolver.fit_surface`` 的外循环;上游为 4 轮,
#: 本模块实测 3 轮后系数变化低于 1e-12,见 docs/optics.md)
DEFAULT_ITERATIONS = 3


@dataclass(frozen=True)
class SolvedPixel:
    """一个活动像素的回放求解结果。"""

    pixel: tuple[int, int]
    #: 由条纹强度解码的屏幕归一化坐标(两轴统一 ``1 - unwrapped``)
    screen_uv: tuple[float, float]
    #: 模型交点:射线 ∩ 名义基准平面(米,M 系)
    intersection_m: Vec3
    #: 角平分法线(M 系)
    normal_m: Vec3
    #: 斜率 (dz/dx, dz/dy),来自法线
    slope_xy: tuple[float, float]


@dataclass(frozen=True)
class SurfaceFit:
    """斜率场多项式拟合与积分后的面形系数。

    高度常数项 ``z0`` 由斜率不可观,固定为 0(显式记录,不代表真实
    高度截距)。``cxx/cxy/cyy`` 是二次项——验收项"全局二次项不被
    去掉"的直接检查对象。
    """

    poly_order: int
    #: 多项式项标签,按上游 ``poly_terms`` 顺序(y 幂升序)
    terms: tuple[str, ...]
    slope_x_coefs: tuple[float, ...]
    slope_y_coefs: tuple[float, ...]
    #: 斜率拟合残差(最大绝对值)
    max_residual_x: float
    max_residual_y: float
    #: 通用积分高度系数 ``((x 幂, y 幕, 系数), ...)``,常数项固定 0
    height_coefs: tuple[tuple[int, int, float], ...]
    #: 二次及以下面形系数(命名报告字段;常数项由斜率不可观,固定 0)
    z0: float
    cx: float
    cy: float
    cxx: float
    cxy: float
    cyy: float
    #: 三次项(poly_order≥2 的斜率积分产生)
    cxxx: float
    cxxy: float
    cxyy: float
    cyyy: float

    def evaluate_height(self, x: float, y: float) -> float:
        """按积分系数求高度(常数项为 0)。"""
        return sum(c * x**i * y**j for i, j, c in self.height_coefs)


@dataclass(frozen=True)
class SolveResult:
    """整组回放求解结果。"""

    pixels: tuple[SolvedPixel, ...]
    fit: SurfaceFit
    #: 求解采用的基准平面(点, 单位法线)——固定深度自由度的外部约束
    reference_plane: Plane
    #: 实际执行的迭代轮数
    iterations: int


class _FittedSurface(HeightSurface):
    """把 :class:`SurfaceFit` 适配为高度场,供下一轮射线求交。"""

    kind = "fitted"

    def __init__(self, fit: SurfaceFit) -> None:
        self._fit = fit

    def height(self, x: float, y: float) -> float:
        return self._fit.evaluate_height(x, y)

    def gradient(self, x: float, y: float) -> tuple[float, float]:
        # 拟合面梯度即斜率多项式本身(解析,无差分)
        terms = poly_terms(self._fit.poly_order)

        def eval_poly(coefs: tuple[float, ...]) -> float:
            return sum(
                c * _term_value(t, x, y) for c, t in zip(coefs, terms)
            )

        return (eval_poly(self._fit.slope_x_coefs), eval_poly(self._fit.slope_y_coefs))


def decode_screen_uv(
    y_intensities, x_intensities, periods_y, periods_x
) -> tuple[float, float]:
    """从两组条纹强度解码屏幕 ``(u, v)``(归一化,两轴统一翻转)。"""
    unwrapped_x = fringes.unwrap_phase(x_intensities, periods_x)
    unwrapped_y = fringes.unwrap_phase(y_intensities, periods_y)
    return (
        fringes.screen_fraction_from_unwrapped(unwrapped_x),
        fringes.screen_fraction_from_unwrapped(unwrapped_y),
    )


def _bisector_normal(camera_center: Vec3, surface_point: Vec3, screen_point: Vec3) -> Vec3:
    """镜面点处满足反射定律的法线:两单位向量的角平分线。"""
    to_camera = tuple(c - s for c, s in zip(camera_center, surface_point))
    to_screen = tuple(s - p for s, p in zip(screen_point, surface_point))
    to_camera = tuple(c / vec_norm(to_camera) for c in to_camera)
    to_screen = tuple(c / vec_norm(to_screen) for c in to_screen)
    bisector = tuple(a + b for a, b in zip(to_camera, to_screen))
    norm = vec_norm(bisector)
    if norm < 1e-12:
        raise ValueError(
            f"solve: 角平分向量退化(相机与屏幕方向相反),surface_point={surface_point!r}"
        )
    return tuple(c / norm for c in bisector)


def poly_terms(order: int) -> tuple[tuple[int, int], ...]:
    """上游 ``slope_fitting_2d.poly_terms`` 项序:y 幂升序的全阶多项式。

    返回 ``(x 幂, y 幂)`` 元组;order=2 时为
    ``((0,0), (1,0), (2,0), (0,1), (1,1), (0,2))`` 即 ``[1, x, x²,
    y, xy, y²]``。
    """
    if order < 0:
        raise ValueError(f"多项式阶数不能为负,实际为 {order!r}")
    return tuple(
        (xi, yi)
        for yi in range(order + 1)
        for xi in range(order - yi + 1)
    )


def term_labels(terms: tuple[tuple[int, int], ...]) -> tuple[str, ...]:
    """幂次元组 → 人读标签(如 ``(2, 1)`` → ``"x^2 y"``)。"""

    def label(exponents: tuple[int, int]) -> str:
        xi, yi = exponents
        if xi == 0 and yi == 0:
            return "1"
        parts = []
        if xi:
            parts.append("x" if xi == 1 else f"x^{xi}")
        if yi:
            parts.append("y" if yi == 1 else f"y^{yi}")
        return "".join(parts)

    return tuple(label(e) for e in terms)


def _term_value(exponents: tuple[int, int], x: float, y: float) -> float:
    """项在 ``(x, y)`` 处的取值。"""
    xi, yi = exponents
    return (x**xi) * (y**yi)


def _solve_linear_system(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """高斯消元(部分主元)解线性方程组;奇异时显式报错。"""
    n = len(rhs)
    a = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-14:
            raise ValueError(f"solve: 法方程奇异(第 {col} 列主元过小),拟合退化")
        a[col], a[pivot] = a[pivot], a[col]
        for row in range(col + 1, n):
            factor = a[row][col] / a[col][col]
            for k in range(col, n + 1):
                a[row][k] -= factor * a[col][k]
    solution = [0.0] * n
    for i in range(n - 1, -1, -1):
        acc = a[i][n] - sum(a[i][k] * solution[k] for k in range(i + 1, n))
        solution[i] = acc / a[i][i]
    return solution


def _fit_poly_ls(
    points_xy: list[tuple[float, float]], values: list[float], order: int
) -> tuple[tuple[float, ...], float]:
    """单场最小二乘多项式拟合,返回(系数, 最大绝对残差)。"""
    terms = poly_terms(order)
    num_terms = len(terms)
    normal = [[0.0] * num_terms for _ in range(num_terms)]
    rhs = [0.0] * num_terms
    for (x, y), value in zip(points_xy, values):
        basis = [_term_value(t, x, y) for t in terms]
        for i in range(num_terms):
            rhs[i] += basis[i] * value
            for j in range(num_terms):
                normal[i][j] += basis[i] * basis[j]
    coefs = _solve_linear_system(normal, rhs)
    max_residual = 0.0
    for (x, y), value in zip(points_xy, values):
        fitted = sum(c * _term_value(t, x, y) for c, t in zip(coefs, terms))
        max_residual = max(max_residual, abs(fitted - value))
    return tuple(coefs), max_residual


def _integrate_surface_fit(
    slope_x_coefs: tuple[float, ...],
    slope_y_coefs: tuple[float, ...],
    order: int,
    max_residual_x: float,
    max_residual_y: float,
) -> SurfaceFit:
    """把斜率系数积分合成为面形系数(对齐上游 ``fit_slopes`` 思路)。

    通用规则:``z = Σ c_ij x^i y^j`` 满足
    ``a_ij = (i+1) * c_{i+1,j}``、``b_ij = (j+1) * c_{i,j+1}``;
    纯 x 项与纯 y 项由对应方向唯一确定,混合项两条路径都给出
    (可积性在精确数据下相等),取平均。上游一阶情形即
    ``[z0, cx0, cx1/2, cy0, (cx2+cy1)/2, cy2/2]``。
    """
    terms = poly_terms(order)

    def coef(coefs: tuple[float, ...], exponents: tuple[int, int]) -> float:
        return coefs[terms.index(exponents)] if exponents in terms else 0.0

    height: dict[tuple[int, int], float] = {}

    def put(exponents: tuple[int, int], value: float) -> None:
        if value != 0.0 or exponents in height:
            height[exponents] = height.get(exponents, 0.0) + value

    for i, j in terms:
        a_ij = coef(slope_x_coefs, (i, j))
        b_ij = coef(slope_y_coefs, (i, j))
        # dz/dx 路径:贡献 x^{i+1} y^j(j≥1 时为混合项,两条路径平均)
        put((i + 1, j), a_ij / (i + 1) / (2.0 if j >= 1 else 1.0))
        # dz/dy 路径:贡献 x^i y^{j+1}(i≥1 时为混合项)
        put((i, j + 1), b_ij / (j + 1) / (2.0 if i >= 1 else 1.0))

    def get(i: int, j: int) -> float:
        return height.get((i, j), 0.0)

    return SurfaceFit(
        poly_order=order,
        terms=term_labels(terms),
        slope_x_coefs=slope_x_coefs,
        slope_y_coefs=slope_y_coefs,
        max_residual_x=max_residual_x,
        max_residual_y=max_residual_y,
        height_coefs=tuple(
            (i, j, c) for (i, j), c in sorted(height.items())
        ),
        z0=0.0,
        cx=get(1, 0),
        cy=get(0, 1),
        cxx=get(2, 0),
        cxy=get(1, 1),
        cyy=get(0, 2),
        cxxx=get(3, 0),
        cxxy=get(2, 1),
        cxyy=get(1, 2),
        cyyy=get(0, 3),
    )


def solve_from_observations(
    forward_result: ForwardResult,
    reference_plane: Plane,
    poly_order: int = DEFAULT_POLY_ORDER,
    iterations: int = DEFAULT_ITERATIONS,
) -> SolveResult:
    """从正向观测(射线 + 条纹强度)回放求解斜率场并拟合面形。

    过程对齐上游 ``SlopeSolver``:第 1 轮把镜面点取在名义基准平面
    (案例声明的外部约束);之后每轮先用上一轮的拟合面与射线求交,
    再重算角平分法线并重新拟合。只使用射线方向、屏幕几何、条纹强度
    与基准平面;不读取正向真值的交点/法线。
    """
    if iterations < 1:
        raise ValueError(f"迭代轮数至少为 1,实际为 {iterations!r}")
    camera_center = forward_result.camera.center_m
    screen = forward_result.screen
    plane_point, plane_normal = reference_plane

    def run_pass(surface: HeightSurface | None) -> tuple[list[SolvedPixel], SurfaceFit]:
        solved: list[SolvedPixel] = []
        for obs in forward_result.observations:
            u, v = decode_screen_uv(
                list(obs.y_intensities),
                list(obs.x_intensities),
                forward_result.periods_y,
                forward_result.periods_x,
            )
            screen_point = screen.point_from_uv(u, v)
            if surface is None:
                t = line_plane_parameter(
                    camera_center,
                    obs.ray_direction,
                    plane_point,
                    plane_normal,
                    where="solve.ray_plane",
                )
                intersection = point_on_ray(camera_center, obs.ray_direction, t)
            else:
                intersection = intersect_height_field(
                    camera_center,
                    obs.ray_direction,
                    surface,
                    where="solve.ray_surface",
                )
            normal = _bisector_normal(camera_center, intersection, screen_point)
            slope = (-normal[0] / normal[2], -normal[1] / normal[2])
            solved.append(
                SolvedPixel(
                    pixel=obs.pixel,
                    screen_uv=(u, v),
                    intersection_m=intersection,
                    normal_m=normal,
                    slope_xy=slope,
                )
            )
        points_xy = [(p.intersection_m[0], p.intersection_m[1]) for p in solved]
        coefs_x, residual_x = _fit_poly_ls(
            points_xy, [p.slope_xy[0] for p in solved], poly_order
        )
        coefs_y, residual_y = _fit_poly_ls(
            points_xy, [p.slope_xy[1] for p in solved], poly_order
        )
        fit = _integrate_surface_fit(
            coefs_x, coefs_y, poly_order, residual_x, residual_y
        )
        return solved, fit

    solved: list[SolvedPixel] = []
    fit: SurfaceFit | None = None
    for _ in range(iterations):
        solved, fit = run_pass(None if fit is None else _FittedSurface(fit))
    assert fit is not None  # iterations >= 1 保证
    return SolveResult(
        pixels=tuple(solved),
        fit=fit,
        reference_plane=reference_plane,
        iterations=iterations,
    )
