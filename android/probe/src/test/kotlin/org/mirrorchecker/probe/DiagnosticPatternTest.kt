package org.mirrorchecker.probe

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.roundToInt

/**
 * 诊断图案的解析交叉验证（PR-03 验收：渲染坐标与参考图一致）。
 * 参考值用独立的三角函数路径计算，不复用被测实现。
 */
class DiagnosticPatternTest {

    /** 独立参考：与实现相同定义、但独立编写的条纹亮度公式。 */
    private fun refFringe(cycles: Int, u: Int, extent: Int, phase: Double): Int {
        val angle = (2.0 * PI * cycles / extent) * u + phase
        val v = 127.5 + 127.5 * cos(angle)
        return v.roundToInt().coerceIn(0, 255)
    }

    @Test
    fun `黑白图案是确定的全 0 或全 255`() {
        val black = PatternRenderer.renderRowMajor(DiagnosticPattern("b", PatternKind.BLACK), 7, 5)
        assertEquals(7 * 5, black.size)
        assertTrue(black.all { it == 0.toByte() })
        val white = PatternRenderer.renderRowMajor(DiagnosticPattern("w", PatternKind.WHITE), 7, 5)
        assertTrue(white.all { it == 255.toByte() })
    }

    @Test
    fun `灰阶带按行分布且端点为 0 与 255`() {
        val pattern = DiagnosticPattern("g2", PatternKind.GRAY_STEPS, steps = 2)
        val bytes = PatternRenderer.renderRowMajor(pattern, 4, 4)
        // height=4, steps=2 → 前两行 band=0（0），后两行 band=1（255）
        assertEquals(0, bytes[0].toInt() and 0xFF)
        assertEquals(0, bytes[4 + 3].toInt() and 0xFF)
        assertEquals(255, bytes[2 * 4].toInt() and 0xFF)
        assertEquals(255, bytes[3 * 4 + 1].toInt() and 0xFF)

        val eight = DiagnosticPattern("g8", PatternKind.GRAY_STEPS, steps = 8)
        val bytes8 = PatternRenderer.renderRowMajor(eight, 2, 16)
        assertEquals(0, PatternRenderer.luminanceAt(eight, 0, 0, 2, 16))
        assertEquals(255, PatternRenderer.luminanceAt(eight, 1, 15, 2, 16))
        // y=2 → band=1 → round(255/7)=36
        assertEquals((255.0 / 7).roundToInt(), PatternRenderer.luminanceAt(eight, 0, 2, 2, 16))
    }

    @Test
    fun `条纹与独立解析参考逐像素一致`() {
        val pattern = DiagnosticPattern("f", PatternKind.FRINGE, directionDeg = 0, cycles = 3, phaseShiftRad = 0.7)
        val w = 41
        val h = 13
        val bytes = PatternRenderer.renderRowMajor(pattern, w, h)
        for (y in 0 until h) {
            for (x in 0 until w) {
                val expected = refFringe(3, x, w, 0.7)
                assertEquals("($x,$y)", expected, bytes[y * w + x].toInt() and 0xFF)
            }
        }
    }

    @Test
    fun `条纹方向 0 与 90 互为转置`() {
        val horizontal = DiagnosticPattern("fh", PatternKind.FRINGE, directionDeg = 0, cycles = 2)
        val vertical = DiagnosticPattern("fv", PatternKind.FRINGE, directionDeg = 90, cycles = 2)
        val w = 9
        val h = 9
        val bytesH = PatternRenderer.renderRowMajor(horizontal, w, h)
        val bytesV = PatternRenderer.renderRowMajor(vertical, w, h)
        for (y in 0 until h) {
            for (x in 0 until w) {
                assertEquals("转置关系 ($x,$y)", bytesH[y * w + x], bytesV[x * w + y])
            }
        }
    }

    @Test
    fun `单周期条纹的四分之一周期采样符合余弦预期`() {
        val pattern = DiagnosticPattern("f1", PatternKind.FRINGE, directionDeg = 0, cycles = 1)
        val w = 8
        assertEquals(255, PatternRenderer.luminanceAt(pattern, 0, 0, w, 1))
        assertEquals(0, PatternRenderer.luminanceAt(pattern, 4, 0, w, 1))
        // u=2/6 处 cos≈0，值恰在 127.5：舍入方向取决于浮点余项，127/128 都符合公式
        assertTrue(listOf(127, 128).contains(PatternRenderer.luminanceAt(pattern, 2, 0, w, 1)))
        assertTrue(listOf(127, 128).contains(PatternRenderer.luminanceAt(pattern, 6, 0, w, 1)))
    }

    @Test
    fun `渲染确定且行主序排列`() {
        val pattern = DiagnosticPattern("f4", PatternKind.FRINGE, directionDeg = 90, cycles = 4, phaseShiftRad = 1.0)
        val first = PatternRenderer.renderRowMajor(pattern, 24, 10)
        val second = PatternRenderer.renderRowMajor(pattern, 24, 10)
        assertArrayEquals(first, second)
        // 行主序：renderRowMajor[i] == luminanceAt(x=i%w, y=i/w)
        for (i in first.indices) {
            assertEquals(
                first[i],
                PatternRenderer.luminanceAt(pattern, i % 24, i / 24, 24, 10).toByte()
            )
        }
    }

    @Test
    fun `非法图案定义被拒绝`() {
        try {
            DiagnosticPattern("f", PatternKind.FRINGE, directionDeg = 45)
            fail("45° 方向应被拒绝")
        } catch (expected: IllegalArgumentException) {
        }
        try {
            DiagnosticPattern("g", PatternKind.GRAY_STEPS, steps = 1)
            fail("steps=1 应被拒绝")
        } catch (expected: IllegalArgumentException) {
        }
    }

    @Test
    fun `JSON 字段与内置诊断配方`() {
        val json = DiagnosticPattern("fx", PatternKind.FRINGE, directionDeg = 90, cycles = 5, phaseShiftRad = 0.25).toJson()
        assertEquals("fringe", json["kind"]!!.toString().trim('"'))
        assertEquals("90", json["direction_deg"]!!.toString())
        val builtIn = DiagnosticPattern.builtIn()
        assertEquals(listOf("diag_black", "diag_white", "diag_gray8", "diag_fringe_h8", "diag_fringe_v8"), builtIn.map { it.patternId })
        assertTrue(builtIn.any { it.kind == PatternKind.FRINGE && it.directionDeg == 0 })
        assertTrue(builtIn.any { it.kind == PatternKind.FRINGE && it.directionDeg == 90 })
    }
}
