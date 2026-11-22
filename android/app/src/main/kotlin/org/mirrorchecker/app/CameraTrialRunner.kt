package org.mirrorchecker.app

import android.content.Context
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import android.hardware.camera2.TotalCaptureResult
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import android.util.Range
import android.view.Surface
import kotlinx.coroutines.suspendCancellableCoroutine
import org.mirrorchecker.probe.CapturedFrameTiming
import org.mirrorchecker.probe.FpsRange
import org.mirrorchecker.probe.TrialRequest
import org.mirrorchecker.probe.TrialResult
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * 试开目标相机流（PR-03 验收：捕获实际配置）。
 *
 * 打开一个 YUV_420_888 流，按相机能力选择：
 * - manual：AE 关 + 显式曝光/ISO（默认 10 ms、ISO 100，由调用方夹紧到实测范围后传入）；
 * - ae_lock：AE 开 + AE 锁，等待自动收敛后观察稳定性。
 * 记录每帧实际生效的曝光、ISO、SENSOR_TIMESTAMP 与帧周期，
 * 结果交给 :probe 的 ControlClassifier 判档；不在此处下结论。
 * 预览不参与：试开只有采集流，避免镜像预览污染坐标（§2.1）。
 */
class CameraTrialRunner(private val context: Context) {

    data class Config(
        val widthPx: Int,
        val heightPx: Int,
        val targetFps: Int,
        val fpsRange: FpsRange,
        val mode: String,
        /** manual 模式的请求值（已夹紧到相机实测范围）。 */
        val requestedExposureTimeNs: Long? = null,
        val requestedSensitivityIso: Int? = null,
    ) {
        init {
            if (mode == "manual") {
                require(requestedExposureTimeNs != null && requestedSensitivityIso != null) {
                    "manual 模式必须提供请求曝光与 ISO"
                }
            }
        }
    }

