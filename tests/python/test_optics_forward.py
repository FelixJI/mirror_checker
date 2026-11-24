"""``mirror_core.optics.forward`` 的单元测试:正向模型自洽性。"""

from __future__ import annotations

import math
import unittest

from mirror_core.optics import forward
from mirror_core.optics.linalg import (
    vec_dot,
    vec_norm,
    vec_sub,
)
from mirror_core.optics.surfaces import (
    CylinderSurface,
    PlaneSurface,
    SphereSurface,
    TiltedPlaneSurface,
)


def _default_scene(surface):
    """测试用小网格场景:相机 z=0.12、屏幕 z=0.15(近距,屏能接住反射视锥)。"""
    camera = forward.Camera(
        center_m=(0.0, 0.0, 0.12),
        image_width_px=24,
        image_height_px=16,
        focal_length_px=32.0,
    )
    screen = forward.Screen(
        center_m=(0.0, 0.0, 0.15), width_m=0.3, height_m=0.2
    )
    return forward.trace_scene(surface, camera, screen)


class CameraScreenTest(unittest.TestCase):
    def test_pixel_ray_geometry(self):
        camera = forward.Camera(
            center_m=(0.0, 0.0, 1.0),
            image_width_px=4,
            image_height_px=4,
            focal_length_px=8.0,
        )
        self.assertGreater(camera.pixel_ray(1, 0)[1], 0.0)
        self.assertLess(camera.pixel_ray(1, 3)[1], 0.0)
        # 偶数网格没有正好居中的像素;检查对称性:像素 (0,1) 与 (3,1) 的 x 分量相反
        left = camera.pixel_ray(0, 1)
        right = camera.pixel_ray(3, 1)
        self.assertAlmostEqual(left[0] + right[0], 0.0, places=15)
        # 方向单位化且朝 -z
        for ray in (left, right):
            self.assertAlmostEqual(vec_norm(ray), 1.0)
            self.assertLess(ray[2], 0.0)

    def test_uv_metric_mapping(self):
        screen = forward.Screen(center_m=(0.0, 0.0, 1.2), width_m=0.3, height_m=0.2)
        # 上游 DisplayShape 矩形模型:xm=(ux-0.5)*W, ym=(uy-0.5)*H
        point = screen.point_from_uv(0.25, 0.75)
        self.assertAlmostEqual(point[0], -0.075)
        self.assertAlmostEqual(point[1], 0.05)
        self.assertAlmostEqual(point[2], 1.2)
        u, v = screen.uv_from_point((0.03, -0.01, 1.2))
        self.assertAlmostEqual(u, 0.6)
        self.assertAlmostEqual(v, 0.45)
        with self.assertRaises(ValueError):
            screen.point_from_uv(1.2, 0.5)

    def test_invalid_construction(self):
        with self.assertRaises(ValueError):
            forward.Camera(
                center_m=(0.0, 0.0, -1.0),
                image_width_px=4,
                image_height_px=4,
                focal_length_px=8.0,
            )
        with self.assertRaises(ValueError):
            forward.Camera(
                center_m=(0.0, 0.0, 1.0),
                image_width_px=0,
                image_height_px=4,
                focal_length_px=8.0,
            )
        with self.assertRaises(ValueError):
            forward.Screen(center_m=(0.0, 0.0, 1.2), width_m=-0.1, height_m=0.2)
        with self.assertRaises(ValueError):
            forward.Camera(
                center_m=(0.0, 0.0, 1.0),
                image_width_px=4,
                image_height_px=4,
                focal_length_px=8.0,
            ).pixel_ray(4, 0)


