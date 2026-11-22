package org.mirrorchecker.probe

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * 探测报告：严格逐相机查找（不从前摄/后摄互相推断）、候选流规划、设备标识与镜像分离。
 */
class ProbeReportTest {

    private fun manualBackCamera() = CameraSnapshot(
        cameraId = "0",
        facing = "back",
        hardwareLevel = "full",
        capabilities = listOf("manual_sensor", "manual_post_processing"),
        sensorOrientationDeg = 90,
        timestampSource = "REALTIME",
        physicalIds = emptyList(),
        activeArrayWidthPx = 4000,
        activeArrayHeightPx = 3000,
        preCorrectionArrayWidthPx = null,
        preCorrectionArrayHeightPx = null,
        pixelArrayWidthPx = null,
        pixelArrayHeightPx = null,
        physicalWidthMm = null,
        physicalHeightMm = null,
        exposureTimeRangeNs = 100_000L..1_000_000_000L,
        sensitivityRangeIso = 50..3200,
        maxFrameDurationNs = null,
        aeModes = listOf("off", "on"),
        afModes = listOf("auto"),
        minFocusDistanceDiopters = null,
        yuvSizes = listOf(YuvSize(1920, 1080), YuvSize(1280, 720)),
        fpsRanges = listOf(FpsRange(30, 30)),
        distortionCorrectionAvailable = false,
        videoStabilizationAvailable = false,
        requestKeys = listOf("android.control.aeLock"),
        resultKeys = emptyList(),
        maxDigitalZoom = null,
    )

    /** 只有 AE 锁的前摄：与后摄能力明显不同，用于验证不互相推断。 */
    private fun lockOnlyFrontCamera() = manualBackCamera().copy(
        cameraId = "1",
        facing = "front",
        hardwareLevel = "limited",
        capabilities = listOf("backward_compatible"),
        exposureTimeRangeNs = null,
        sensitivityRangeIso = null,
        aeModes = listOf("on"),
    )

    private fun display() = DisplaySnapshot(1200, 800, 0, "landscape", 60.0)

    private fun report(trial: TrialResult? = null) = ProbeReport(
        deviceId = ProbeReport.deriveDeviceId("test/fingerprint"),
        manufacturer = "TestVendor",
        model = "TestPad",
        androidRelease = "14",
        androidSdkInt = 34,
        cameras = listOf(
            CameraReport(manualBackCamera(), StreamPlanner.candidates(manualBackCamera().yuvSizes, manualBackCamera().fpsRanges), null),
            CameraReport(lockOnlyFrontCamera(), StreamPlanner.candidates(lockOnlyFrontCamera().yuvSizes, lockOnlyFrontCamera().fpsRanges), trial),
        ),
        display = display(),
        previewMirroring = PreviewMirroring(previewMirrored = true),
        sensors = SensorSummary(gyroscope = true, accelerometer = true),
        generatedAtUtcIso = "2026-11-22T00:00:00Z",
        appVersion = "pr-03-dev",
    )

    @Test
    fun `相机查找严格按 ID，缺失即报错且不回退`() {
        val report = report()
        assertEquals("0", report.camera("0").snapshot.cameraId)
        try {
            report.camera("9")
            fail("不存在的相机必须报错")
        } catch (e: ProbeException) {
            assertTrue(e.message!!.contains("camera_id=9"))
            assertTrue(e.message!!.contains("禁止用其他相机的能力顶替"))
        }
    }

    @Test
    fun `后摄的手动能力不会让前摄升级`() {
        val report = report()
        val back = report.camera("0")
        val front = report.camera("1")
        assertEquals(ControlClassifier.HardwareTier.MANUAL_CAPABLE, back.hardwareTier)
        assertEquals(ControlClassifier.HardwareTier.LOCK_ONLY, front.hardwareTier)
        assertTrue(report.frontCameras().all { it.snapshot.facing == "front" })
        assertEquals(listOf("1"), report.frontCameras().map { it.snapshot.cameraId })
    }

