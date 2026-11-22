package org.mirrorchecker.app

import android.graphics.ImageFormat
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CameraMetadata
import android.os.Build
import android.util.Range
import android.util.Size
import org.mirrorchecker.probe.CameraSnapshot
import org.mirrorchecker.probe.FpsRange
import org.mirrorchecker.probe.YuvSize

/**
 * Camera2 实测值 → 探测模块快照的映射。
 *
 * 只做逐相机查询与名称转换，不添加任何推断：null 保留为 null
 * （实施方案 §5.1：不能从后摄或机型宣传推断前摄）。
 * 未知枚举值以原始数值名（如 mode_5、capability_19）保留，不丢弃。
 */
object AndroidCameraMapper {

    fun enumerate(cameraManager: CameraManager): List<CameraSnapshot> =
        cameraManager.cameraIdList.orEmpty().map { id -> toSnapshot(id, cameraManager.getCameraCharacteristics(id)) }

    fun toSnapshot(cameraId: String, ch: CameraCharacteristics): CameraSnapshot {
        val map = ch.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
        val yuvOutputSizes: Array<Size>? = map?.getOutputSizes(ImageFormat.YUV_420_888)
        val yuvSizes: List<YuvSize> = yuvOutputSizes.orEmpty()
            .map { YuvSize(it.width, it.height) }
            .sortedWith(compareByDescending<YuvSize> { it.area }.thenByDescending { it.widthPx })

        val exposureRange: Range<Long>? = ch.get(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE)
        val sensitivityRange: Range<Int>? = ch.get(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE)
        val fpsOutputRanges: Array<Range<Int>>? = ch.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES)
        val fpsRanges: List<FpsRange> = fpsOutputRanges.orEmpty()
            .map { FpsRange(it.lower, it.upper) }
            .sortedWith(compareBy<FpsRange> { it.minFps }.thenBy { it.maxFps })

