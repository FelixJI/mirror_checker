package org.mirrorchecker.probe

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * 相机控制档位判定（实施方案 §5.1 的三档）：
 * manual=手动受控；lockable=可锁定且实测稳定；uncontrolled=自动参数不可控
 * （只能采诊断数据，不能进入定量支持名单）。
 *
 * 判定分两层：
 * 1. [hardwareTier] 只看本相机实测能力（manual_sensor、AE OFF、AE 锁可用性）；
 * 2. [observedClass] 结合试开（trial）的实际生效参数与稳定性。没有试开数据时
 *    返回 null——device.json 的 control_class 不允许由能力表单方面填写。
 * 所有两层判定都以传入的 [CameraSnapshot] 为准，不使用其他相机的任何信息。
 */
object ControlClassifier {

    /** 硬件能力层（未经实测验证）。 */
    enum class HardwareTier { MANUAL_CAPABLE, LOCK_ONLY, UNCONTROLLED }

    /** 实测观察层结果：null 表示尚未实测。 */
    data class ObservedClass(
        val controlClass: String,
        val reasons: List<String>,
        val stability: TrialStability?,
    ) {
        fun toJson(): JsonObject = buildJsonObject {
            put("control_class", controlClass)
            put("reasons", stringsToJson(reasons))
            stability?.let { put("stability", it.toJson()) }
        }
    }

    fun hardwareTier(snapshot: CameraSnapshot): HardwareTier {
        val manual = snapshot.hasManualSensor && snapshot.aeOffAvailable &&
            snapshot.exposureTimeRangeNs != null && snapshot.sensitivityRangeIso != null
        if (manual) return HardwareTier.MANUAL_CAPABLE
        if (snapshot.aeLockAvailable) return HardwareTier.LOCK_ONLY
        return HardwareTier.UNCONTROLLED
    }

    /**
     * 结合试开结果给出 device.json 的 control_class（manual/lockable/uncontrolled）。
     * trial 为 null 或试开失败时返回 null（未实测，不得填入正式档案）。
     */
    fun observedClass(snapshot: CameraSnapshot, trial: TrialResult?): ObservedClass? {
        if (trial == null || trial.error != null) return null
        val stability = evaluateStability(trial)
        val tier = hardwareTier(snapshot)

        // 手动受控：硬件支持 + 试开就是手动模式 + 实际参数与请求一致且稳定。
        if (tier == HardwareTier.MANUAL_CAPABLE &&
            trial.request.mode == "manual" &&
            stability.matchesRequest && stability.stable
        ) {
            return ObservedClass(
                "manual",
                listOf(
                    "manual_sensor 能力由本相机实测",
                    "手动曝光试开：实际曝光/ISO 与请求一致且稳定",
                ),
                stability,
            )
        }

        // 可锁定：AE 锁实测曝光稳定（硬件只支持锁，或手动模式实测不稳定时降档）。
        val lockTrial = trial.request.mode == "ae_lock"
        if (lockTrial && stability.stable) {
            val reasons = buildList {
                add("AE 锁试开：曝光与帧间隔实测稳定")
                if (tier == HardwareTier.MANUAL_CAPABLE) {
                    add("具备 manual_sensor 能力，但手动模式未实测通过，暂不授予 manual 档")
                }
            }
            return ObservedClass("lockable", reasons, stability)
        }

        val reasons = buildList {
            if (trial.request.mode == "manual") add("手动模式试开未通过：实际参数与请求不一致或不稳定")
            if (!stability.stable) add("实测不稳定：${stability.unstableReason ?: "判据未满足"}")
            if (tier == HardwareTier.UNCONTROLLED) add("硬件不支持手动或锁定控制")
        }
        return ObservedClass("uncontrolled", reasons, stability)
    }

