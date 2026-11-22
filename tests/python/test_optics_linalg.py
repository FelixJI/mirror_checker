"""``mirror_core.optics.linalg`` 的单元测试。"""

from __future__ import annotations

import math
import unittest

from mirror_core.contracts import ContractError
from mirror_core.optics import linalg


class VectorOpsTest(unittest.TestCase):
    def test_add_sub_scale(self):
        a = (1.0, 2.0, 3.0)
        b = (-0.5, 0.0, 4.0)
        self.assertEqual(linalg.vec_add(a, b), (0.5, 2.0, 7.0))
        self.assertEqual(linalg.vec_sub(a, b), (1.5, 2.0, -1.0))
        self.assertEqual(linalg.vec_scale(a, 2.0), (2.0, 4.0, 6.0))

    def test_dot_cross(self):
        self.assertAlmostEqual(linalg.vec_dot((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), 0.0)
        self.assertAlmostEqual(
            linalg.vec_dot((1.0, 2.0, 3.0), (4.0, 5.0, 6.0)), 32.0
        )
        self.assertEqual(
            linalg.vec_cross((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), (0.0, 0.0, 1.0)
        )
        # 反交换
        cross_ba = linalg.vec_cross((0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
        self.assertEqual(cross_ba, (0.0, 0.0, -1.0))

    def test_norm_normalize(self):
        self.assertAlmostEqual(linalg.vec_norm((3.0, 4.0, 0.0)), 5.0)
        unit = linalg.vec_normalize((0.0, 0.0, -2.0))
        self.assertEqual(unit, (0.0, 0.0, -1.0))
        with self.assertRaisesRegex(ContractError, "零长度向量"):
            linalg.vec_normalize((0.0, 0.0, 0.0))

    def test_reflect(self):
        # 入射方向斜向平面法线 z,反射后 z 分量反号、xy 保持
        d = linalg.vec_normalize((1.0, -1.0, -1.0))
        n = (0.0, 0.0, 1.0)
        r = linalg.vec_reflect(d, n)
        self.assertAlmostEqual(r[0], d[0])
        self.assertAlmostEqual(r[1], d[1])
        self.assertAlmostEqual(r[2], -d[2])
        self.assertAlmostEqual(linalg.vec_norm(r), 1.0)
        # 垂直入射原路返回
        self.assertEqual(linalg.vec_reflect((0.0, 0.0, -1.0), n), (0.0, 0.0, 1.0))

    def test_angle_between(self):
        self.assertAlmostEqual(
            linalg.vec_angle_between((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), math.pi / 2
        )
        self.assertAlmostEqual(
            linalg.vec_angle_between((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)), math.pi
        )
        # atan2 形式在近平行时仍稳定
        tiny = 1e-12
        self.assertAlmostEqual(
            linalg.vec_angle_between((1.0, tiny, 0.0), (1.0, 0.0, 0.0)),
            tiny,
            places=15,
        )
        with self.assertRaisesRegex(ContractError, "零向量"):
            linalg.vec_angle_between((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))


class MatrixAndRayTest(unittest.TestCase):
    def test_mat_vec(self):
        m = ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))  # 绕 z 转 90°
        self.assertEqual(linalg.mat_vec(m, (1.0, 0.0, 0.0)), (0.0, 1.0, 0.0))

    def test_point_on_ray(self):
        self.assertEqual(
            linalg.point_on_ray((1.0, 1.0, 1.0), (0.0, 0.0, -1.0), 2.5),
            (1.0, 1.0, -1.5),
        )

    def test_line_plane_parameter(self):
        # 相机在 z=2,沿 -z 看向 z=0 平面
        t = linalg.line_plane_parameter(
            (0.0, 0.0, 2.0), (0.0, 0.0, -1.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)
        )
        self.assertAlmostEqual(t, 2.0)
        # 斜射线
        t2 = linalg.line_plane_parameter(
            (0.0, 0.0, 1.0), (1.0, 0.0, -1.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
        )
        self.assertAlmostEqual(t2, 1.0)
        with self.assertRaisesRegex(ContractError, "平行"):
            linalg.line_plane_parameter(
                (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)
            )


if __name__ == "__main__":
    unittest.main()