        val activeArray = ch.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE)
        val preCorrection = ch.get(CameraCharacteristics.SENSOR_INFO_PRE_CORRECTION_ACTIVE_ARRAY_SIZE)
        val pixelArray: Size? = ch.get(CameraCharacteristics.SENSOR_INFO_PIXEL_ARRAY_SIZE)
        val physicalSize = ch.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE)

        val capabilities: IntArray =
            ch.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES) ?: IntArray(0)
        val aeModes: IntArray = ch.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_MODES) ?: IntArray(0)
        val afModes: IntArray = ch.get(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES) ?: IntArray(0)
        val stabilizationModes: IntArray =
            ch.get(CameraCharacteristics.CONTROL_AVAILABLE_VIDEO_STABILIZATION_MODES) ?: IntArray(0)

        // LENS_DISTORTION 常量在 API 28 引入；低版本设备按运行时守卫跳过
        val distortionAvailable = Build.VERSION.SDK_INT >= 28 &&
            runCatching { ch.get(CameraCharacteristics.LENS_DISTORTION) != null }.getOrDefault(false)

        return CameraSnapshot(
            cameraId = cameraId,
            facing = when (ch.get(CameraCharacteristics.LENS_FACING)) {
                CameraMetadata.LENS_FACING_FRONT -> "front"
                CameraMetadata.LENS_FACING_BACK -> "back"
                CameraMetadata.LENS_FACING_EXTERNAL -> "external"
                else -> "external"
            },
            hardwareLevel = when (ch.get(CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL)) {
                CameraMetadata.INFO_SUPPORTED_HARDWARE_LEVEL_LEGACY -> "legacy"
                CameraMetadata.INFO_SUPPORTED_HARDWARE_LEVEL_LIMITED -> "limited"
                CameraMetadata.INFO_SUPPORTED_HARDWARE_LEVEL_FULL -> "full"
                CameraMetadata.INFO_SUPPORTED_HARDWARE_LEVEL_3 -> "level_3"
                CameraMetadata.INFO_SUPPORTED_HARDWARE_LEVEL_EXTERNAL -> "external"
                else -> "unknown"
            },
            capabilities = capabilities.toList().mapNotNull(::capabilityName),
            sensorOrientationDeg = ch.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: -1,
            timestampSource = when (ch.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE)) {
                CameraMetadata.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME -> "REALTIME"
                else -> "UNKNOWN"
            },
            physicalIds = if (Build.VERSION.SDK_INT >= 28) ch.physicalCameraIds.toList() else emptyList(),
            activeArrayWidthPx = activeArray?.width(),
            activeArrayHeightPx = activeArray?.height(),
            preCorrectionArrayWidthPx = preCorrection?.width(),
            preCorrectionArrayHeightPx = preCorrection?.height(),
            pixelArrayWidthPx = pixelArray?.width,
            pixelArrayHeightPx = pixelArray?.height,
            physicalWidthMm = physicalSize?.width?.toDouble(),
            physicalHeightMm = physicalSize?.height?.toDouble(),
            exposureTimeRangeNs = exposureRange?.let { it.lower..it.upper },
            sensitivityRangeIso = sensitivityRange?.let { it.lower..it.upper },
            maxFrameDurationNs = ch.get(CameraCharacteristics.SENSOR_INFO_MAX_FRAME_DURATION),
            aeModes = aeModes.toList().mapNotNull(::aeModeName),
            afModes = afModes.toList().mapNotNull(::afModeName),
            minFocusDistanceDiopters = if (Build.VERSION.SDK_INT >= 28) {
                ch.get(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE)?.toDouble()
            } else {
                null
            },
            yuvSizes = yuvSizes,
            fpsRanges = fpsRanges,
            distortionCorrectionAvailable = distortionAvailable,
            videoStabilizationAvailable = stabilizationModes.any {
                it != CameraMetadata.CONTROL_VIDEO_STABILIZATION_MODE_OFF
            },
            requestKeys = ch.availableCaptureRequestKeys.map { it.name },
            resultKeys = ch.availableCaptureResultKeys.map { it.name },
            maxDigitalZoom = ch.get(CameraCharacteristics.SCALER_AVAILABLE_MAX_DIGITAL_ZOOM)?.toDouble(),
        )
    }

    private fun capabilityName(value: Int): String? = when (value) {
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_BACKWARD_COMPATIBLE -> "backward_compatible"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR -> "manual_sensor"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_POST_PROCESSING -> "manual_post_processing"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_RAW -> "raw"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_READ_SENSOR_SETTINGS -> "read_sensor_settings"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_PRIVATE_REPROCESSING -> "private_reprocessing"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_BURST_CAPTURE -> "burst_capture"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_YUV_REPROCESSING -> "yuv_reprocessing"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_DEPTH_OUTPUT -> "depth_output"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_CONSTRAINED_HIGH_SPEED_VIDEO -> "constrained_high_speed_video"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_LOGICAL_MULTI_CAMERA -> "logical_multi_camera"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_MONOCHROME -> "monochrome"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_MOTION_TRACKING -> "motion_tracking"
        else -> "capability_$value"
    }

    /** 只归一化 off/on；闪光等变体保留原始数值名（档位判定只看 off/on）。 */
    private fun aeModeName(value: Int): String? = when (value) {
        CameraMetadata.CONTROL_AE_MODE_OFF -> "off"
        CameraMetadata.CONTROL_AE_MODE_ON -> "on"
        else -> "mode_$value"
    }

    private fun afModeName(value: Int): String? = when (value) {
        CameraMetadata.CONTROL_AF_MODE_OFF -> "off"
        CameraMetadata.CONTROL_AF_MODE_AUTO -> "auto"
        CameraMetadata.CONTROL_AF_MODE_MACRO -> "macro"
        CameraMetadata.CONTROL_AF_MODE_CONTINUOUS_PICTURE -> "continuous_picture"
        CameraMetadata.CONTROL_AF_MODE_CONTINUOUS_VIDEO -> "continuous_video"
        CameraMetadata.CONTROL_AF_MODE_EDOF -> "edof"
        else -> "mode_$value"
    }
}
