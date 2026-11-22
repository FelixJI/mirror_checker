"""标准合成案例注册表与解析交叉验证(实施方案 PR-02)。

七类案例覆盖验收要求:平面、倾斜平面、正/负柱面、旋转 90° 柱面、
正/负球面、鞍形、低频二次 + 波纹。所有参数固定硬编码,输出确定
(不使用随机数与当前时间)。

场景量级对齐家用镜检测:屏距 ~0.25 m(平板尺寸 0.32 × 0.22 m),
镜面孔径 ±0.07 m,曲率半径 200–300 m。

每个案例的验证报告(``verify_case``)给出 PR-02 验收项的数值结论:
法线角误差、屏幕坐标解码误差、二次曲面系数与解析期望的偏差、以及
"倾斜平面不产生假曲率 / 90° 方向可识别 / 全局二次项保留"的判定。
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

from mirror_core.contracts import ContractError, SCHEMA_VERSION
from mirror_core.optics import forward as forward_module
from mirror_core.optics import solve as solve_module
from mirror_core.optics.linalg import vec_angle_between
from mirror_core.optics.surfaces import (
    CylinderSurface,
    HeightSurface,
    PlaneSurface,
    RippleSurface,
    SaddleSurface,
    SphereSurface,
    TiltedPlaneSurface,
)

#: 案例共用场景(单位:米、像素)
CAMERA = forward_module.Camera(
    center_m=(0.0, 0.0, 0.18),
    image_width_px=48,
    image_height_px=32,
    focal_length_px=64.0,
)
SCREEN = forward_module.Screen(
    center_m=(0.0, 0.0, 0.25), width_m=0.32, height_m=0.22
)

#: 求解参数(默认 4 阶 + 3 轮迭代,依据 docs/optics.md 误差预算)
SOLVE_POLY_ORDER = solve_module.DEFAULT_POLY_ORDER
SOLVE_ITERATIONS = solve_module.DEFAULT_ITERATIONS

#: 各案例二次曲面系数的解析期望:(cxx, cxy, cyy)
_EXPECTED_QUADRATIC = {
    "plane": (0.0, 0.0, 0.0),
    "tilted_plane": (0.0, 0.0, 0.0),
    "cylinder_pos": (1.0 / 400.0, 0.0, 0.0),
    "cylinder_neg": (-1.0 / 400.0, 0.0, 0.0),
    "cylinder_y": (0.0, 0.0, 1.0 / 400.0),
    "sphere_pos": (1.0 / 600.0, 0.0, 1.0 / 600.0),
    "sphere_neg": (-1.0 / 600.0, 0.0, -1.0 / 600.0),
    "saddle": (0.001, 0.0, -0.001),
    "ripple": (0.0005, 0.0, 0.0),
}

#: ripple 案例:正弦斜率向低阶多项式的投影泄漏预算(相对偏差)
_RIPPLE_QUADRATIC_TOLERANCE = 0.15

#: 光滑面法线角误差预算(弧度;ripple 放宽到 2e-6)
_SMOOTH_NORMAL_ANGLE_BUDGET = 1e-7
_RIPPLE_NORMAL_ANGLE_BUDGET = 2e-6

#: 屏幕坐标解码误差预算
_UV_DECODE_BUDGET = 1e-12


@dataclass(frozen=True)
class CaseDefinition:
    """一个标准合成案例的完整定义。"""

    name: str
    description: str
    surface: HeightSurface

    @property
    def expected_quadratic(self) -> tuple[float, float, float]:
        return _EXPECTED_QUADRATIC[self.name]


#: 案例注册表(顺序即文档顺序;名称稳定,作为 CLI 与测试的键)
CASES: dict[str, CaseDefinition] = {
    case.name: case
    for case in (
        CaseDefinition(
            name="plane",
            description="理想平面镜 h=0",
            surface=PlaneSurface(),
        ),
        CaseDefinition(
            name="tilted_plane",
            description="倾斜平面 h=0.004x-0.003y(刚体姿态,无曲率)",
            surface=TiltedPlaneSurface(slope_x=0.004, slope_y=-0.003),
        ),
        CaseDefinition(
            name="cylinder_pos",
            description="正柱面 h=+x²/(2·200)(凹面朝相机,母线沿 y)",
            surface=CylinderSurface(radius_m=200.0, sign=1.0, axis="x"),
        ),
        CaseDefinition(
            name="cylinder_neg",
            description="负柱面 h=-x²/(2·200)(凸面朝相机)",
            surface=CylinderSurface(radius_m=200.0, sign=-1.0, axis="x"),
        ),
        CaseDefinition(
            name="cylinder_y",
            description="柱面旋转 90°(母线沿 x,弯曲轴 y)",
            surface=CylinderSurface(radius_m=200.0, sign=1.0, axis="y"),
        ),
        CaseDefinition(
            name="sphere_pos",
            description="球面 sag,R=300,凹面朝相机",
            surface=SphereSurface(radius_m=300.0, sign=1.0),
        ),
        CaseDefinition(
            name="sphere_neg",
            description="球面 sag,R=300,凸面朝相机",
            surface=SphereSurface(radius_m=300.0, sign=-1.0),
        ),
        CaseDefinition(
            name="saddle",
            description="鞍形 h=0.001·(x²-y²)",
            surface=SaddleSurface(coefficient_a=0.001),
        ),
        CaseDefinition(
            name="ripple",
            description="低频二次 + 横向波纹 h=5e-4·x²+3e-7·cos(2πx/0.01+0.7)",
            surface=RippleSurface(
                quad_a=0.0005,
                ripple_amp=3e-7,
                ripple_wavelength=0.01,
                ripple_phase_rad=0.7,
            ),
        ),
    )
}


def case_definition(name: str) -> CaseDefinition:
    """按名称取案例定义;未知名称显式报错。"""
    case = CASES.get(name)
    if case is None:
        known = ", ".join(sorted(CASES))
        raise ContractError(f"未知合成案例 {name!r};可用案例:{known}")
    return case


@dataclass(frozen=True)
class CaseRun:
    """一次案例执行:正向真值 + 回放求解。"""

    definition: CaseDefinition
    forward_result: forward_module.ForwardResult
    solve_result: solve_module.SolveResult


#: 上游公式来源登记(与 docs/upstream.md 对照表一致)
_UPSTREAM_SOURCES = {
    "commit": "356e3a98eeb880146b57955112b1a9759692531f",
    "license": "Apache-2.0",
    "formula_sources": [
        "opencsp/app/sofast/lib/Fringes.py:get_sinusoids/from_num_periods",
        "opencsp/app/sofast/lib/image_processing.py:unwrap_phase",
        "opencsp/app/sofast/lib/DisplayShape.py(矩形屏幕米制映射)",
        "opencsp/common/lib/deflectometry/slope_fitting_2d.py:calc_slopes/poly_terms",
        "opencsp/common/lib/deflectometry/SlopeSolver.py(迭代求交思路)",
        "opencsp/app/sofast/lib/Surface2DParabolic.py:fit_slopes(系数积分合成)",
    ],
}

#: 导出 JSON 的公共说明字段
_COMMON_META = {
    "provenance": "synthetic",
    "coordinate_frame": {
        "id": "M",
        "description": "镜面参考系:原点为名义镜面参考点,+z 指向相机与屏幕一侧",
        "normal_convention": "n = normalize(-dh/dx, -dh/dy, 1),+z 分量为正",
    },
    "units": {
        "length": "m",
        "angle": "rad",
        "screen_coord": "normalized [0,1] over active screen rectangle",
        "intensity": "normalized [0,1] grayscale",
    },
}


def _json_bytes(obj: dict) -> bytes:
    """数据文件序列化(与 sample.py 一致:indent=2 + 尾换行)。"""
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def _round(value: float, digits: int = 12) -> float:
    """导出数值的稳定表示(低于 1e-12 的量按 0 记录)。"""
    return round(float(value), digits)


def _vec3_list(vec) -> list[float]:
    return [_round(c) for c in vec]


def _surface_parameters(surface: HeightSurface) -> dict:
    """表面的规范参数(数据类字段;非数据类表面为空)。"""
    if dataclasses.is_dataclass(surface):
        return {
            key: _round(value) if isinstance(value, float) else value
            for key, value in dataclasses.asdict(surface).items()
        }
    return {}


def case_document(run: CaseRun) -> dict:
    """案例定义文档(case.json 内容)。"""
    case = run.definition
    plane_point, plane_normal = case.surface.reference_plane
    return {
        "schema_version": SCHEMA_VERSION,
        "case": case.name,
        "description": case.description,
        **_COMMON_META,
        "scene": {
            "camera": {
                "model": "pinhole",
                "center_m": _vec3_list(CAMERA.center_m),
                "image_width_px": CAMERA.image_width_px,
                "image_height_px": CAMERA.image_height_px,
                "focal_length_px": CAMERA.focal_length_px,
                "pixel_sampling": "pixel centers (i+0.5, j+0.5)",
                "image_axes": "列 i 向 +x,行 j 向 -y",
            },
            "screen": {
                "center_m": _vec3_list(SCREEN.center_m),
                "width_m": _round(SCREEN.width_m),
                "height_m": _round(SCREEN.height_m),
                "metric_mapping": "x=(u-0.5)*W, y=(v-0.5)*H(对齐上游 DisplayShape)",
                "distance_semantics": "DistanceOpticScreen = 镜面参考点(M 原点)到屏幕中心的距离",
            },
        },
        "surface": {
            "kind": case.surface.kind,
            "height_field": "z = h(x, y),M 系",
            "parameters": _surface_parameters(case.surface),
            "reference_plane": {
                "point_m": _vec3_list(plane_point),
                "normal": _vec3_list(plane_normal),
                "role": "求解端深度自由度的外部约束",
            },
        },
        "fringes": {
            "periods_x": list(run.forward_result.periods_x),
            "periods_y": list(run.forward_result.periods_y),
            "phase_shifts": 4,
            "frame_order": "y 方向在前,x 方向在后",
        },
        "solve": {
            "poly_order": run.solve_result.fit.poly_order,
            "iterations": run.solve_result.iterations,
        },
        "upstream": _UPSTREAM_SOURCES,
    }


def forward_document(run: CaseRun) -> dict:
    """正向真值文档(forward.json 内容):逐像素相位/屏幕对应/交点/法线。"""
    result = run.forward_result
    observations = []
    for obs in result.observations:
        observations.append(
            {
                "pixel": [obs.pixel[0], obs.pixel[1]],
                "ray_direction": _vec3_list(obs.ray_direction),
                "model_intersection_m": _vec3_list(obs.intersection_m),
                "normal_m": _vec3_list(obs.normal_m),
                "screen_uv": [_round(obs.screen_uv[0]), _round(obs.screen_uv[1])],
                "y_intensities": [_round(v) for v in obs.y_intensities],
                "x_intensities": [_round(v) for v in obs.x_intensities],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "case": run.definition.name,
        **_COMMON_META,
        "point_geometry_provenance": "model_intersection",
        "active_pixels": len(observations),
        "observations": observations,
    }


def replay_document(run: CaseRun) -> dict:
    """回放求解文档(replay.json 内容):解码坐标、解算交点/法线与拟合。"""
    solve_result = run.solve_result
    fit = solve_result.fit
    pixels = [
        {
            "pixel": [p.pixel[0], p.pixel[1]],
            "screen_uv": [_round(p.screen_uv[0]), _round(p.screen_uv[1])],
            "model_intersection_m": _vec3_list(p.intersection_m),
            "normal_m": _vec3_list(p.normal_m),
            "slope_xy": [_round(p.slope_xy[0]), _round(p.slope_xy[1])],
        }
        for p in solve_result.pixels
    ]
    plane_point, plane_normal = solve_result.reference_plane
    return {
        "schema_version": SCHEMA_VERSION,
        "case": run.definition.name,
        **_COMMON_META,
        "point_geometry_provenance": "model_intersection",
        "solver": {
            "inputs": "射线方向、屏幕几何、条纹强度、名义基准平面(不读取正向真值交点/法线)",
            "reference_plane": {
                "point_m": _vec3_list(plane_point),
                "normal": _vec3_list(plane_normal),
            },
            "iterations": solve_result.iterations,
            "poly_order": fit.poly_order,
            "height_constant_unobservable": True,
        },
        "fit": {
            "terms": list(fit.terms),
            "slope_x_coefs": [_round(c) for c in fit.slope_x_coefs],
            "slope_y_coefs": [_round(c) for c in fit.slope_y_coefs],
            "max_residual_x": _round(fit.max_residual_x, 15),
            "max_residual_y": _round(fit.max_residual_y, 15),
            "height_coefs": [
                [i, j, _round(c, 15)] for i, j, c in fit.height_coefs
            ],
            "quadratic": {
                "z0": fit.z0,
                "cx": _round(fit.cx, 15),
                "cy": _round(fit.cy, 15),
                "cxx": _round(fit.cxx, 15),
                "cxy": _round(fit.cxy, 15),
                "cyy": _round(fit.cyy, 15),
            },
        },
        "pixels": pixels,
    }


def export_case(run: CaseRun, output_dir: Path) -> list[Path]:
    """把案例的四个 JSON 文档写入输出目录(确定性字节)。

    目录不存在则创建;已存在时覆盖同名文件。
    """
    output_dir = Path(output_dir)
    if output_dir.exists() and not output_dir.is_dir():
        raise ContractError(f"输出路径已存在且不是目录:{output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    documents = {
        "case.json": case_document(run),
        "forward.json": forward_document(run),
        "replay.json": replay_document(run),
        "verify.json": verify_case(run),
    }
    written: list[Path] = []
    for filename in ("case.json", "forward.json", "replay.json", "verify.json"):
        path = output_dir / filename
        path.write_bytes(_json_bytes(documents[filename]))
        written.append(path)
    return written


def run_case(name: str) -> CaseRun:
    """执行案例:正向仿真 + 条纹编码,再仅凭观测回放求解。"""
    case = case_definition(name)
    forward_result = forward_module.trace_scene(case.surface, CAMERA, SCREEN)
    solve_result = solve_module.solve_from_observations(
        forward_result,
        case.surface.reference_plane,
        poly_order=SOLVE_POLY_ORDER,
        iterations=SOLVE_ITERATIONS,
    )
    return CaseRun(
        definition=case,
        forward_result=forward_result,
        solve_result=solve_result,
    )


def _check(name: str, passed: bool, detail: str) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


def verify_case(run: CaseRun) -> dict:
    """对案例执行结果生成 PR-02 验收报告(JSON 可序列化)。

    报告分三部分:交叉验证数值(法线角误差、解码误差、系数偏差)、
    验收项判定、以及求解近似说明(基准平面约束、高度常数不可观)。
    """
    surface = run.definition.surface
    fit = run.solve_result.fit

    max_angle_error = 0.0
    max_uv_error = 0.0
    truth = {obs.pixel: obs for obs in run.forward_result.observations}
    for pixel_result in run.solve_result.pixels:
        analytic = surface.normal(
            pixel_result.intersection_m[0], pixel_result.intersection_m[1]
        )
        max_angle_error = max(
            max_angle_error, vec_angle_between(pixel_result.normal_m, analytic)
        )
        true_uv = truth[pixel_result.pixel].screen_uv
        max_uv_error = max(
            max_uv_error,
            abs(pixel_result.screen_uv[0] - true_uv[0]),
            abs(pixel_result.screen_uv[1] - true_uv[1]),
        )

    expected_cxx, expected_cxy, expected_cyy = run.definition.expected_quadratic
    name = run.definition.name

    # 二次项相对偏差(期望为 0 时用光滑面二次项的绝对预算)
    def rel_error(actual: float, expected: float) -> float:
        if expected == 0.0:
            return abs(actual)
        return abs(actual - expected) / abs(expected)

    quad_tolerance = (
        _RIPPLE_QUADRATIC_TOLERANCE if name == "ripple" else 1e-3
    )
    checks = [
        _check(
            "analytic_normal_cross_validation",
            max_angle_error
            <= (_RIPPLE_NORMAL_ANGLE_BUDGET if name == "ripple" else _SMOOTH_NORMAL_ANGLE_BUDGET),
            f"max_normal_angle_error_rad={max_angle_error:.3e}",
        ),
        _check(
            "screen_uv_decode",
            max_uv_error <= _UV_DECODE_BUDGET,
            f"max_uv_error={max_uv_error:.3e}",
        ),
        _check(
            "quadratic_coefficients",
            rel_error(fit.cxx, expected_cxx) <= quad_tolerance
            and rel_error(fit.cxy, expected_cxy) <= 1e-3
            and rel_error(fit.cyy, expected_cyy) <= quad_tolerance,
            f"cxx={fit.cxx:+.6e}(期望 {expected_cxx:+.6e}),"
            f"cxy={fit.cxy:+.3e},cyy={fit.cyy:+.6e}(期望 {expected_cyy:+.6e})",
        ),
    ]
    if name in ("plane", "tilted_plane"):
        checks.append(
            _check(
                "no_fake_curvature_on_plane",
                abs(fit.cxx) < 1e-15 and abs(fit.cyy) < 1e-15 and abs(fit.cxy) < 1e-15,
                "平面/倾斜平面的二次系数应为机器零",
            )
        )
    if name in ("cylinder_pos", "cylinder_neg", "cylinder_y"):
        bend_x = name != "cylinder_y"
        dominant, other = (fit.cxx, fit.cyy) if bend_x else (fit.cyy, fit.cxx)
        checks.append(
            _check(
                "direction_identifiable_90deg",
                abs(dominant) > 100.0 * max(abs(other), 1e-12),
                f"主曲率轴应为 {'x' if bend_x else 'y'}",
            )
        )
    if name.startswith("sphere"):
        checks.append(
            _check(
                "global_quadratic_retained",
                abs(fit.cxx) > 0.5 * abs(expected_cxx)
                and abs(fit.cyy) > 0.5 * abs(expected_cyy),
                "全局二次项未被拟合去掉",
            )
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "case": name,
        "provenance": "synthetic",
        "units": {"length": "m", "angle": "rad", "screen_coord": "normalized [0,1]"},
        "cross_validation": {
            "max_normal_angle_error_rad": round(max_angle_error, 15),
            "max_screen_uv_decode_error": round(max_uv_error, 15),
            "expected_quadratic_cxx_cxy_cyy": [expected_cxx, expected_cxy, expected_cyy],
            "fitted_quadratic_cxx_cxy_cyy": [fit.cxx, fit.cxy, fit.cyy],
        },
        "checks": checks,
        "all_passed": all(check["passed"] for check in checks),
        "solver_notes": {
            "reference_plane_constraint": "深度自由度由案例声明的名义基准平面固定(外部约束)",
            "height_constant_unobservable": "高度常数项由斜率不可观,固定为 0",
            "iterations": run.solve_result.iterations,
            "poly_order": fit.poly_order,
        },
    }
