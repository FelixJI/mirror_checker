package org.mirrorchecker.app

import android.app.Activity
import android.content.res.Configuration
import android.os.Build
import android.provider.Settings
import android.util.DisplayMetrics
import org.mirrorchecker.probe.DisplaySnapshot
import org.mirrorchecker.probe.RectPx

/**
 * 采集显示/Surface 状态（PR-03：方向和 Surface 记录）。
 *
 * - Surface 尺寸取真实显示指标（含系统栏区域），这是全屏图案渲染可用的缓冲大小；
 * - 自然方向由「旋转角 + 当前配置方向」推断，不把 ROTATION_0 固定解释为竖屏（§3.3）；
 * - 遮挡区记录 API 28+ 的开孔边界；读不到时保留空列表并在报告中如实呈现。
 */
object DisplayProbe {

    @Suppress("DEPRECATION")
    fun current(activity: Activity): DisplaySnapshot {
        val display = activity.windowManager.defaultDisplay
        val metrics = DisplayMetrics()
        display.getRealMetrics(metrics)
        val rotationDeg = display.rotation * 90

        val configuration = activity.resources.configuration
        val naturalOrientation = when (rotationDeg) {
            0, 180 -> if (configuration.orientation == Configuration.ORIENTATION_LANDSCAPE) "landscape" else "portrait"
            90, 270 -> if (configuration.orientation == Configuration.ORIENTATION_PORTRAIT) "landscape" else "portrait"
            else -> "landscape"
        }

        val brightnessMode = runCatching {
            when (Settings.System.getInt(activity.contentResolver, Settings.System.SCREEN_BRIGHTNESS_MODE)) {
                Settings.System.SCREEN_BRIGHTNESS_MODE_AUTOMATIC -> "automatic"
                else -> "manual"
            }
        }.getOrNull()
        val brightnessValue = runCatching {
            val raw = Settings.System.getFloat(activity.contentResolver, Settings.System.SCREEN_BRIGHTNESS)
            (raw / 255.0).coerceIn(0.0, 1.0)
        }.getOrNull()

        return DisplaySnapshot(
            surfaceWidthPx = metrics.widthPixels,
            surfaceHeightPx = metrics.heightPixels,
            rotationDeg = rotationDeg,
            naturalOrientation = naturalOrientation,
            refreshRateHz = display.refreshRate.toDouble(),
            brightnessMode = brightnessMode,
            brightnessValue = brightnessValue,
            occlusionsPx = occlusions(activity),
        )
    }

    /** 记录但不下结论：取不到时为空列表，代表「本次未能读取遮挡信息」。 */
    private fun occlusions(activity: Activity): List<RectPx> {
        if (Build.VERSION.SDK_INT < 28) return emptyList()
        val insets = activity.window?.decorView?.rootWindowInsets ?: return emptyList()
        val cutout = insets.displayCutout ?: return emptyList()
        return cutout.boundingRects.map { RectPx(it.left, it.top, it.width(), it.height()) }
    }
}
