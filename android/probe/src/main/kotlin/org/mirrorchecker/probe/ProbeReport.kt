package org.mirrorchecker.probe

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.mirrorchecker.contracts.Contracts
import org.mirrorchecker.contracts.JsonUtil

/**
 * 安卓能力探测报告（PR-03 交付物，H03 的人工证据）。
 *
 * 这是诊断产物（package_kind=capability_report），不是会话包内的 device.json：
 * device.json 要求实测有效发光尺寸等 H05 才能得到的字段，此处不伪造。
 * 报告中每个相机的数据都来自该相机自己的查询/试开；跨相机推断被
 * [camera] 的严格查找阻止（验收：不根据后摄能力判断前摄）。
 */
data class ProbeReport(
    val deviceId: String,
    val manufacturer: String?,
    val model: String?,
    val androidRelease: String?,
    val androidSdkInt: Int?,
    val cameras: List<CameraReport>,
    val display: DisplaySnapshot,
    /** 本次探测界面的预览镜像配置（预览与计算坐标分离的证据）。 */
    val previewMirroring: PreviewMirroring,
    val sensors: SensorSummary,
    val generatedAtUtcIso: String,
    /** 生成报告的应用版本（git describe 或 versionName），人工证据溯源用。 */
    val appVersion: String,
) {
    init {
        require(cameras.isNotEmpty()) { "能力报告至少包含一个相机的实测数据" }
        val duplicated = cameras.groupBy { it.snapshot.cameraId }.filterValues { it.size > 1 }.keys
        if (duplicated.isNotEmpty()) throw ProbeException("报告内 camera_id 重复：$duplicated")
    }

    /**
     * 严格按 camera_id 查找；不存在即抛错，绝不回退或用其他相机顶替
     * （后摄有能力不代表前摄有，实施方案 §5.1）。
     */
    fun camera(cameraId: String): CameraReport {
        return cameras.firstOrNull { it.snapshot.cameraId == cameraId }
            ?: throw ProbeException(
                "probe_report: camera_id=$cameraId 不在本次逐相机实测名单 " +
                    "(${cameras.joinToString { it.snapshot.cameraId }})；禁止用其他相机的能力顶替"
            )
    }

    /** 全部前置相机（可能为空：设备没有前摄或被禁用）。 */
    fun frontCameras(): List<CameraReport> = cameras.filter { it.snapshot.facing == "front" }

    fun toJson(): JsonObject = buildJsonObject {
        put("schema_version", Contracts.SCHEMA_VERSION)
        put("package_kind", PACKAGE_KIND)
        put("provenance", "device")
        put("device_id", deviceId)
        manufacturer?.let { put("manufacturer", it) }
        model?.let { put("model", it) }
        put("android", buildJsonObject {
            androidRelease?.let { put("version_release", it) }
            androidSdkInt?.let { put("sdk_int", it) }
        })
        put("cameras", JsonArray(cameras.map { it.toJson() }))
        put("display", display.toJson())
        put("preview_mirroring", previewMirroring.toJson())
        put("sensors", sensors.toJson())
        put("generated_at_utc", generatedAtUtcIso)
        put("app_version", appVersion)
    }

    /** 规范 JSON 的 SHA-256：报告文件的完整性标识（分享与归档时核对）。 */
    fun canonicalSha256(): String = JsonUtil.canonicalSha256(toJson())

    companion object {
        const val PACKAGE_KIND = "capability_report"

        /**
         * 稳定设备标识：由系统 Build 指纹派生，不含序列号等直接个人信息；
         * 同一系统版本重刷会变化，作为诊断报告的分组键足够。
         */
        fun deriveDeviceId(buildFingerprint: String): String =
            "android:" + JsonUtil.sha256Hex(buildFingerprint.encodeToByteArray()).take(16)
    }
}

/** 单相机报告 = 能力快照 + 候选流 + 试开结果与档位判定。 */
data class CameraReport(
    val snapshot: CameraSnapshot,
    val streamCandidates: List<StreamCandidate>,
    val trial: TrialResult?,
) {
    /** 硬件能力层判定（仅本相机能力）。 */
    val hardwareTier: ControlClassifier.HardwareTier get() = ControlClassifier.hardwareTier(snapshot)

    /** 实测档位；未试开或试开失败为 null（不得写入正式 device.json）。 */
    val observedClass: ControlClassifier.ObservedClass? get() = ControlClassifier.observedClass(snapshot, trial)

    fun toJson(): JsonObject = buildJsonObject {
        put("snapshot", snapshot.toJson())
        put("hardware_tier", hardwareTier.name)
        put("stream_candidates", JsonArray(streamCandidates.map { it.toJson() }))
        trial?.let { put("trial", it.toJson()) }
        observedClass?.let { put("observed_class", it.toJson()) }
    }
}

/** IMU 等运动传感器可用性（§5.1：显示模式、亮度、传感器信息一并记录）。 */
data class SensorSummary(
    val gyroscope: Boolean,
    val accelerometer: Boolean,
) {
    fun toJson(): JsonObject = buildJsonObject {
        put("gyroscope", gyroscope)
        put("accelerometer", accelerometer)
    }
}
