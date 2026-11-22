"""``mirror_core.optics.fringes`` 的单元测试:上游公式移植与编解码回环。"""

from __future__ import annotations

import math
import unittest

from mirror_core.optics import fringes


class UpstreamFormulaTest(unittest.TestCase):
    """锁定上游固定提交公式在手算采样点上的取值。"""

    def test_default_periods(self):
        # from_num_periods(4) = [4^0 - 0.1, 4, 16, 64]
        self.assertEqual(fringes.default_periods(4), (0.9, 4.0, 16.0, 64.0))
        self.assertEqual(fringes.default_periods(1), (0.9,))
        self.assertEqual(fringes.default_periods(2), (0.9, 4.0))

    def test_fringe_value_reference_points(self):
        period = 4.0
        # s = 0.5 → 幅角 (1-0.5)*4*2π = 4π;cos(4π) = 1 → 强度 1.0
        self.assertAlmostEqual(fringes.fringe_value(0.5, period, 0), 1.0)
        # s = 0.75 → 幅角 (0.25)*4*2π = 2π → 1.0
        self.assertAlmostEqual(fringes.fringe_value(0.75, period, 0), 1.0)
        # s = 0.625 → 幅角 (0.375)*8π = 3π → cos = -1 → 强度 0.0
        self.assertAlmostEqual(fringes.fringe_value(0.625, period, 0), 0.0)
        # 相移 π/2:cos(θ - π/2) = sin θ;s = 0(幅角 8π)→ sin(8π) = 0 → 0.5
        self.assertAlmostEqual(fringes.fringe_value(0.0, period, 1), 0.5)
        # s = 0.4375 → 幅角 (0.5625)*8π = 4.5π;sin(4.5π) = 1 → 强度 1.0
        self.assertAlmostEqual(fringes.fringe_value(0.4375, period, 1), 1.0)
        # 手算:period=0.9, s=1/3, shift=0
        # 幅角 = (2/3)*0.9*2π = 0.6*2π = 1.2π;cos(1.2π) ≈ -0.809016994
        expected = math.cos(1.2 * math.pi) / 2.0 + 0.5
        self.assertAlmostEqual(fringes.fringe_value(1.0 / 3.0, 0.9, 0), expected)

    def test_frame_order_y_before_x(self):
        periods = (0.9, 4.0)
        # 帧总数 = (2+2)*4 = 16;y 块占前 8 帧
        self.assertEqual(fringes.frame_count(periods, periods), 16)
        # 帧 0..7 随 v 变化、与 u 无关
        for idx in range(8):
            a = fringes.frame_value(idx, 0.2, 0.7, periods, periods)
            b = fringes.frame_value(idx, 0.9, 0.7, periods, periods)
            self.assertEqual(a, b, msg=f"帧 {idx} 应属 y 方向")
        # 帧 8..15 随 u 变化、与 v 无关
        for idx in range(8, 16):
            a = fringes.frame_value(idx, 0.2, 0.7, periods, periods)
            b = fringes.frame_value(idx, 0.2, 0.1, periods, periods)
            self.assertEqual(a, b, msg=f"帧 {idx} 应属 x 方向")
        # 帧内容与 encode_intensities 一致
        u, v = 0.3, 0.8
        y_seq = fringes.encode_intensities(v, periods)
        x_seq = fringes.encode_intensities(u, periods)
        for idx in range(8):
            self.assertEqual(
                fringes.frame_value(idx, u, v, periods, periods), y_seq[idx]
            )
        for idx in range(8):
            self.assertEqual(
                fringes.frame_value(idx + 8, u, v, periods, periods), x_seq[idx]
            )


