package org.mirrorchecker.app

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.view.SurfaceHolder
import android.view.SurfaceView
import org.mirrorchecker.probe.DiagnosticPattern
import org.mirrorchecker.probe.PatternRenderer

/**
 * 像素确定的全屏图案渲染（PR-03 验收：渲染坐标与参考图一致）。
 *
 * 渲染规则：Surface 尺寸变化时用 :probe 的 [PatternRenderer] 重新生成整幅亮度，
 * 逐字节转 ARGB 后 1:1 写入位图，drawBitmap 传 null Paint（无滤波）且不做缩放。
 * 不在此处做任何旋转/镜像——图案定义就是当前 Surface 像素坐标（§3.3）。
 */
class PatternView(context: Context) : SurfaceView(context), SurfaceHolder.Callback {

    var pattern: DiagnosticPattern = DiagnosticPattern.builtIn().first()
        set(value) {
            field = value
            renderIfReady()
        }

    /** 最近一次实际渲染的 Surface 尺寸与图案，用于核对渲染状态。 */
    var lastRenderedWidthPx: Int = 0
        private set
    var lastRenderedHeightPx: Int = 0
        private set
    var lastRenderedPatternId: String = ""
        private set

    init {
        holder.addCallback(this)
    }

    override fun surfaceCreated(holder: SurfaceHolder) = Unit

    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
        render(width, height)
    }

    override fun surfaceDestroyed(holder: SurfaceHolder) = Unit

    private fun renderIfReady() {
        val (width, height) = holder.surfaceFrame.let { it.width() to it.height() }
        if (width > 0 && height > 0) render(width, height)
    }

    private fun render(width: Int, height: Int) {
        if (holder.surface == null || !holder.surface.isValid) return
        val luminance = PatternRenderer.renderRowMajor(pattern, width, height)
        val pixels = IntArray(luminance.size) { index ->
            val v = luminance[index].toInt() and 0xFF
            Color.rgb(v, v, v)
        }
        val bitmap = Bitmap.createBitmap(pixels, width, height, Bitmap.Config.ARGB_8888)
        val canvas: Canvas = holder.lockCanvas() ?: return
        try {
            // 1:1 绘制：位图尺寸即 Surface 尺寸，无缩放、无滤波
            canvas.drawBitmap(bitmap, 0f, 0f, null)
        } finally {
            holder.unlockCanvasAndPost(canvas)
        }
        lastRenderedWidthPx = width
        lastRenderedHeightPx = height
        lastRenderedPatternId = pattern.patternId
    }
}