    /**
     * 试开稳定性评估（首版诊断判据，不是计量规格）：
     * - 丢弃前 [WARM_UP_FRAMES] 帧自动收敛预热；
     * - 曝光相对标准差 <= 0.02 且 ISO 去重值 <= 2 档判为稳定；
     * - 手动模式另外要求 >=90% 帧的实际曝光/ISO 与请求偏差 <=5%；
     * - 帧间隔相对中位数的最大偏差 <= 20%（时间戳用 SENSOR_TIMESTAMP，
     *   抖动异常提示显示/曝光时序问题，不作为精度保证）。
     */
    fun evaluateStability(trial: TrialResult): TrialStability {
        val warmed = trial.frames.drop(WARM_UP_FRAMES)
        if (warmed.size < MIN_EVAL_FRAMES) {
            return TrialStability(
                stable = false,
                matchesRequest = false,
                unstableReason = "有效帧不足：丢弃 ${WARM_UP_FRAMES} 帧预热后仅 ${warmed.size} 帧（需 >=$MIN_EVAL_FRAMES）",
            )
        }

        val exposures = warmed.map { it.exposureTimeNs.toLong() }
        val sensitivities = warmed.map { it.sensitivityIso }
        val timestamps = warmed.map { it.sensorTimestampNs.toLong() }

        val expMean = exposures.average()
        val expStd = if (expMean > 0) kotlin.math.sqrt(exposures.sumOf { val d = it - expMean; d * d } / exposures.size) / expMean else 1.0
        val isoDistinct = sensitivities.distinct().size

        val deltas = timestamps.zipWithNext { a, b -> b - a }.filter { it > 0 }
        val medianDelta = if (deltas.isNotEmpty()) deltas.sorted()[deltas.size / 2] else 0L
        val maxJitter = if (deltas.isNotEmpty() && medianDelta > 0) {
            deltas.maxOf { kotlin.math.abs(it - medianDelta).toDouble() / medianDelta }
        } else {
            1.0
        }

        var unstable: String? = null
        if (expStd > 0.02) unstable = "曝光相对标准差 ${"%.4f".format(expStd)} > 0.02"
        if (isoDistinct > 2) unstable = (unstable ?: "") + "；ISO 去重后 $isoDistinct 档 > 2"
        if (maxJitter > 0.20) unstable = (unstable ?: "") + "；帧间隔抖动 ${(maxJitter * 100).toInt()}% > 20%"

        var matchesRequest = false
        if (trial.request.mode == "manual") {
            val reqExp = trial.request.requestedExposureTimeNs
            val reqIso = trial.request.requestedSensitivityIso
            if (reqExp == null || reqIso == null) {
                matchesRequest = false
            } else {
                val expOk = exposures.count { kotlin.math.abs(it - reqExp) <= reqExp * 0.05 + 1 }
                val isoOk = sensitivities.count { kotlin.math.abs(it - reqIso) <= reqIso * 0.05 + 1 }
                matchesRequest = expOk >= warmed.size * 0.9 && isoOk >= warmed.size * 0.9
            }
        } else {
            // 非手动模式没有「与请求一致」可查：只报告稳定性。
            matchesRequest = unstable == null
        }

        return TrialStability(
            stable = unstable == null,
            matchesRequest = matchesRequest,
            unstableReason = unstable,
            exposureRelStd = expStd,
            isoDistinct = isoDistinct,
            frameJitterRatio = maxJitter,
            evaluatedFrames = warmed.size,
        )
    }

    const val WARM_UP_FRAMES = 3
    const val MIN_EVAL_FRAMES = 6
}

/** 稳定性指标。字段在 unstable 时仍尽量填充，便于诊断。 */
data class TrialStability(
    val stable: Boolean,
    val matchesRequest: Boolean,
    val unstableReason: String?,
    val exposureRelStd: Double = Double.NaN,
    val isoDistinct: Int = -1,
    val frameJitterRatio: Double = Double.NaN,
    val evaluatedFrames: Int = 0,
) {
    fun toJson(): JsonObject = buildJsonObject {
        put("stable", stable)
        put("matches_request", matchesRequest)
        unstableReason?.let { put("unstable_reason", it) }
        if (!exposureRelStd.isNaN()) put("exposure_rel_std", exposureRelStd)
        if (isoDistinct >= 0) put("iso_distinct", isoDistinct)
        if (!frameJitterRatio.isNaN()) put("frame_jitter_ratio", frameJitterRatio)
        put("evaluated_frames", evaluatedFrames)
    }
}
