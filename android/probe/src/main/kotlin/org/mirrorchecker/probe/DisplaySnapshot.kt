package org.mirrorchecker.probe

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.mirrorchecker.contracts.JsonUtil

/** Surface 像素坐标中的矩形（左上角 + 宽高）。 */
data class RectPx(val leftPx: Int, val topPx: Int, val widthPx: Int, val heightPx: Int) {
    init {
        require(widthPx >= 0 && heightPx >= 0) { "矩形宽高必须非负：${widthPx}x$heightPx" }
    }

    fun toJson(): JsonObject = buildJsonObject {
        put("left_px", leftPx)
        put("top_px", topPx)
        put("width_px", widthPx)
        put("height_px", heightPx)
    }
}

/**
 * 一次采集/渲染时刻的显示与 Surface 状态快照（PR-03：方向和 Surface 记录）。
 *
 * 记录规则（实施方案 §3.3）：
 * - 不把 ROTATION_0 固定解释为竖屏，自然方向单独记录；
 * - 旋转、分屏、窗口尺寸或有效 Surface（遮挡区）变化时当前组必须中止，
 *   不得静默沿用旧配置——用 [requireSurfaceUnchanged] 强制；
 * - 亮度和刷新率属于设备配置的完整指纹，但不属于几何失效条件：
 *   亮度由采集配方固定（PR-04），几何字段不变时亮度的变化不触发中止。
 */
data class DisplaySnapshot(
    val surfaceWidthPx: Int,
    val surfaceHeightPx: Int,
    /** Surface.ROTATION_*：0/90/180/270。 */
    val rotationDeg: Int,
    /** 自然方向：多数平板为 landscape，多数手机为 portrait。 */
    val naturalOrientation: String,
    val refreshRateHz: Double,
    /** 亮度模式："manual"/"automatic"；null 表示未知（读取失败不伪造）。 */
    val brightnessMode: String? = null,
    /** 当前亮度 0..1；null 表示未知。 */
    val brightnessValue: Double? = null,
    /** 有效发光区内的已知遮挡（前摄开孔、系统栏），Surface 像素坐标。 */
    val occlusionsPx: List<RectPx> = emptyList(),
) {
    init {
        require(surfaceWidthPx > 0 && surfaceHeightPx > 0) { "Surface 尺寸必须为正" }
        require(rotationDeg in intArrayOf(0, 90, 180, 270)) { "rotationDeg 必须是 0/90/180/270" }
        require(naturalOrientation == "landscape" || naturalOrientation == "portrait") {
            "naturalOrientation 只允许 landscape/portrait，实际为 $naturalOrientation"
        }
    }

    /** 几何指纹：参与「旋转/窗口/Surface 变化必须中止」判断的全部字段。 */
    fun surfaceFingerprintJson(): JsonObject = buildJsonObject {
        put("surface_width_px", surfaceWidthPx)
        put("surface_height_px", surfaceHeightPx)
        put("rotation_deg", rotationDeg)
        put("natural_orientation", naturalOrientation)
        put("occlusions", JsonArray(occlusionsPx.map { it.toJson() }))
    }

    fun surfaceFingerprint(): String = JsonUtil.canonicalJson(surfaceFingerprintJson())

    /** 完整配置指纹：几何 + 亮度/刷新率，用于绑定 device_config。 */
    fun fullFingerprint(): String = JsonUtil.canonicalJson(
        buildJsonObject {
            surfaceFingerprintJson().forEach { (key, value) -> put(key, value) }
            put("refresh_rate_hz", refreshRateHz)
            brightnessMode?.let { put("brightness_mode", it) }
            brightnessValue?.let { put("brightness_value", it) }
        }
    )

    /**
     * 断言当前快照与采集开始时的几何状态一致；不一致即抛 [ProbeException]
     * （旋转、分屏、窗口尺寸或有效 Surface 变化，当前组必须中止）。
     */
    fun requireSurfaceUnchanged(current: DisplaySnapshot, where: String) {
        val expected = surfaceFingerprint()
        val actual = current.surfaceFingerprint()
        if (expected != actual) {
            throw ProbeException(
                "$where: 显示 Surface 状态在采集中发生变化，旧配置失效，当前组必须中止：" +
                    "开始时 $expected，当前 $actual"
            )
        }
    }

    fun toJson(): JsonObject = buildJsonObject {
        put("surface_width_px", surfaceWidthPx)
        put("surface_height_px", surfaceHeightPx)
        put("rotation_deg", rotationDeg)
        put("natural_orientation", naturalOrientation)
        put("refresh_rate_hz", refreshRateHz)
        brightnessMode?.let { put("brightness_mode", it) }
        brightnessValue?.let { put("brightness_value", it) }
        put("occlusions", JsonArray(occlusionsPx.map { it.toJson() }))
        put("surface_fingerprint_sha256", JsonUtil.canonicalSha256(surfaceFingerprintJson()))
    }
}
