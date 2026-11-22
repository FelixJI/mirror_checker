package org.mirrorchecker.probe

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** YUV 流输出尺寸。 */
data class YuvSize(val widthPx: Int, val heightPx: Int) {
    init {
        require(widthPx > 0 && heightPx > 0) { "尺寸必须为正：${widthPx}x$heightPx" }
    }

    /** 面积（像素数），用于候选流排序。 */
    val area: Long get() = widthPx.toLong() * heightPx
}

/** AE 目标帧率范围（CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES 的单项）。 */
data class FpsRange(val minFps: Int, val maxFps: Int) {
    init {
        require(minFps in 1..maxFps) { "帧率范围非法：[$minFps,$maxFps]" }
    }
}

/**
 * 单个相机的原始能力快照（PR-03：能力报告）。
 *
 * 只保存 Camera2 查询到的实际值（名称化后的枚举字符串），不做任何跨相机推断。
 * 字段与实施方案 §5.1 的清单对应：相机 ID/朝向/硬件级别/可用 request-result 键、
 * YUV 流组合、手动曝光与 AE 锁、AF 与焦距、几何处理、时间戳源、物理阵列。
 * null 一律表示「该设备未暴露此信息」，不得填默认值冒充实测。
 */
data class CameraSnapshot(
    val cameraId: String,
    val facing: String,
    val hardwareLevel: String,
    /** REQUEST_AVAILABLE_CAPABILITIES 的名称化列表（manual_sensor/manual_post_processing/...）。 */
    val capabilities: List<String>,
    val sensorOrientationDeg: Int,
    /** LENS_INFO_TIMESTAMP_SOURCE："REALTIME"/"UNKNOWN"。 */
    val timestampSource: String,
    /** 逻辑多摄的物理子相机 ID（API<28 为空）。 */
    val physicalIds: List<String>,
    val activeArrayWidthPx: Int?,
    val activeArrayHeightPx: Int?,
    val preCorrectionArrayWidthPx: Int?,
    val preCorrectionArrayHeightPx: Int?,
    val pixelArrayWidthPx: Int?,
    val pixelArrayHeightPx: Int?,
    /** SENSOR_INFO_PHYSICAL_SIZE（毫米，Camera2 原生单位）。 */
    val physicalWidthMm: Double?,
    val physicalHeightMm: Double?,
    val exposureTimeRangeNs: LongRange?,
    val sensitivityRangeIso: IntRange?,
    val maxFrameDurationNs: Long?,
    /** CONTROL_AE_AVAILABLE_MODES 名称化：off/on；闪光等变体保留 mode_N 原始名。 */
    val aeModes: List<String>,
    /** CONTROL_AF_AVAILABLE_MODES 名称化：off、auto、macro、continuous 系列等。 */
    val afModes: List<String>,
    /** LENS_INFO_MINIMUM_FOCUS_DISTANCE（屈光度）；0.0=固定焦距无穷远，null=未暴露。 */
    val minFocusDistanceDiopters: Double?,
    val yuvSizes: List<YuvSize>,
    val fpsRanges: List<FpsRange>,
    /** LENS_DISTORTION 键是否暴露（畸变校正可用性影响几何解释）。 */
    val distortionCorrectionAvailable: Boolean,
    val videoStabilizationAvailable: Boolean,
    /** 可用 request/result 键名（android.control.aeLock 等），证明逐相机查询而非机型推断。 */
    val requestKeys: List<String>,
    val resultKeys: List<String>,
    val maxDigitalZoom: Double?,
) {
    init {
        require(cameraId.isNotEmpty()) { "cameraId 不能为空" }
        require(facing in FACING_VALUES) { "facing 只允许 ${FACING_VALUES.sorted()}，实际为 $facing" }
        require(hardwareLevel in HARDWARE_LEVEL_VALUES) {
            "hardwareLevel 只允许 ${HARDWARE_LEVEL_VALUES.sorted()}，实际为 $hardwareLevel"
        }
        require(timestampSource in TIMESTAMP_SOURCES) {
            "timestampSource 只允许 $TIMESTAMP_SOURCES，实际为 $timestampSource"
        }
    }

    /** 是否具备手动传感器能力（能力名来自本相机实测，不从他机继承）。 */
    val hasManualSensor: Boolean get() = "manual_sensor" in capabilities
    val hasManualPostProcessing: Boolean get() = "manual_post_processing" in capabilities

    /** AE 可关闭（手动曝光的前提之一）。 */
    val aeOffAvailable: Boolean get() = "off" in aeModes

    /** AE 锁可用（曝光自动收敛后锁定，是 lockable 档的硬件前提）。 */
    val aeLockAvailable: Boolean get() =
        "on" in aeModes && "android.control.aeLock" in requestKeys

    fun toJson(): JsonObject = buildJsonObject {
        put("camera_id", cameraId)
        put("facing", facing)
        put("hardware_level", hardwareLevel)
        put("capabilities", stringsToJson(capabilities))
        put("sensor_orientation_deg", sensorOrientationDeg)
        put("timestamp_source", timestampSource)
        put("physical_ids", stringsToJson(physicalIds))
        activeArrayWidthPx?.let { put("active_array_width_px", it) }
        activeArrayHeightPx?.let { put("active_array_height_px", it) }
        preCorrectionArrayWidthPx?.let { put("pre_correction_array_width_px", it) }
        preCorrectionArrayHeightPx?.let { put("pre_correction_array_height_px", it) }
        pixelArrayWidthPx?.let { put("pixel_array_width_px", it) }
        pixelArrayHeightPx?.let { put("pixel_array_height_px", it) }
        physicalWidthMm?.let { put("physical_width_mm", it) }
        physicalHeightMm?.let { put("physical_height_mm", it) }
        exposureTimeRangeNs?.let { range ->
            put("exposure_range_ns", JsonArray(listOf(JsonPrimitive(range.first), JsonPrimitive(range.last))))
        }
        sensitivityRangeIso?.let { range ->
            put("sensitivity_range_iso", JsonArray(listOf(JsonPrimitive(range.first), JsonPrimitive(range.last))))
        }
        maxFrameDurationNs?.let { put("max_frame_duration_ns", it) }
        put("ae_modes", stringsToJson(aeModes))
        put("af_modes", stringsToJson(afModes))
        minFocusDistanceDiopters?.let { put("min_focus_distance_diopters", it) }
        put("yuv_sizes", JsonArray(yuvSizes.map { buildJsonObject {
            put("width_px", it.widthPx)
            put("height_px", it.heightPx)
        } }))
        put("fps_ranges", JsonArray(fpsRanges.map { buildJsonObject {
            put("min_fps", it.minFps)
            put("max_fps", it.maxFps)
        } }))
        put("distortion_correction_available", distortionCorrectionAvailable)
        put("video_stabilization_available", videoStabilizationAvailable)
        put("request_keys", stringsToJson(requestKeys))
        put("result_keys", stringsToJson(resultKeys))
        maxDigitalZoom?.let { put("max_digital_zoom", it) }
    }

    companion object {
        val FACING_VALUES = setOf("front", "back", "external")
        val HARDWARE_LEVEL_VALUES = setOf("legacy", "limited", "full", "level_3", "external", "unknown")
        val TIMESTAMP_SOURCES = setOf("REALTIME", "UNKNOWN")
    }
}

