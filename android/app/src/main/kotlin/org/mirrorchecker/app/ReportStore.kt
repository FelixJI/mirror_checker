package org.mirrorchecker.app

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import org.mirrorchecker.probe.ProbeReport
import java.io.File
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * 能力报告落盘与分享（H03 人工证据的导出通道）。
 *
 * 保存两份文件：人可读的缩进 JSON 与其规范 JSON 的 SHA-256 校验行；
 * 分享经 FileProvider 授权，不申请存储权限。缩进仅为阅读方便，
 * 完整性以 sidecar 记录的规范 JSON 哈希（与仓库 JsonUtil 口径一致）为准。
 */
object ReportStore {

    private val FILE_STAMP: DateTimeFormatter =
        DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss").withZone(ZoneOffset.UTC)

    fun save(context: Context, report: ProbeReport): File {
        val dir = File(context.filesDir, "reports").apply { mkdirs() }
        val stamp = FILE_STAMP.format(Instant.now())
        val file = File(dir, "capability_report_$stamp.json")
        file.writeText(prettyPrint(report.toJson()), Charsets.UTF_8)
        File(dir, file.name + ".sha256").writeText(report.canonicalSha256() + "\n", Charsets.UTF_8)
        return file
    }

    fun share(context: Context, file: File) {
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "application/json"
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(Intent.createChooser(intent, "分享能力报告"))
    }

    /** 两空格缩进的简易打印器（不参与任何哈希/契约，仅供人阅读）。 */
    internal fun prettyPrint(element: JsonElement, indent: String = ""): String = buildString {
        when (element) {
            is JsonObject -> {
                if (element.isEmpty()) {
                    append("{}")
                    return@buildString
                }
                append("{\n")
                element.keys.sorted().forEachIndexed { index, key ->
                    if (index > 0) append(",\n")
                    append(indent).append("  ").append(kotlinx.serialization.json.JsonPrimitive(key))
                        .append(": ")
                        .append(prettyPrint(element.getValue(key), "$indent  "))
                }
                append('\n').append(indent).append('}')
            }
            is JsonArray -> {
                if (element.isEmpty()) {
                    append("[]")
                    return@buildString
                }
                append("[\n")
                element.forEachIndexed { index, item ->
                    if (index > 0) append(",\n")
                    append(indent).append("  ").append(prettyPrint(item, "$indent  "))
                }
                append('\n').append(indent).append(']')
            }
            else -> append(element.toString())
        }
    }
}
