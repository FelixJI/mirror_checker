package org.mirrorchecker.probe

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.roundToInt

/**
 * 诊断图案定义与像素级渲染（PR-03：像素确定的全屏图案）。
 *
 * 图案定义在「当前显示 Surface 的像素坐标」中：原点在左上角，
 * x 向右、y 向下，与渲染缓冲区的行主序字节一一对应。
 * [renderRowMajor] 是渲染的唯一真值来源：应用端不得缩放、旋转、滤波
 * 或按 dpi 换算，只能把返回的字节按行填入 Surface（验收：渲染坐标与参考图一致）。
 * 旋转或窗口变化会改变 Surface 尺寸，必须用新的尺寸重新渲染，
 * 并按 [DisplaySnapshot] 的失效规则中止旧配置（实施方案 §3.3）。
 */
enum class PatternKind(val wireName: String) {
    BLACK("black"),
    WHITE("white"),
    GRAY_STEPS("gray_steps"),
    FRINGE("fringe"),
}

data class DiagnosticPattern(
    val patternId: String,
    val kind: PatternKind,
    /**
     * FRINGE 条纹法线方向（度）：0 = 亮度沿 +x 变化（竖直条纹），
     * 90 = 亮度沿 +y 变化（水平条纹）。只允许 0/90，其他角度报错。
     */
    val directionDeg: Int = 0,
    /** FRINGE：沿变化方向整个范围内的完整周期数（正整数）。 */
    val cycles: Int = 4,
    /** FRINGE：相位偏移（弧度），用于诊断显示—曝光混帧时可作边缘编码的相位基准。 */
    val phaseShiftRad: Double = 0.0,
    /** GRAY_STEPS：灰阶带数量（>=2）。 */
    val steps: Int = 8,
) {
    init {
        require(patternId.isNotEmpty()) { "patternId 不能为空" }
        when (kind) {
            PatternKind.FRINGE -> {
                require(directionDeg == 0 || directionDeg == 90) {
                    "directionDeg 只允许 0/90，实际为 $directionDeg"
                }
                require(cycles >= 1) { "cycles 必须是正整数，实际为 $cycles" }
            }
            PatternKind.GRAY_STEPS -> require(steps >= 2) { "steps 必须 >=2，实际为 $steps" }
            else -> Unit
        }
    }

    fun toJson(): JsonObject = buildJsonObject {
        put("pattern_id", patternId)
        put("kind", kind.wireName)
        when (kind) {
            PatternKind.FRINGE -> {
                put("direction_deg", directionDeg)
                put("cycles", cycles)
                put("phase_shift_rad", phaseShiftRad)
            }
            PatternKind.GRAY_STEPS -> put("steps", steps)
            else -> Unit
        }
    }

    companion object {
        /** PR-03 内置诊断配方：黑白、灰阶与两个方向的低频条纹（§5.1）。 */
        fun builtIn(): List<DiagnosticPattern> = listOf(
            DiagnosticPattern("diag_black", PatternKind.BLACK),
            DiagnosticPattern("diag_white", PatternKind.WHITE),
            DiagnosticPattern("diag_gray8", PatternKind.GRAY_STEPS, steps = 8),
            DiagnosticPattern("diag_fringe_h8", PatternKind.FRINGE, directionDeg = 0, cycles = 8),
            DiagnosticPattern("diag_fringe_v8", PatternKind.FRINGE, directionDeg = 90, cycles = 8),
        )
    }
}

object PatternRenderer {

    /**
     * 计算图案在 (x, y) 处的 8 位亮度（0..255）。
     * 纯函数：同一图案与尺寸永远得到同一字节，便于与应用渲染结果逐字节比对。
     */
    fun luminanceAt(pattern: DiagnosticPattern, x: Int, y: Int, width: Int, height: Int): Int {
        require(width > 0 && height > 0) { "尺寸必须为正：${width}x$height" }
        require(x in 0 until width && y in 0 until height) { "像素坐标越界：($x,$y) 不在 ${width}x$height 内" }
        return when (pattern.kind) {
            PatternKind.BLACK -> 0
            PatternKind.WHITE -> 255
            PatternKind.GRAY_STEPS -> {
                val band = (y.toLong() * pattern.steps / height).toInt().coerceAtMost(pattern.steps - 1)
                (255.0 * band / (pattern.steps - 1)).roundToInt()
            }
            PatternKind.FRINGE -> {
                val alongX = pattern.directionDeg == 0
                val u = if (alongX) x else y
                val extent = if (alongX) width else height
                val phase = 2.0 * PI * pattern.cycles * u / extent + pattern.phaseShiftRad
                (127.5 + 127.5 * cos(phase)).roundToInt().coerceIn(0, 255)
            }
        }
    }

    /**
     * 渲染为行主序 8 位亮度数组（长度 width*height，行 y 占 [y*width, (y+1)*width)）。
     * 应用端按 1:1 像素写入 Surface；任何重采样都会破坏与该参考输出的一致性。
     */
    fun renderRowMajor(pattern: DiagnosticPattern, width: Int, height: Int): ByteArray {
        require(width > 0 && height > 0) { "尺寸必须为正：${width}x$height" }
        val out = ByteArray(width * height)
        var index = 0
        for (y in 0 until height) {
            for (x in 0 until width) {
                out[index++] = luminanceAt(pattern, x, y, width, height).toByte()
            }
        }
        return out
    }
}
