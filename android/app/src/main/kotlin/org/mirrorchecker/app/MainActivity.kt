package org.mirrorchecker.app

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorManager
import android.hardware.camera2.CameraManager
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.mirrorchecker.probe.CameraReport
import org.mirrorchecker.probe.CameraSnapshot
import org.mirrorchecker.probe.ControlClassifier
import org.mirrorchecker.probe.DiagnosticPattern
import org.mirrorchecker.probe.PatternKind
import org.mirrorchecker.probe.PreviewMirroring
import org.mirrorchecker.probe.ProbeReport
import org.mirrorchecker.probe.SensorSummary
import org.mirrorchecker.probe.StreamPlanner
import org.mirrorchecker.probe.TrialResult
import java.time.Instant

/**
 * PR-03 诊断入口：能力探测（含试开相机流与报告分享）＋ 全屏诊断图案。
 *
 * 本应用只做诊断：不等待几何标定即可采样，也不输出任何定量镜面结论（§5.1）。
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                AppRoot(this)
            }
        }
    }
}

@Composable
fun AppRoot(activity: MainActivity) {
    var screen by remember { mutableStateOf("probe") }
    if (screen == "pattern") {
        PatternScreen(activity, onExit = { screen = "probe" })
    } else {
        ProbeScreen(activity, onOpenPatterns = { screen = "pattern" })
    }
}

// ---------------------------------------------------------------------------
// 能力探测
// ---------------------------------------------------------------------------

@Composable
fun ProbeScreen(activity: MainActivity, onOpenPatterns: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var cameraGranted by remember { mutableStateOf(false) }
    var snapshots by remember { mutableStateOf<List<CameraSnapshot>>(emptyList()) }
    var trials by remember { mutableStateOf<Map<String, TrialResult>>(emptyMap()) }
    var busy by remember { mutableStateOf<String?>(null) }
    var message by remember { mutableStateOf("授予相机权限后读取逐相机能力；再按需试开相机流。") }

    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        cameraGranted = granted
        if (!granted) message = "没有相机权限：只能浏览已读取的能力，无法试开相机流。"
    }

    fun loadCameras() {
        busy = "读取相机能力"
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    val manager = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
                    AndroidCameraMapper.enumerate(manager)
                }
            }
            result.onSuccess {
                snapshots = it
                trials = emptyMap()
                message = if (it.isEmpty()) "未发现任何相机。" else "读到 ${it.size} 个相机，逐相机列出；试开会打开 YUV 流记录实际参数。"
            }.onFailure {
                message = "读取失败：${it.message}"
            }
            busy = null
        }
    }

    LaunchedEffect(Unit) {
        cameraGranted = ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Text("镜面检测 · 能力探测", style = MaterialTheme.typography.titleLarge)
            Text(
                "诊断模式：不依赖几何标定。试开只有采集流，无镜像预览；" +
                    "预览镜像与否不改变任何计算坐标（报告记录 preview_mirrored）。",
                style = MaterialTheme.typography.bodySmall,
            )
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = {
                        if (cameraGranted) loadCameras() else permissionLauncher.launch(Manifest.permission.CAMERA)
                    },
                    enabled = busy == null,
                ) { Text(if (cameraGranted) "读取相机能力" else "授予相机权限") }
                OutlinedButton(onClick = onOpenPatterns) { Text("诊断图案") }
            }
        }
        item {
            Text(message, style = MaterialTheme.typography.bodyMedium)
            if (busy != null) Text("$busy…", style = MaterialTheme.typography.bodySmall)
        }

        items(snapshots, key = { it.cameraId }) { snapshot ->
            CameraCard(
                snapshot = snapshot,
                trial = trials[snapshot.cameraId],
                busy = busy,
                onTrial = {
                    scope.launch {
                        busy = "试开 ${snapshot.cameraId}"
                        val trial = withContext(Dispatchers.IO) {
                            runTrial(context, snapshot)
                        }
                        trials = trials + (snapshot.cameraId to trial)
                        busy = null
                    }
                },
            )
        }

        if (snapshots.isNotEmpty()) {
            item {
                Button(
                    onClick = {
                        scope.launch {
                            busy = "生成报告"
                            val report = withContext(Dispatchers.IO) {
                                buildReport(context, snapshots, trials)
                            }
                            runCatching {
                                val file = ReportStore.save(context, report)
                                ReportStore.share(context, file)
                            }.onFailure { message = "分享失败：${it.message}" }
                            busy = null
                        }
                    },
                    enabled = busy == null,
                ) { Text("生成并分享能力报告") }
                Text(
                    "报告含逐相机实测能力、试开实际参数、显示/Surface 状态与其指纹，作为 H03 证据提交。",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun CameraCard(
    snapshot: CameraSnapshot,
    trial: TrialResult?,
    busy: String?,
    onTrial: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(
                "相机 ${snapshot.cameraId} · " + when (snapshot.facing) {
                    "front" -> "前摄"
                    "back" -> "后摄"
                    else -> "外接"
                } + " · ${snapshot.hardwareLevel}",
                style = MaterialTheme.typography.titleMedium,
            )
            val tier = ControlClassifier.hardwareTier(snapshot)
            Text("硬件能力档：$tier（仅本相机实测，不由其他相机推断）", style = MaterialTheme.typography.bodySmall)
            Text("YUV 尺寸 ${snapshot.yuvSizes.size} 种；时间戳源 ${snapshot.timestampSource}", style = MaterialTheme.typography.bodySmall)
            Button(onClick = onTrial, enabled = busy == null) { Text("试开相机流") }
            when {
                trial == null -> Text("未试开。", style = MaterialTheme.typography.bodySmall)
                trial.error != null -> Text("试开失败：${trial.error}", style = MaterialTheme.typography.bodySmall)
                else -> {
                    val observed = ControlClassifier.observedClass(snapshot, trial)
                    Text(
                        "实测档位：${observed?.controlClass ?: "未定"}（帧 ${trial.frames.size}，" +
                            "${trial.widthPx}x${trial.heightPx}@${trial.targetFps}fps，模式 ${trial.request.mode}）",
                        style = MaterialTheme.typography.bodySmall,
                    )
                    observed?.reasons?.forEach {
                        Text("· $it", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
    }
}

/** 根据相机能力选择试开模式并夹紧请求参数。 */
private fun runTrial(context: Context, snapshot: CameraSnapshot): TrialResult {
    val candidate = StreamPlanner.candidates(snapshot.yuvSizes, snapshot.fpsRanges).firstOrNull()
        ?: return TrialResult(
            cameraId = snapshot.cameraId,
            widthPx = 0,
            heightPx = 0,
            targetFps = 0,
            request = org.mirrorchecker.probe.TrialRequest("auto", null, null),
            frames = emptyList(),
            error = "没有可用的常规宽高比 YUV 输出尺寸",
        )
    val manual = snapshot.hasManualSensor && snapshot.aeOffAvailable &&
        snapshot.exposureTimeRangeNs != null && snapshot.sensitivityRangeIso != null
    val mode = when {
        manual -> "manual"
        snapshot.aeLockAvailable -> "ae_lock"
        else -> "auto"
    }
    val config = CameraTrialRunner.Config(
        widthPx = candidate.size.widthPx,
        heightPx = candidate.size.heightPx,
        targetFps = candidate.targetFps,
        fpsRange = candidate.fpsRange,
        mode = mode,
        requestedExposureTimeNs = snapshot.exposureTimeRangeNs?.let { 10_000_000L.coerceIn(it.first, it.last) },
        requestedSensitivityIso = snapshot.sensitivityRangeIso?.let { 100.coerceIn(it.first, it.last) },
    )
    return CameraTrialRunner(context).run(snapshot.cameraId, config)
}