    suspend fun run(
        cameraId: String,
        config: Config,
        captureCount: Int = 16,
        timeoutMs: Long = 10_000,
    ): TrialResult {
        val frames = ConcurrentLinkedQueue<CapturedFrameTiming>()

        // 全部资源在 finally 释放；异常转成带原因的 TrialResult，不伪装成功
        var session: CameraCaptureSession? = null
        var device: CameraDevice? = null
        var reader: ImageReader? = null
        var thread: HandlerThread? = null

        try {
            thread = HandlerThread("trial-$cameraId").also { it.start() }
            val handler = Handler(thread.looper)

            val manager = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
            device = manager.openCameraCompat(cameraId, handler)

            reader = ImageReader.newInstance(config.widthPx, config.heightPx, android.graphics.ImageFormat.YUV_420_888, 3)
            reader.setOnImageAvailableListener({ r -> r.acquireLatestImage()?.close() }, handler)

            val request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                addTarget(reader.surface)
                set(
                    CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE,
                    Range(config.fpsRange.minFps, config.fpsRange.maxFps),
                )
                if (config.mode == "manual") {
                    set(CaptureRequest.CONTROL_AE_MODE, CameraMetadata.CONTROL_AE_MODE_OFF)
                    val exposure = config.requestedExposureTimeNs
                    val sensitivity = config.requestedSensitivityIso
                    if (exposure != null && sensitivity != null) {
                        set(CaptureRequest.SENSOR_EXPOSURE_TIME, exposure)
                        set(CaptureRequest.SENSOR_SENSITIVITY, sensitivity)
                    }
                } else {
                    set(CaptureRequest.CONTROL_AE_MODE, CameraMetadata.CONTROL_AE_MODE_ON)
                    set(CaptureRequest.CONTROL_AE_LOCK, true)
                }
            }

            val latch = CountDownLatch(captureCount)
            val callback = object : CameraCaptureSession.CaptureCallback() {
                override fun onCaptureCompleted(
                    session: CameraCaptureSession,
                    request: CaptureRequest,
                    result: TotalCaptureResult,
                ) {
                    if (frames.size >= captureCount) return
                    frames.add(
                        CapturedFrameTiming(
                            sensorTimestampNs = (result.get(CaptureResult.SENSOR_TIMESTAMP) ?: 0L).toString(),
                            exposureTimeNs = (result.get(CaptureResult.SENSOR_EXPOSURE_TIME) ?: 0L).toString(),
                            sensitivityIso = result.get(CaptureResult.SENSOR_SENSITIVITY) ?: 0,
                            frameDurationNs = (result.get(CaptureResult.SENSOR_FRAME_DURATION) ?: 0L).toString(),
                            aeState = result.get(CaptureResult.CONTROL_AE_STATE)?.let(::aeStateName),
                            afState = result.get(CaptureResult.CONTROL_AF_STATE)?.let(::afStateName),
                        )
                    )
                    latch.countDown()
                }
            }

            session = device.createSessionCompat(reader.surface, handler)
            session.setRepeatingRequest(request.build(), callback, handler)
            latch.await(timeoutMs, TimeUnit.MILLISECONDS)

            return TrialResult(
                cameraId = cameraId,
                widthPx = config.widthPx,
                heightPx = config.heightPx,
                targetFps = config.targetFps,
                request = TrialRequest(
                    mode = config.mode,
                    requestedExposureTimeNs = config.requestedExposureTimeNs,
                    requestedSensitivityIso = config.requestedSensitivityIso,
                ),
                frames = frames.toList(),
                error = if (frames.isEmpty()) "试开未收到任何 CaptureResult（超时 ${timeoutMs}ms）" else null,
            )
        } catch (t: Throwable) {
            return TrialResult(
                cameraId = cameraId,
                widthPx = config.widthPx,
                heightPx = config.heightPx,
                targetFps = config.targetFps,
                request = TrialRequest(
                    mode = config.mode,
                    requestedExposureTimeNs = config.requestedExposureTimeNs,
                    requestedSensitivityIso = config.requestedSensitivityIso,
                ),
                frames = frames.toList(),
                error = "试开失败：${t.javaClass.simpleName}: ${t.message}",
            )
        } finally {
            runCatching { session?.stopRepeating() }
            runCatching { session?.close() }
            runCatching { reader?.close() }
            runCatching { device?.close() }
            thread?.quitSafely()
        }
    }

    private fun aeStateName(value: Int): String = when (value) {
        CameraMetadata.CONTROL_AE_STATE_INACTIVE -> "INACTIVE"
        CameraMetadata.CONTROL_AE_STATE_SEARCHING -> "SEARCHING"
        CameraMetadata.CONTROL_AE_STATE_CONVERGED -> "CONVERGED"
        CameraMetadata.CONTROL_AE_STATE_LOCKED -> "LOCKED"
        CameraMetadata.CONTROL_AE_STATE_FLASH_REQUIRED -> "FLASH_REQUIRED"
        CameraMetadata.CONTROL_AE_STATE_PRECAPTURE -> "PRECAPTURE"
        else -> "STATE_$value"
    }

    private fun afStateName(value: Int): String = when (value) {
        CameraMetadata.CONTROL_AF_STATE_INACTIVE -> "INACTIVE"
        CameraMetadata.CONTROL_AF_STATE_PASSIVE_SCAN -> "PASSIVE_SCAN"
        CameraMetadata.CONTROL_AF_STATE_PASSIVE_FOCUSED -> "PASSIVE_FOCUSED"
        CameraMetadata.CONTROL_AF_STATE_ACTIVE_SCAN -> "ACTIVE_SCAN"
        CameraMetadata.CONTROL_AF_STATE_FOCUSED_LOCKED -> "FOCUSED_LOCKED"
        CameraMetadata.CONTROL_AF_STATE_NOT_FOCUSED_LOCKED -> "NOT_FOCUSED_LOCKED"
        CameraMetadata.CONTROL_AF_STATE_PASSIVE_UNFOCUSED -> "PASSIVE_UNFOCUSED"
        else -> "STATE_$value"
    }

    private suspend fun CameraManager.openCameraCompat(id: String, handler: Handler): CameraDevice =
        suspendCancellableCoroutine { cont ->
            openCamera(
                id,
                object : CameraDevice.StateCallback() {
                    override fun onOpened(camera: CameraDevice) {
                        if (cont.isActive) cont.resume(camera)
                    }

                    override fun onDisconnected(camera: CameraDevice) {
                        camera.close()
                        if (cont.isActive) cont.resumeWithException(IllegalStateException("相机被系统断开"))
                    }

                    override fun onError(camera: CameraDevice, error: Int) {
                        camera.close()
                        if (cont.isActive) cont.resumeWithException(IllegalStateException("打开相机错误码 $error"))
                    }
                },
                handler,
            )
        }

    /** minSdk 26 无 SessionConfiguration（API 28+）；统一走旧接口，两档系统行为一致。 */
    private suspend fun CameraDevice.createSessionCompat(surface: Surface, handler: Handler): CameraCaptureSession =
        suspendCancellableCoroutine { cont ->
            createCaptureSession(
                listOf(surface),
                object : CameraCaptureSession.StateCallback() {
                    override fun onConfigured(session: CameraCaptureSession) {
                        if (cont.isActive) cont.resume(session)
                    }

                    override fun onConfigureFailed(session: CameraCaptureSession) {
                        session.close()
                        if (cont.isActive) cont.resumeWithException(IllegalStateException("相机会话配置失败"))
                    }
                },
                handler,
            )
        }
}
