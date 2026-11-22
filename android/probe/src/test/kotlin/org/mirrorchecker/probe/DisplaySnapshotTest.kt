package org.mirrorchecker.probe

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * 显示/Surface 状态快照的失效规则（PR-03 验收：旋转/窗口变化不会静默沿用旧配置）。
 */
class DisplaySnapshotTest {

    private fun base() = DisplaySnapshot(
        surfaceWidthPx = 1200,
        surfaceHeightPx = 800,
        rotationDeg = 0,
        naturalOrientation = "landscape",
        refreshRateHz = 60.0,
        brightnessMode = "manual",
        brightnessValue = 0.8,
        occlusionsPx = listOf(RectPx(1140, 0, 60, 20)),
    )

    @Test
    fun `几何指纹对相同状态确定，对几何变化敏感`() {
        assertEquals(base().surfaceFingerprint(), base().surfaceFingerprint())
        assertNotEquals(base().surfaceFingerprint(), base().copy(rotationDeg = 90).surfaceFingerprint())
        assertNotEquals(base().surfaceFingerprint(), base().copy(surfaceWidthPx = 1180).surfaceFingerprint())
        assertNotEquals(base().surfaceFingerprint(), base().copy(occlusionsPx = emptyList()).surfaceFingerprint())
        // 自然方向是记录字段，不同自然方向的相同旋转不能共享指纹
        assertNotEquals(base().surfaceFingerprint(), base().copy(naturalOrientation = "portrait").surfaceFingerprint())
    }

    @Test
    fun `几何不变时亮度或刷新率变化不触发中止，但完整指纹变化`() {
        val start = base()
        val brightnessChanged = start.copy(brightnessValue = 0.2, brightnessMode = "automatic")
        start.requireSurfaceUnchanged(brightnessChanged, "trial")
        assertNotEquals(start.fullFingerprint(), brightnessChanged.fullFingerprint())

        val refreshChanged = start.copy(refreshRateHz = 120.0)
        start.requireSurfaceUnchanged(refreshChanged, "trial")
    }

    @Test
    fun `旋转或窗口变化必须中止并报告差异`() {
        val start = base()
        try {
            start.requireSurfaceUnchanged(start.copy(rotationDeg = 270), "patch P1")
            fail("旋转变化必须抛出 ProbeException")
        } catch (e: ProbeException) {
            assertTrue(e.message!!.contains("必须中止"))
            assertTrue(e.message!!.contains("P1"))
        }
        try {
            start.requireSurfaceUnchanged(start.copy(surfaceHeightPx = 810), "trial")
            fail("窗口尺寸变化必须抛出 ProbeException")
        } catch (expected: ProbeException) {
        }
        // 新增遮挡（分屏栏/开孔）同样失效
        try {
            start.requireSurfaceUnchanged(
                start.copy(occlusionsPx = start.occlusionsPx + RectPx(0, 0, 1200, 40)),
                "trial",
            )
            fail("有效 Surface 变化必须抛出 ProbeException")
        } catch (expected: ProbeException) {
        }
        // 相同状态通过
        start.requireSurfaceUnchanged(base(), "trial")
    }

    @Test
    fun `JSON 记录方向与指纹，不含把 ROTATION_0 解释为竖屏的假设`() {
        val json = base().toJson()
        assertEquals("0", json["rotation_deg"].toString())
        assertEquals("\"landscape\"", json["natural_orientation"].toString())
        assertTrue(json["surface_fingerprint_sha256"].toString().matches(Regex(""""[0-9a-f]{64}"""")))
    }

    @Test
    fun `非法旋转角或自然方向被拒绝`() {
        try {
            base().copy(rotationDeg = 45)
            fail()
        } catch (expected: IllegalArgumentException) {
        }
        try {
            base().copy(naturalOrientation = "square")
            fail()
        } catch (expected: IllegalArgumentException) {
        }
    }
}
