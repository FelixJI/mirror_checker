"""``mirror_core.optics.surfaces`` 的单元测试:解析高度/法线/Hessian 互证。"""

from __future__ import annotations

import math
import unittest

from mirror_core.optics import surfaces
from mirror_core.optics.linalg import vec_angle_between, vec_norm


def _numeric_gradient(surface, x: float, y: float, d: float = 1e-7) -> tuple[float, float]:
    """中心差分数值梯度,用于互证解析梯度。"""
    gx = (surface.height(x + d, y) - surface.height(x - d, y)) / (2.0 * d)
    gy = (surface.height(x, y + d) - surface.height(x, y - d)) / (2.0 * d)
    return (gx, gy)


def _numeric_hessian(surface, x: float, y: float, d: float = 1e-4) -> surfaces.Hessian:
    """差分数值 Hessian,用于互证解析 Hessian。"""
    h = surface.height
    dxx = (h(x + d, y) - 2.0 * h(x, y) + h(x - d, y)) / (d * d)
    dyy = (h(x, y + d) - 2.0 * h(x, y) + h(x, y - d)) / (d * d)
    dxy = (
        h(x + d, y + d) - h(x + d, y - d) - h(x - d, y + d) + h(x - d, y - d)
    ) / (4.0 * d * d)
    return ((dxx, dxy), (dxy, dyy))


class SurfaceConsistencyTest(unittest.TestCase):
    """各表面:解析梯度/Hessian 与数值差分一致;法线与约定一致。"""

    CASES = [
        surfaces.PlaneSurface(),
        surfaces.TiltedPlaneSurface(slope_x=0.004, slope_y=-0.003),
        surfaces.CylinderSurface(radius_m=200.0, sign=1.0, axis="x"),
        surfaces.CylinderSurface(radius_m=150.0, sign=-1.0, axis="y"),
        surfaces.SphereSurface(radius_m=300.0, sign=1.0),
        surfaces.SphereSurface(radius_m=300.0, sign=-1.0),
        surfaces.SaddleSurface(coefficient_a=0.0008),
        surfaces.RippleSurface(
            quad_a=0.0005,
            ripple_amp=2e-6,
            ripple_wavelength=0.08,
            ripple_phase_rad=0.7,
        ),
    ]

    SAMPLE_POINTS = [(0.0, 0.0), (0.12, -0.08), (-0.15, 0.1), (0.05, 0.05)]

    def test_gradient_matches_numeric(self):
        for surface in self.CASES:
            for x, y in self.SAMPLE_POINTS:
                gx, gy = surface.gradient(x, y)
                nx, ny = _numeric_gradient(surface, x, y)
                self.assertAlmostEqual(gx, nx, places=6, msg=f"{surface.kind} ({x},{y}) gx")
                self.assertAlmostEqual(gy, ny, places=6, msg=f"{surface.kind} ({x},{y}) gy")

    def test_hessian_matches_numeric(self):
        for surface in self.CASES:
            for x, y in self.SAMPLE_POINTS:
                (dxx, dxy), (_, dyy) = surface.hessian(x, y)
                (nxx, nxy), (_, nyy) = _numeric_hessian(surface, x, y)
                scale = max(1.0, abs(nxx), abs(nyy))
                self.assertAlmostEqual(
                    dxx / scale, nxx / scale, places=4, msg=f"{surface.kind} ({x},{y}) dxx"
                )
                self.assertAlmostEqual(
                    dyy / scale, nyy / scale, places=4, msg=f"{surface.kind} ({x},{y}) dyy"
                )
                self.assertAlmostEqual(
                    dxy / scale, nxy / scale, places=3, msg=f"{surface.kind} ({x},{y}) dxy"
                )

    def test_normal_convention_points_to_camera(self):
        # n ∝ (-dh/dx, -dh/dy, 1),z 分量为正
        for surface in self.CASES:
            for x, y in self.SAMPLE_POINTS:
                n = surface.normal(x, y)
                self.assertGreater(n[2], 0.0, msg=surface.kind)
                self.assertAlmostEqual(vec_norm(n), 1.0, msg=surface.kind)
                gx, gy = surface.gradient(x, y)
                self.assertAlmostEqual(n[0], -gx / math.sqrt(gx * gx + gy * gy + 1.0))
                self.assertAlmostEqual(n[1], -gy / math.sqrt(gx * gx + gy * gy + 1.0))
                self.assertAlmostEqual(
                    n[2], 1.0 / math.sqrt(gx * gx + gy * gy + 1.0)
                )