/** 一个候选诊断流：尺寸 + 计划帧率及所依据的实测范围。 */
data class StreamCandidate(
    val size: YuvSize,
    val targetFps: Int,
    val fpsRange: FpsRange,
) {
    fun toJson(): JsonObject = buildJsonObject {
        put("width_px", size.widthPx)
        put("height_px", size.heightPx)
        put("target_fps", targetFps)
        put("fps_range_min", fpsRange.minFps)
        put("fps_range_max", fpsRange.maxFps)
    }
}

/**
 * 候选流规划（纯逻辑，供诊断页选择试开目标）。
 *
 * 规则（首版诊断判据，非计量规格）：
 * - 只保留常规宽高比（每边比值的较大者/较小者不超过 2，覆盖 4:3 与 16:9）；
 * - 按面积从大到小排序，同面积按宽度大者优先，保证顺序确定；
 * - 帧率取「能覆盖目标帧率的最小 maxFps 范围」，没有覆盖时取 maxFps 最接近目标的范围。
 */
object StreamPlanner {

    fun candidates(yuvSizes: List<YuvSize>, fpsRanges: List<FpsRange>, targetFps: Int = 30): List<StreamCandidate> {
        require(fpsRanges.isNotEmpty()) { "没有实测帧率范围，无法规划候选流" }
        val ratioOk = yuvSizes.filter { size ->
            val (long, short) = maxOf(size.widthPx, size.heightPx) to minOf(size.widthPx, size.heightPx)
            short > 0 && long.toDouble() / short <= 2.0
        }
        val ordered = ratioOk.sortedWith(
            compareByDescending<YuvSize> { it.area }.thenByDescending { it.widthPx }.thenBy { it.heightPx }
        )
        return ordered.map { size -> StreamCandidate(size, pickFps(fpsRanges, targetFps).first, pickFps(fpsRanges, targetFps).second) }
    }

