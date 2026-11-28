package org.mirrorchecker.probe

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * 三档控制分类（手动受控/可锁定/自动不可控）与稳定性判据（实施方案 §5.1）。
 */
class ControlClassifierTest {

    private fun manualCapableCamera(id: String = "0", facing: String = "front") = CameraSnapshot(
        cameraId = id,
        facing = facing,
        hardwareLevel = "full",
        capabilities = listOf("manual_sensor", "manual_post_processing", "raw"),
        sensorOrientationDeg = 270,
        timestampSource = "REALTIME",
        physicalIds = emptyList(),
        activeArrayWidthPx = 4000,
        activeArrayHeightPx = 3000,
        preCorrectionArrayWidthPx = 4016,
        preCorrectionArrayHeightPx = 3016,
        pixelArrayWidthPx = 4056,
        pixelArrayHeightPx = 3040,
        physicalWidthMm = 5.6,
        physicalHeightMm = 4.2,
        exposureTimeRangeNs = 100_000L..1_000_000_000L,
        sensitivityRangeIso = 50..3200,
        maxFrameDurationNs = 1_000_000_000L,
        aeModes = listOf("off", "on", "always_on"),
        afModes = listOf("off", "auto", "continuous_picture"),
        minFocusDistanceDiopters = 0.0,
        yuvSizes = listOf(YuvSize(1600, 1200), YuvSize(1280, 960), YuvSize(640, 480)),
        fpsRanges = listOf(FpsRange(15, 30), FpsRange(30, 30)),
        distortionCorrectionAvailable = true,
        videoStabilizationAvailable = false,
        requestKeys = listOf("android.control.aeLock", "android.sensor.exposureTime", "android.sensor.sensitivity"),
        resultKeys = listOf("android.sensor.exposureTime", "android.sensor.timestamp"),
        maxDigitalZoom = 4.0,
    )

    private fun lockOnlyCamera(id: String = "1", facing: String = "front") = manualCapableCamera(id, facing).copy(
        hardwareLevel = "limited",
        capabilities = listOf("backward_compatible"),
        exposureTimeRangeNs = null,
        sensitivityRangeIso = null,
        aeModes = listOf("on", "always_on"),
    )

    private fun frame(index: Int, exposureNs: Long = 10_000_000L, iso: Int = 100, periodNs: Long = 33_000_000L) =
        CapturedFrameTiming(
            sensorTimestampNs = (index * periodNs).toString(),
            exposureTimeNs = exposureNs.toString(),
            sensitivityIso = iso,
            frameDurationNs = periodNs.toString(),
            aeState = "CONVERGED",
            afState = "FOCUSED",
        )

    private fun manualTrial(frames: List<CapturedFrameTiming>, error: String? = null) = TrialResult(
        cameraId = "0",
        widthPx = 1600,
        heightPx = 1200,
        targetFps = 30,
        request = TrialRequest("manual", 10_000_000L, 100),
        frames = frames,
        error = error,
    )

    @Test
    fun `硬件能力层按本相机能力判定三档`() {
        assertEquals(
            ControlClassifier.HardwareTier.MANUAL_CAPABLE,
            ControlClassifier.hardwareTier(manualCapableCamera()),
        )
        assertEquals(
            ControlClassifier.HardwareTier.LOCK_ONLY,
            ControlClassifier.hardwareTier(lockOnlyCamera()),
        )
        val uncontrolled = lockOnlyCamera().copy(
            aeModes = listOf("on"),
            requestKeys = emptyList(),
        )
        assertEquals(
            ControlClassifier.HardwareTier.UNCONTROLLED,
            ControlClassifier.hardwareTier(uncontrolled),
        )
    }

    @Test
    fun `试开请求按本相机档位选择且手动参数夹紧到可用范围`() {
        val manual = manualCapableCamera().copy(
            exposureTimeRangeNs = 20_000_000L..30_000_000L,
            sensitivityRangeIso = 50..80,
        )
        assertEquals(TrialRequest("manual", 20_000_000L, 80), ControlClassifier.trialRequest(manual))
        val lockOnly = lockOnlyCamera()
        assertEquals(TrialRequest("ae_lock", null, null), ControlClassifier.trialRequest(lockOnly))
        val auto = lockOnly.copy(requestKeys = emptyList())
        assertEquals(TrialRequest("auto", null, null), ControlClassifier.trialRequest(auto))

        val trial = manualTrial(List(12) { frame(it) })
        assertNull(ControlClassifier.observedClass(lockOnly, trial))
        val lockTrial = trial.copy(cameraId = auto.cameraId, request = TrialRequest("ae_lock", null, null))
        assertEquals("uncontrolled", ControlClassifier.observedClass(auto, lockTrial)?.controlClass)
    }

