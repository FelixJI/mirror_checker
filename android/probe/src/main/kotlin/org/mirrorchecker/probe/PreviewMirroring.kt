package org.mirrorchecker.probe

import kotlinx.serialization.json.put

/**
 * 镜像预览与计算坐标的分离（PR-03 验收项）。
 *
 * 规则（实施方案 §2.1 调试行：「图案采集时不显示悬浮预览」及坐标口径）：
 * - 前摄预览默认水平镜像只是显示习惯；保存的帧与一切计算坐标永远使用
 *   传感器图像系（未镜像），`frameMirrored` 恒为 false；
 * - 把预览坐标换算到图像坐标必须显式经过本对象，禁止在渲染层「顺手」翻转
 *   后不留记录；预览是否镜像作为设备配置的一部分随报告落盘。
 */
data class PreviewMirroring(
    /** 预览流是否对用户做了水平镜像显示（多数前摄默认 true）。 */
    val previewMirrored: Boolean,
) {
    /** 计算用帧的镜像状态：契约固定为不镜像，任何流水线不得改动。 */
    val frameMirrored: Boolean get() = false

    /** 预览坐标 → 传感器图像坐标（仅水平镜像一种变换；宽度为预览像素宽）。 */
    fun previewXToImageX(previewX: Int, previewWidthPx: Int): Int {
        require(previewWidthPx > 0) { "previewWidthPx 必须为正" }
        return if (previewMirrored) previewWidthPx - 1 - previewX else previewX
    }

    fun toJson(): kotlinx.serialization.json.JsonObject =
        kotlinx.serialization.json.buildJsonObject {
            put("preview_mirrored", previewMirrored)
            put("frame_mirrored", frameMirrored)
        }
}