class UpstreamRecordedValuesTest(unittest.TestCase):
    """与上游固定提交实跑输出的对比记录(2026-11-22,人工证据)。

    在独立 venv(numpy 2.5.5)中运行上游 ``Fringes.get_frames``
    (96x64,周期 [0.9,4,16,64])与 ``unwrap_phase``,与本实现逐点
    对比:2016 个帧采样点最大差 2.8e-14;解包最大差 6.0e-10(上游
    内部 float32 转换,非公式差异)。此处固化代表性采样点,CI 无
    numpy 也能锁定两实现一致。复现脚本与完整记录见 docs/upstream.md。
    """

    #: (帧号, 行, 列, 本实现值, 上游值)——上游输出 96x64 图像,
    #: 屏幕分数坐标 u = 列/95, v = 行/63(linspace 端点含)
    RECORDED = [
        (0, 9, 0, 0.5671166329088276, 0.5671166329088276),
        (0, 27, 63, 0.002012853002380466, 0.002012853002380466),
        (3, 54, 28, 0.13860256808630417, 0.13860256808630417),
        (5, 9, 0, 0.7169418695587801, 0.7169418695587801),
        (8, 27, 63, 0.8117449009293676, 0.8117449009293676),
        (16, 32, 7, 0.7509540229240601, 0.7509540229240601),
        (20, 32, 35, 0.006819348298638672, 0.006819348298638672),
        (25, 32, 63, 0.8199842702516582, 0.8199842702516582),
        (31, 32, 7, 0.011506584608197645, 0.011506584608197645),
    ]

    def test_frame_values_match_upstream_recording(self):
        periods = fringes.default_periods(4)
        for frame_idx, row, col, ours, upstream in self.RECORDED:
            u = col / 95
            v = row / 63
            value = fringes.frame_value(frame_idx, u, v, periods, periods)
            self.assertAlmostEqual(
                value, upstream, places=12, msg=f"帧 {frame_idx} ({row},{col})"
            )
            self.assertAlmostEqual(value, ours, places=15)

    def test_unwrap_matches_upstream_recording(self):
        # 上游 unwrap_phase 输出(图案坐标 = 1 - s;上游 float32 精度)
        recorded = [
            (0.03, 0.9700000000644293),
            (0.17, 0.8299999998743072),
            (0.31, 0.6900000001288586),
            (0.5, 0.5),
            (0.62, 0.38000000025771735),
            (0.78, 0.22000000006442932),
            (0.94, 0.06000000060239574),
        ]
        periods = fringes.default_periods(4)
        for s, upstream_unwrapped in recorded:
            unwrapped = fringes.unwrap_phase(
                fringes.encode_intensities(s, periods), periods
            )
            self.assertAlmostEqual(
                unwrapped, upstream_unwrapped, places=8, msg=f"s={s}"
            )
            self.assertAlmostEqual(1.0 - unwrapped, s, places=9)


class RoundTripTest(unittest.TestCase):
    """编码 → 解码回环:精确强度下恢复屏幕坐标。"""

    PERIODS = fringes.default_periods(4)

    def _roundtrip(self, s: float) -> float:
        intensities = fringes.encode_intensities(s, self.PERIODS)
        unwrapped = fringes.unwrap_phase(intensities, self.PERIODS)
        return fringes.screen_fraction_from_unwrapped(unwrapped)

    def test_exact_recovery(self):
        # 避开恰好落在整数边界的采样点
        for s in (0.05, 0.123, 0.25, 0.377, 0.5, 0.628, 0.75, 0.901):
            recovered = self._roundtrip(s)
            self.assertAlmostEqual(
                recovered, s, places=9, msg=f"s={s} 恢复为 {recovered}"
            )

    def test_scaled_and_offset_intensities(self):
        # 解码对线性缩放 + 常数偏置不敏感(模拟显示值域与响应偏置)
        s = 0.42
        raw = fringes.encode_intensities(s, self.PERIODS)
        scaled = [20.0 + 200.0 * value for value in raw]
        unwrapped = fringes.unwrap_phase(scaled, self.PERIODS)
        self.assertAlmostEqual(
            fringes.screen_fraction_from_unwrapped(unwrapped), s, places=9
        )

    def test_quantized_8bit_intensities(self):
        # 8 位量化后的恢复误差应在半个像素级屏幕分数内
        s = 0.42
        raw = fringes.encode_intensities(s, self.PERIODS)
        quantized = [round(value * 255.0) for value in raw]
        unwrapped = fringes.unwrap_phase(quantized, self.PERIODS)
        error = abs(fringes.screen_fraction_from_unwrapped(unwrapped) - s)
        self.assertLess(error, 1e-3)

    def test_single_period_no_wrap(self):
        # 只有最粗一级(0.9)时,解包即 frac((1-s)*0.9)/0.9
        periods = fringes.default_periods(1)
        for s in (0.1, 0.5, 0.83):
            intensities = fringes.encode_intensities(s, periods)
            unwrapped = fringes.unwrap_phase(intensities, periods)
            self.assertAlmostEqual(1.0 - unwrapped, s, places=9)

    def test_input_validation(self):
        with self.assertRaises(ValueError):
            fringes.default_periods(0)
        with self.assertRaises(ValueError):
            fringes.fringe_value(0.5, 4.0, 4)
        with self.assertRaises(ValueError):
            fringes.frame_value(16, 0.1, 0.1, (0.9,), (0.9,))
        with self.assertRaises(ValueError):
            fringes.unwrap_phase([0.1, 0.2, 0.3], (0.9,))


if __name__ == "__main__":
    unittest.main()