    @Test
    fun `没有 AE OFF 或曝光范围时手动能力不成立`() {
        val noAeOff = manualCapableCamera().copy(aeModes = listOf("on"))
        assertEquals(ControlClassifier.HardwareTier.LOCK_ONLY, ControlClassifier.hardwareTier(noAeOff))
        val noRange = manualCapableCamera().copy(exposureTimeRangeNs = null)
        assertEquals(ControlClassifier.HardwareTier.LOCK_ONLY, ControlClassifier.hardwareTier(noRange))
    }

    @Test
    fun `手动模式实测一致且稳定时授予 manual 档`() {
        val trial = manualTrial(List(12) { frame(it) })
        val observed = ControlClassifier.observedClass(manualCapableCamera(), trial)
        assertNotNull(observed)
        assertEquals("manual", observed!!.controlClass)
        assertTrue(observed.stability!!.stable)
        assertTrue(observed.stability.matchesRequest)
    }

    @Test
    fun `预热帧不参与稳定性评估且有效帧不足判不稳定`() {
        // 前 3 帧曝光乱跳（自动收敛预热），之后稳定
        val frames = List(3) { frame(it, exposureNs = (20_000_000L * (it + 1))) } + List(6) { frame(it + 3) }
        val stability = ControlClassifier.evaluateStability(manualTrial(frames))
        assertTrue(stability.stable)

        val tooFew = manualTrial(List(5) { frame(it) })
        val fewStability = ControlClassifier.evaluateStability(tooFew)
        assertFalse(fewStability.stable)
        assertTrue(fewStability.unstableReason!!.contains("有效帧不足"))
    }

    @Test
    fun `曝光漂移或 ISO 跳档判不稳定并降档`() {
        val drifting = manualTrial(List(12) { frame(it, exposureNs = if (it % 2 == 0) 10_000_000L else 15_000_000L) })
        val observed = ControlClassifier.observedClass(manualCapableCamera(), drifting)
        assertNotNull(observed)
        assertEquals("uncontrolled", observed!!.controlClass)
        assertTrue(observed.stability!!.unstableReason!!.contains("曝光相对标准差"))

        // ISO 在 3 档之间跳变（判据：去重 >2 档不稳定）
        val isoJump = manualTrial(
            List(12) { frame(it, iso = listOf(100, 400, 800)[it % 3]) }
        )
        assertTrue(ControlClassifier.evaluateStability(isoJump).unstableReason!!.contains("ISO"))
    }

    @Test
    fun `帧间隔抖动过大提示时序问题`() {
        // 中间一帧间隔偏差 50%
        val frames = List(12) { index ->
            val period = if (index == 7) 49_500_000L else 33_000_000L
            CapturedFrameTiming(
                sensorTimestampNs = (index * 33_000_000L + (if (index > 7) 16_500_000L else 0)).toString(),
                exposureTimeNs = "10000000",
                sensitivityIso = 100,
                frameDurationNs = period.toString(),
                aeState = "CONVERGED",
                afState = null,
            )
        }
        val stability = ControlClassifier.evaluateStability(manualTrial(frames))
        assertTrue(stability.unstableReason!!.contains("帧间隔抖动"))
    }

    @Test
    fun `AE 锁实测稳定授予 lockable 档`() {
        val lockTrial = TrialResult(
            cameraId = "1",
            widthPx = 1600,
            heightPx = 1200,
            targetFps = 30,
            request = TrialRequest("ae_lock", null, null),
            frames = List(12) { frame(it) },
        )
        val observed = ControlClassifier.observedClass(lockOnlyCamera(), lockTrial)
        assertNotNull(observed)
        assertEquals("lockable", observed!!.controlClass)
    }

    @Test
    fun `手动能力但手动实测不稳时不冒领 manual`() {
        val unstableManual = manualTrial(
            List(12) { frame(it, exposureNs = if (it % 3 == 0) 20_000_000L else 10_000_000L) }
        )
        val observed = ControlClassifier.observedClass(manualCapableCamera(), unstableManual)
        assertEquals("uncontrolled", observed!!.controlClass)
        assertTrue(observed.reasons.any { it.contains("手动模式试开未通过") })
    }

    @Test
    fun `试开失败或未试开不得给出档位`() {
        assertNull(ControlClassifier.observedClass(manualCapableCamera(), null))
        val failed = manualTrial(emptyList(), error = "打开相机被拒绝")
        assertNull(ControlClassifier.observedClass(manualCapableCamera(), failed))
    }
}