    @Test
    fun `未试开的相机观察档位为空，试开后有档位`() {
        assertNull(report().camera("1").observedClass)
        val trial = TrialResult(
            cameraId = "1",
            widthPx = 1280,
            heightPx = 720,
            targetFps = 30,
            request = TrialRequest("ae_lock", null, null),
            frames = List(12) { index ->
                CapturedFrameTiming(
                    sensorTimestampNs = (index * 33_000_000L).toString(),
                    exposureTimeNs = "8300000",
                    sensitivityIso = 120,
                    frameDurationNs = "33000000",
                    aeState = "LOCKED",
                    afState = null,
                )
            },
        )
        val observed = report(trial).camera("1").observedClass
        assertEquals("lockable", observed!!.controlClass)
    }

    @Test
    fun `报告 JSON 包含契约头与逐相机实测数据`() {
        val json = report().toJson()
        assertEquals("\"1.0.0\"", json["schema_version"].toString())
        assertEquals("\"capability_report\"", json["package_kind"].toString())
        assertEquals("\"device\"", json["provenance"].toString())
        val camerasText = json["cameras"].toString()
        assertTrue(camerasText.contains("camera_id"))
        assertTrue(camerasText.contains("MANUAL_CAPABLE"))
        assertTrue(camerasText.contains("LOCK_ONLY"))
        assertTrue(json.containsKey("display"))
    }

    @Test
    fun `重复相机 ID 被拒绝`() {
        try {
            report().copy(
                cameras = listOf(
                    CameraReport(manualBackCamera(), emptyList(), null),
                    CameraReport(manualBackCamera(), emptyList(), null),
                )
            )
            fail("重复 camera_id 必须抛出 ProbeException")
        } catch (expected: ProbeException) {
        }
    }

    @Test
    fun `设备标识由指纹确定派生且不含个人信息`() {
        val a = ProbeReport.deriveDeviceId("vendor/model/device:release")
        val b = ProbeReport.deriveDeviceId("vendor/model/device:release")
        val c = ProbeReport.deriveDeviceId("vendor/model/device:other")
        assertEquals(a, b)
        assertNotEquals(a, c)
        assertTrue(a.startsWith("android:"))
        assertEquals("android:".length + 16, a.length)
    }

    @Test
    fun `预览镜像换算显式且计算帧永不镜像`() {
        val mirroring = PreviewMirroring(previewMirrored = true)
        assertTrue(mirroring.frameMirrored.not())
        assertEquals(9, mirroring.previewXToImageX(0, 10))
        assertEquals(0, mirroring.previewXToImageX(9, 10))
        val noMirror = PreviewMirroring(previewMirrored = false)
        assertEquals(3, noMirror.previewXToImageX(3, 10))
        assertTrue(mirroring.toJson()["frame_mirrored"].toString().contains("false"))
    }

    @Test
    fun `候选流过滤极端长宽比并按面积降序`() {
        val sizes = listOf(
            YuvSize(1920, 480), // 4:1 排除
            YuvSize(640, 480),
            YuvSize(1920, 1080),
            YuvSize(1600, 1200),
        )
        val candidates = StreamPlanner.candidates(sizes, listOf(FpsRange(15, 30), FpsRange(30, 30)))
        assertEquals(
            listOf("1920x1080", "1600x1200", "640x480"),
            candidates.map { "${it.size.widthPx}x${it.size.heightPx}" },
        )
        assertEquals(30, candidates[0].targetFps)
        assertEquals(30, candidates[0].fpsRange.maxFps)
    }

    @Test
    fun `目标帧率不可覆盖时选最接近的范围`() {
        val (fps, range) = StreamPlanner.pickFps(listOf(FpsRange(30, 30), FpsRange(15, 60)), targetFps = 60)
        assertEquals(60, fps)
        assertEquals(60, range.maxFps)
        val (fps30, range30) = StreamPlanner.pickFps(listOf(FpsRange(30, 30)), targetFps = 60)
        assertEquals(30, fps30)
        assertEquals(30, range30.maxFps)
    }
}
