"""``mirror_core.optics.solve`` 的验收测试(实施方案 PR-02 验收项)。

覆盖:倾斜平面不产生假曲率、90° 方向变化可识别、全局二次项不被
去掉、解析结果交叉验证、条纹解码回环与迭代收敛。
"""

from __future__ import annotations

import unittest

from mirror_core.optics import forward, solve
from mirror_core.optics.linalg import vec_angle_between
from mirror_core.optics.surfaces import (
    CylinderSurface,
    PlaneSurface,
    RippleSurface,
    SaddleSurface,
    SphereSurface,
    TiltedPlaneSurface,
)

#: 案例级场景(与 mirror_core.optics.cases 的规范参数一致)
CAMERA = forward.Camera(
    center_m=(0.0, 0.0, 0.18),
    image_width_px=48,
    image_height_px=32,
    focal_length_px=64.0,
)
SCREEN = forward.Screen(center_m=(0.0, 0.0, 0.25), width_m=0.32, height_m=0.22)

SURFACES = {
    "plane": PlaneSurface(),
    "tilted_plane": TiltedPlaneSurface(slope_x=0.004, slope_y=-0.003),
    "cylinder_pos": CylinderSurface(radius_m=200.0, sign=1.0, axis="x"),
    "cylinder_neg": CylinderSurface(radius_m=200.0, sign=-1.0, axis="x"),
    "cylinder_y": CylinderSurface(radius_m=200.0, sign=1.0, axis="y"),
    "sphere_pos": SphereSurface(radius_m=300.0, sign=1.0),
    "sphere_neg": SphereSurface(radius_m=300.0, sign=-1.0),
    "saddle": SaddleSurface(coefficient_a=0.001),
    "ripple": RippleSurface(
        quad_a=0.0005, ripple_amp=3e-7, ripple_wavelength=0.01, ripple_phase_rad=0.7
    ),
}


class _CaseRun:
    """一次正向 + 回放的缓存结果与交叉验证量。"""

    def __init__(self, surface) -> None:
        self.surface = surface
        self.forward_result = forward.trace_scene(surface, CAMERA, SCREEN)
        self.solve_result = solve.solve_from_observations(
            self.forward_result, surface.reference_plane
        )
        self.max_normal_angle_error_rad = 0.0
        self.max_uv_error = 0.0
        truth = {obs.pixel: obs for obs in self.forward_result.observations}
        for pixel_result in self.solve_result.pixels:
            analytic = surface.normal(
                pixel_result.intersection_m[0], pixel_result.intersection_m[1]
            )
            self.max_normal_angle_error_rad = max(
                self.max_normal_angle_error_rad,
                vec_angle_between(pixel_result.normal_m, analytic),
            )
            true_uv = truth[pixel_result.pixel].screen_uv
            self.max_uv_error = max(
                self.max_uv_error,
                abs(pixel_result.screen_uv[0] - true_uv[0]),
                abs(pixel_result.screen_uv[1] - true_uv[1]),
            )