class TraceConsistencyTest(unittest.TestCase):
    """各表面:交点在表面上、反射几何成立、编码与屏幕坐标一致。"""

    SURFACES = [
        PlaneSurface(),
        TiltedPlaneSurface(slope_x=0.004, slope_y=-0.003),
        CylinderSurface(radius_m=200.0, sign=1.0, axis="x"),
        SphereSurface(radius_m=300.0, sign=-1.0),
    ]

    def test_intersection_on_surface(self):
        for surface in self.SURFACES:
            result = _default_scene(surface)
            for obs in result.observations:
                h = surface.height(*obs.intersection_m[:2])
                self.assertAlmostEqual(
                    obs.intersection_m[2],
                    h,
                    delta=1e-9,
                    msg=f"{surface.kind} 交点应落在表面上",
                )

    def test_reflection_geometry(self):
        # 反射定律:入射角 = 反射角(关于法线对称),且屏幕点在反射线上
        for surface in self.SURFACES:
            result = _default_scene(surface)
            camera = result.camera
            for obs in result.observations:
                n = obs.normal_m
                d = obs.ray_direction
                # 法线平分入射反方向与出射方向
                screen_point = result.screen.point_from_uv(*obs.screen_uv)
                outgoing = vec_sub(screen_point, obs.intersection_m)
                outgoing = tuple(c / vec_norm(outgoing) for c in outgoing)
                incoming_reversed = tuple(-c for c in d)
                # n ≈ normalize(incoming_reversed + outgoing)
                bisector = tuple(a + b for a, b in zip(incoming_reversed, outgoing))
                bisector = tuple(c / vec_norm(bisector) for c in bisector)
                dot = vec_dot(n, bisector)
                self.assertAlmostEqual(dot, 1.0, places=9, msg=surface.kind)
                # 切向分量消失:d - (d·n)n 与 outgoing - (outgoing·n)n 同向
                self.assertAlmostEqual(
                    vec_dot(d, n), -vec_dot(outgoing, n), places=12
                )

    def test_screen_uv_consistent_with_intensities(self):
        from mirror_core.optics import fringes

        for surface in self.SURFACES:
            result = _default_scene(surface)
            for obs in result.observations:
                _, v = obs.screen_uv
                # v 帧强度由 v 决定
                expected_y = fringes.encode_intensities(v, result.periods_y)
                self.assertEqual(
                    [round(x, 12) for x in obs.y_intensities],
                    [round(x, 12) for x in expected_y],
                )
                unwrapped_y = fringes.unwrap_phase(
                    list(obs.y_intensities), result.periods_y
                )
                self.assertAlmostEqual(
                    1.0 - unwrapped_y, v, places=9, msg=surface.kind
                )

    def test_plane_screen_mapping_analytic(self):
        # 平面镜:屏幕点横向偏移 = (相机距离 + 屏距) * tan(视线角)
        # 相机 z=0.12、屏幕 z=0.15 → 放大系数 0.27;与像素中心视线一一对应
        result = _default_scene(PlaneSurface())
        camera = result.camera
        screen = result.screen
        for obs in result.observations:
            column, row = obs.pixel
            u_i = column + 0.5 - camera.image_width_px / 2.0
            v_j = row + 0.5 - camera.image_height_px / 2.0
            expected_u = 0.5 + 0.27 * u_i / (camera.focal_length_px * screen.width_m)
            expected_v = 0.5 - 0.27 * v_j / (camera.focal_length_px * screen.height_m)
            self.assertAlmostEqual(
                obs.screen_uv[0], expected_u, places=9, msg=f"像素 {obs.pixel} u"
            )
            self.assertAlmostEqual(
                obs.screen_uv[1], expected_v, places=9, msg=f"像素 {obs.pixel} v"
            )
        # 法线恒为 (0,0,1)
        for obs in result.observations:
            self.assertAlmostEqual(obs.normal_m[0], 0.0, places=15)
            self.assertAlmostEqual(obs.normal_m[1], 0.0, places=15)

    def test_curved_surface_deflects_screen_point(self):
        # 柱面使屏幕对应偏离平面情形(曲率有物理效应)
        plane = _default_scene(PlaneSurface())
        curved = _default_scene(CylinderSurface(radius_m=200.0, sign=1.0, axis="x"))
        by_pixel_plane = {obs.pixel: obs.screen_uv for obs in plane.observations}
        max_shift = 0.0
        for obs in curved.observations:
            if obs.pixel in by_pixel_plane:
                du = obs.screen_uv[0] - by_pixel_plane[obs.pixel][0]
                max_shift = max(max_shift, abs(du))
        self.assertGreater(max_shift, 1e-4, "柱面应使屏幕对应发生可测偏移")
        self.assertLess(max_shift, 0.5, "偏移应在屏幕量级内(未越界失真)")

    def test_row_major_order_and_uniqueness(self):
        result = _default_scene(PlaneSurface())
        pixels = [obs.pixel for obs in result.observations]
        # 像素为 (列, 行);行主序 = 先按行再按列
        self.assertEqual(
            pixels, sorted(pixels, key=lambda p: (p[1], p[0])), "观测应按行主序"
        )
        self.assertEqual(len(pixels), len(set(pixels)), "像素不重复")
        # 大部分像素活动(平面镜正视)
        self.assertGreater(len(pixels), 24 * 16 * 0.8)

    def test_no_active_pixels_raises(self):
        camera = forward.Camera(
            center_m=(0.0, 0.0, 1.0),
            image_width_px=4,
            image_height_px=4,
            focal_length_px=8.0,
        )
        # 屏幕极小,几乎无反射点落入
        tiny = forward.Screen(center_m=(0.0, 0.0, 1.05), width_m=1e-6, height_m=1e-6)
        with self.assertRaisesRegex(ValueError, "没有活动像素"):
            forward.trace_scene(PlaneSurface(), camera, tiny)


if __name__ == "__main__":
    unittest.main()