private fun buildReport(
    context: Context,
    snapshots: List<CameraSnapshot>,
    trials: Map<String, TrialResult>,
): ProbeReport {
    val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    val versionName = runCatching {
        context.packageManager.getPackageInfo(context.packageName, 0).versionName
    }.getOrNull() ?: "unknown"
    val activity = context as? Activity
    return ProbeReport(
        deviceId = ProbeReport.deriveDeviceId(Build.FINGERPRINT),
        manufacturer = Build.MANUFACTURER,
        model = Build.MODEL,
        androidRelease = Build.VERSION.RELEASE,
        androidSdkInt = Build.VERSION.SDK_INT,
        cameras = snapshots.map { snapshot ->
            CameraReport(
                snapshot = snapshot,
                streamCandidates = StreamPlanner.candidates(snapshot.yuvSizes, snapshot.fpsRanges),
                trial = trials[snapshot.cameraId],
            )
        },
        display = activity?.let { DisplayProbe.current(it) }
            ?: DisplaySnapshotFallback.current(context),
        previewMirroring = PreviewMirroring(previewMirrored = true),
        sensors = SensorSummary(
            gyroscope = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE) != null,
            accelerometer = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER) != null,
        ),
        generatedAtUtcIso = Instant.now().toString(),
        appVersion = versionName,
    )
}