    /** 选择帧率范围：优先完全覆盖目标；否则 maxFps 与目标差最小。返回 (目标帧率, 范围)。 */
    fun pickFps(fpsRanges: List<FpsRange>, targetFps: Int): Pair<Int, FpsRange> {
        val covering = fpsRanges.filter { it.minFps <= targetFps && targetFps <= it.maxFps }
            .minByOrNull { it.maxFps }
        if (covering != null) return targetFps to covering
        val nearest = fpsRanges.minByOrNull { kotlin.math.abs(it.maxFps - targetFps) }!!
        return nearest.maxFps to nearest
    }
}

/** 单帧试开采集到的实际参数（纳秒值用十进制字符串，与会话契约一致）。 */
data class CapturedFrameTiming(
    val sensorTimestampNs: String,
    val exposureTimeNs: String,
    val sensitivityIso: Int,
    val frameDurationNs: String,
    val aeState: String?,
    val afState: String?,
) {
    init {
        require(sensorTimestampNs.toLongOrNull() != null) { "sensor_timestamp_ns 必须是十进制数字字符串" }
        require(exposureTimeNs.toLongOrNull() != null) { "exposure_time_ns 必须是十进制数字字符串" }
        require(frameDurationNs.toLongOrNull() != null) { "frame_duration_ns 必须是十进制数字字符串" }
    }

    fun toJson(): JsonObject = buildJsonObject {
        put("sensor_timestamp_ns", sensorTimestampNs)
        put("exposure_time_ns", exposureTimeNs)
        put("sensitivity_iso", sensitivityIso)
        put("frame_duration_ns", frameDurationNs)
        aeState?.let { put("ae_state", it) }
        afState?.let { put("af_state", it) }
    }
}

/** 试开时下发的请求模式与目标参数。 */
data class TrialRequest(
    /** manual = AE 关、显式曝光/ISO；ae_lock = AE 开且锁定；auto = 全自动对照。 */
    val mode: String,
    val requestedExposureTimeNs: Long?,
    val requestedSensitivityIso: Int?,
) {
    init {
        require(mode in MODES) { "mode 只允许 $MODES，实际为 $mode" }
    }

    fun toJson(): JsonObject = buildJsonObject {
        put("mode", mode)
        requestedExposureTimeNs?.let { put("requested_exposure_time_ns", it.toString()) }
        requestedSensitivityIso?.let { put("requested_sensitivity_iso", it) }
    }

    companion object {
        val MODES = setOf("manual", "ae_lock", "auto")
    }
}

/** 一次试开 YUV 流的完整结果；失败时保留原因，不伪装成成功。 */
data class TrialResult(
    val cameraId: String,
    val widthPx: Int,
    val heightPx: Int,
    val targetFps: Int,
    val request: TrialRequest,
    val frames: List<CapturedFrameTiming>,
    val error: String? = null,
) {
    fun toJson(): JsonObject = buildJsonObject {
        put("camera_id", cameraId)
        put("width_px", widthPx)
        put("height_px", heightPx)
        put("target_fps", targetFps)
        put("request", request.toJson())
        put("frames", JsonArray(frames.map { it.toJson() }))
        error?.let { put("error", it) }
    }
}

/** JsonArray 辅助：List<String> → JSON 字符串数组。 */
internal fun stringsToJson(values: List<String>): JsonArray =
    buildJsonArray { values.forEach { add(kotlinx.serialization.json.JsonPrimitive(it)) } }