class SpecificSurfaceTest(unittest.TestCase):
    def test_plane(self):
        plane = surfaces.PlaneSurface()
        self.assertEqual(plane.height(0.3, -0.4), 0.0)
        self.assertEqual(plane.normal(0.1, 0.1), (0.0, 0.0, 1.0))

    def test_tilted_plane_reference_plane_is_itself(self):
        tilted = surfaces.TiltedPlaneSurface(slope_x=0.01, slope_y=-0.02)
        point, normal = tilted.reference_plane
        # 基准平面法线 = 表面法线(恒定)
        self.assertEqual(normal, tilted.normal(0.0, 0.0))
        # 平面上任意表面点都满足基准平面方程
        for x, y in [(0.0, 0.0), (0.2, -0.1), (-0.15, 0.25)]:
            n = normal
            h = tilted.height(x, y)
            dot = n[0] * x + n[1] * y + n[2] * h
            self.assertAlmostEqual(dot, 0.0, places=12)

    def test_cylinder_sign_and_axis(self):
        pos_x = surfaces.CylinderSurface(radius_m=100.0, sign=1.0, axis="x")
        self.assertAlmostEqual(pos_x.height(0.1, 0.5), 0.1**2 / 200.0)
        self.assertAlmostEqual(pos_x.hessian(0.0, 0.0)[0][0], 1.0 / 100.0)
        self.assertEqual(pos_x.hessian(0.0, 0.0)[1][1], 0.0)
        neg_y = surfaces.CylinderSurface(radius_m=100.0, sign=-1.0, axis="y")
        self.assertAlmostEqual(neg_y.height(0.5, 0.2), -(0.2**2) / 200.0)
        self.assertAlmostEqual(neg_y.hessian(0.0, 0.0)[1][1], -1.0 / 100.0)

    def test_sphere_matches_curvature_center_geometry(self):
        sphere = surfaces.SphereSurface(radius_m=250.0, sign=1.0)
        x, y = 0.12, -0.09
        h = sphere.height(x, y)
        # 点到球心 (0, 0, R) 的距离恒为 R
        d2 = x * x + y * y + (h - 250.0) ** 2
        self.assertAlmostEqual(math.sqrt(d2), 250.0, places=9)
        # 法线 = (球心 - 点) 方向
        n = sphere.normal(x, y)
        toward_center = (-x, -y, 250.0 - h)
        self.assertAlmostEqual(vec_angle_between(n, toward_center), 0.0, places=12)

    def test_saddle_opposite_principal_curvatures(self):
        saddle = surfaces.SaddleSurface(coefficient_a=0.001)
        (dxx, _), (_, dyy) = saddle.hessian(0.2, 0.2)
        self.assertAlmostEqual(dxx, 0.002)
        self.assertAlmostEqual(dyy, -0.002)

    def test_ripple_components(self):
        ripple = surfaces.RippleSurface(
            quad_a=0.001, ripple_amp=1e-5, ripple_wavelength=0.05
        )
        # 原点处二次项 + 波纹项都在 Hessian 中
        (dxx, _), _ = ripple.hessian(0.0, 0.0)
        expected = 2.0 * 0.001 - 1e-5 * (2 * math.pi / 0.05) ** 2
        self.assertAlmostEqual(dxx, expected)

    def test_invalid_parameters_raise(self):
        with self.assertRaises(ValueError):
            surfaces.CylinderSurface(radius_m=-1.0)
        with self.assertRaises(ValueError):
            surfaces.CylinderSurface(radius_m=100.0, sign=2.0)
        with self.assertRaises(ValueError):
            surfaces.CylinderSurface(radius_m=100.0, axis="z")
        with self.assertRaises(ValueError):
            surfaces.SphereSurface(radius_m=0.0)
        with self.assertRaises(ValueError):
            surfaces.RippleSurface(quad_a=1.0, ripple_amp=1.0, ripple_wavelength=0.0)
        with self.assertRaises(ValueError):
            surfaces.SphereSurface(radius_m=0.5).height(0.4, 0.4)  # 孔径外


if __name__ == "__main__":
    unittest.main()