/** 无 Activity 上下文时的兜底（正常路径都用 Activity 的真实显示状态）。 */
private object DisplaySnapshotFallback {
    fun current(context: Context): org.mirrorchecker.probe.DisplaySnapshot {
        val metrics = context.resources.displayMetrics
        return org.mirrorchecker.probe.DisplaySnapshot(
            surfaceWidthPx = metrics.widthPixels,
            surfaceHeightPx = metrics.heightPixels,
            rotationDeg = 0,
            naturalOrientation = "landscape",
            refreshRateHz = 60.0,
        )
    }
}

// ---------------------------------------------------------------------------
// 诊断图案
// ---------------------------------------------------------------------------

@Composable
fun PatternScreen(activity: MainActivity, onExit: () -> Unit) {
    var fullscreen by remember { mutableStateOf(false) }
    var patternIndex by remember { mutableStateOf(0) }
    var cycles by remember { mutableStateOf(8f) }
    val patterns = remember { DiagnosticPattern.builtIn() }

    if (fullscreen) {
        FullscreenPattern(
            activity = activity,
            pattern = customFringe(patterns, patternIndex, cycles),
            onExitFullscreen = { fullscreen = false },
        )
        return
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Text("诊断图案", style = MaterialTheme.typography.titleLarge)
            Text(
                "图案按当前 Surface 像素 1:1 渲染（无缩放/滤波）；全屏显示时隐藏系统栏。" +
                    "旋转或分屏后返回会按新尺寸重新渲染并生成新的 Surface 指纹。",
                style = MaterialTheme.typography.bodySmall,
            )
            OutlinedButton(onClick = onExit) { Text("返回探测") }
        }
        items(patterns.size) { index ->
            val name = patterns[index].patternId
            Button(
                onClick = { patternIndex = index },
                modifier = Modifier.fillMaxWidth(),
            ) { Text(if (index == patternIndex) "▶ $name（选中）" else name) }
        }
        item {
            Text("条纹周期数：${cycles.toInt()}", style = MaterialTheme.typography.bodyMedium)
            Slider(
                value = cycles,
                onValueChange = { cycles = it },
                valueRange = 1f..16f,
                steps = 14,
            )
            Button(onClick = { fullscreen = true }, modifier = Modifier.fillMaxWidth()) {
                Text("全屏显示（点按屏幕退出）")
            }
            Text(
                "低频条纹用于观察摩尔纹、混帧与离焦；灰阶用于响应粗查。" +
                    "这些是诊断工具，不构成定量测量（§5.1）。",
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

/** 条纹图案实时替换周期数；黑白/灰阶保持内置定义。 */
private fun customFringe(patterns: List<DiagnosticPattern>, index: Int, cycles: Float): DiagnosticPattern {
    val base = patterns[index]
    return if (base.kind == PatternKind.FRINGE) {
        base.copy(cycles = cycles.toInt().coerceAtLeast(1))
    } else {
        base
    }
}

@Composable
private fun FullscreenPattern(
    activity: MainActivity,
    pattern: DiagnosticPattern,
    onExitFullscreen: () -> Unit,
) {
    DisposableEffect(Unit) {
        val window = activity.window
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val controller = WindowCompat.getInsetsController(window, window.decorView)
        controller.systemBarsBehavior =
            WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        controller.hide(WindowInsetsCompat.Type.systemBars())
        onDispose {
            controller.show(WindowInsetsCompat.Type.systemBars())
            window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }
    androidx.compose.foundation.layout.Box(
        modifier = Modifier
            .fillMaxSize()
            .pointerInput(Unit) {
                detectTapGestures { onExitFullscreen() }
            },
    ) {
        AndroidView(
            factory = { context -> PatternView(context) },
            update = { view -> view.pattern = pattern },
        )
    }
}