class AcceptanceTest(unittest.TestCase):
    """PR-02 验收项(数值断言;依据 docs/optics.md 的实测误差预算)。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.runs = {name: _CaseRun(surface) for name, surface in SURFACES.items()}

    # --- 验收:平面倾斜不会生成假曲率 ---

    def test_plane_no_fake_curvature(self):
        fit = self.runs["plane"].solve_result.fit
        for coef in (fit.cxx, fit.cxy, fit.cyy):
            self.assertLess(abs(coef), 1e-15, f"平面镜出现假曲率系数 {coef!r}")
        self.assertEqual(fit.z0, 0.0, "高度常数项不可观,应固定为 0")

    def test_tilted_plane_no_fake_curvature(self):
        run = self.runs["tilted_plane"]
        fit = run.solve_result.fit
        for coef in (fit.cxx, fit.cxy, fit.cyy):
            self.assertLess(abs(coef), 1e-15, f"倾斜平面出现假曲率系数 {coef!r}")
        # 一次项 = 倾斜斜率
        self.assertAlmostEqual(fit.cx, 0.004, places=12)
        self.assertAlmostEqual(fit.cy, -0.003, places=12)
        # 法线恒定且等于解析法线
        for pixel_result in run.solve_result.pixels:
            analytic = run.surface.normal(
                pixel_result.intersection_m[0], pixel_result.intersection_m[1]
            )
            self.assertAlmostEqual(
                vec_angle_between(pixel_result.normal_m, analytic), 0.0, places=14
            )

    # --- 验收:90° 方向变化可识别 ---

    def test_cylinder_sign_and_direction(self):
        pos = self.runs["cylinder_pos"].solve_result.fit
        neg = self.runs["cylinder_neg"].solve_result.fit
        turned = self.runs["cylinder_y"].solve_result.fit
        # x 轴柱面:cxx = +1/(2R) = 2.5e-3,y 方向无曲率
        self.assertAlmostEqual(pos.cxx, 1.0 / 400.0, delta=1.0 / 400.0 * 1e-3)
        self.assertLess(abs(pos.cyy), 1e-7)
        self.assertLess(abs(pos.cxy), 1e-15)
        # 符号翻转
        self.assertAlmostEqual(neg.cxx, -1.0 / 400.0, delta=1.0 / 400.0 * 1e-3)
        # 旋转 90°:主曲率轴从 x 换到 y
        self.assertAlmostEqual(turned.cyy, 1.0 / 400.0, delta=1.0 / 400.0 * 1e-3)
        self.assertLess(abs(turned.cxx), 1e-7)
        self.assertGreater(abs(pos.cxx), 100.0 * abs(pos.cyy), "x 柱面主轴应在 x")
        self.assertGreater(abs(turned.cyy), 100.0 * abs(turned.cxx), "y 柱面主轴应在 y")

    # --- 验收:全局二次项不被去掉 ---

    def test_sphere_retains_global_quadratic(self):
        for name, sign in (("sphere_pos", 1.0), ("sphere_neg", -1.0)):
            fit = self.runs[name].solve_result.fit
            expected = sign / 600.0  # 1/(2R)
            self.assertAlmostEqual(
                fit.cxx, expected, delta=abs(expected) * 1e-3, msg=name
            )
            self.assertAlmostEqual(
                fit.cyy, expected, delta=abs(expected) * 1e-3, msg=name
            )
            self.assertLess(abs(fit.cxy), 1e-15, msg=name)
            # 明确保留(未被拟合或去趋势消去)
            self.assertGreater(abs(fit.cxx), 0.5 * abs(expected), msg=name)

    def test_saddle_opposite_curvatures(self):
        fit = self.runs["saddle"].solve_result.fit
        self.assertAlmostEqual(fit.cxx, 0.001, delta=0.001 * 1e-3)
        self.assertAlmostEqual(fit.cyy, -0.001, delta=0.001 * 1e-3)
        self.assertLess(abs(fit.cxy), 1e-15)

    def test_ripple_retains_low_frequency_trend(self):
        run = self.runs["ripple"]
        fit = run.solve_result.fit
        # 低频二次项保留(符号正确、量级在 15% 内;正弦斜率向低阶
        # 多项式的投影泄漏是有记录的局限,见 docs/optics.md)
        self.assertGreater(fit.cxx, 0.0)
        self.assertLess(abs(fit.cxx - 0.0005) / 0.0005, 0.15)
        # 波纹留在斜率残差场中(幅值 ≈ ripple_amp * k = 3e-7 * 2π/0.01)
        ripple_slope_amplitude = 3e-7 * 2.0 * 3.141592653589793 / 0.01
        self.assertGreater(fit.max_residual_x, 0.5 * ripple_slope_amplitude)
        self.assertLess(fit.max_residual_x, 1.5 * ripple_slope_amplitude)

    # --- 验收:解析结果交叉验证仿真器 ---

    def test_normal_cross_validation(self):
        # 光滑面:迭代求解后法线角误差远小于 1e-7 rad
        thresholds = {
            "plane": 1e-15,
            "tilted_plane": 1e-15,
            "cylinder_pos": 1e-7,
            "cylinder_neg": 1e-7,
            "cylinder_y": 1e-7,
            "sphere_pos": 1e-7,
            "sphere_neg": 1e-7,
            "saddle": 1e-7,
            "ripple": 2e-6,  # 波纹的平滑拟合残余
        }
        for name, threshold in thresholds.items():
            error = self.runs[name].max_normal_angle_error_rad
            self.assertLess(
                error, threshold, msg=f"{name} 法线角误差 {error:.2e} 超过 {threshold:.0e}"
            )

    def test_screen_uv_decode_roundtrip(self):
        for name, run in self.runs.items():
            self.assertLess(
                run.max_uv_error, 1e-12, msg=f"{name} 屏幕坐标解码误差过大"
            )

    def test_height_fit_consistent_with_slope_fit(self):
        # evaluate_height 的偏导应等于斜率多项式(积分自洽,中心差分验证)
        fit = self.runs["cylinder_pos"].solve_result.fit
        for x, y in ((0.0, 0.0), (0.03, -0.02), (-0.05, 0.04)):
            d = 1e-7
            dh_dx = (fit.evaluate_height(x + d, y) - fit.evaluate_height(x - d, y)) / (2 * d)
            dh_dy = (fit.evaluate_height(x, y + d) - fit.evaluate_height(x, y - d)) / (2 * d)
            terms = solve.poly_terms(fit.poly_order)
            sx = sum(
                c * (x**i) * (y**j)
                for c, (i, j) in zip(fit.slope_x_coefs, terms)
            )
            sy = sum(
                c * (x**i) * (y**j)
                for c, (i, j) in zip(fit.slope_y_coefs, terms)
            )
            self.assertAlmostEqual(dh_dx, sx, places=9)
            self.assertAlmostEqual(dh_dy, sy, places=9)


class SolverBehaviorTest(unittest.TestCase):
    def test_iteration_reduces_depth_slope_bias(self):
        surface = SURFACES["cylinder_pos"]
        forward_result = forward.trace_scene(surface, CAMERA, SCREEN)
        errors = []
        for iterations in (1, 3):
            result = solve.solve_from_observations(
                forward_result, surface.reference_plane, iterations=iterations
            )
            max_error = max(
                vec_angle_between(
                    p.normal_m,
                    surface.normal(p.intersection_m[0], p.intersection_m[1]),
                )
                for p in result.pixels
            )
            errors.append(max_error)
        self.assertLess(errors[1], errors[0] / 100.0, "迭代应显著收敛深度-斜率耦合偏差")
        self.assertEqual(result.iterations, 3)

    def test_reference_plane_must_match_external_constraint(self):
        # 基准平面偏离真实约束(平移 1 mm)时,法线出现可测系统偏差;
        # 该偏差即"深度自由度由外部约束固定"的量化体现
        surface = SURFACES["cylinder_pos"]
        forward_result = forward.trace_scene(surface, CAMERA, SCREEN)
        good = solve.solve_from_observations(forward_result, surface.reference_plane)
        shifted_plane = ((0.0, 0.0, 0.001), (0.0, 0.0, 1.0))
        bad = solve.solve_from_observations(forward_result, shifted_plane)

        def max_error(result):
            return max(
                vec_angle_between(
                    p.normal_m,
                    surface.normal(p.intersection_m[0], p.intersection_m[1]),
                )
                for p in result.pixels
            )

        self.assertGreater(max_error(bad), 10.0 * max_error(good))

    def test_poly_terms_and_labels(self):
        self.assertEqual(solve.poly_terms(0), ((0, 0),))
        self.assertEqual(
            solve.poly_terms(2),
            ((0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (0, 2)),
        )
        self.assertEqual(
            solve.term_labels(solve.poly_terms(2)),
            ("1", "x", "x^2", "y", "xy", "y^2"),
        )
        with self.assertRaises(ValueError):
            solve.poly_terms(-1)

    def test_singular_fit_raises(self):
        # 阶数过高在小孔径下病态,必须显式报错而非静默给出坏系数
        surface = SURFACES["plane"]
        forward_result = forward.trace_scene(surface, CAMERA, SCREEN)
        with self.assertRaisesRegex(ValueError, "奇异"):
            solve.solve_from_observations(
                forward_result, surface.reference_plane, poly_order=8
            )

    def test_invalid_iterations(self):
        surface = SURFACES["plane"]
        forward_result = forward.trace_scene(surface, CAMERA, SCREEN)
        with self.assertRaises(ValueError):
            solve.solve_from_observations(
                forward_result, surface.reference_plane, iterations=0
            )

    def test_decode_screen_uv(self):
        from mirror_core.optics import fringes

        periods = fringes.default_periods()
        u, v = 0.37, 0.81
        y_seq = fringes.encode_intensities(v, periods)
        x_seq = fringes.encode_intensities(u, periods)
        decoded = solve.decode_screen_uv(y_seq, x_seq, periods, periods)
        self.assertAlmostEqual(decoded[0], u, places=9)
        self.assertAlmostEqual(decoded[1], v, places=9)


if __name__ == "__main__":
    unittest.main()
