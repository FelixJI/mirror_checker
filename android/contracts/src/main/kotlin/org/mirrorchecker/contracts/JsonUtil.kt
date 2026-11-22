package org.mirrorchecker.contracts

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.security.MessageDigest

/**
 * 规范 JSON 序列化与哈希，与 python/mirror_core/canonical.py 字节级一致：
 * UTF-8、键按码点升序、分隔符 `,` `:`、无空白、数值保留源文本、无 NaN/Infinity。
 */
object JsonUtil {
    fun canonicalJson(element: JsonElement): String = buildString { writeCanonical(element) }

    fun canonicalSha256(element: JsonElement): String = sha256Hex(canonicalJson(element).encodeToByteArray())

    /** 除 excludeKey 外全部字段的规范哈希（用于自引用哈希字段）。 */
    fun canonicalSha256Excluding(obj: JsonObject, excludeKey: String): String {
        val core = JsonObject(obj.filterKeys { it != excludeKey })
        return canonicalSha256(core)
    }

    fun sha256Hex(data: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(data).joinToString("") { "%02x".format(it) }

    private fun StringBuilder.writeCanonical(element: JsonElement) {
        when (element) {
            is JsonObject -> {
                append('{')
                element.keys.sorted().forEachIndexed { index, key ->
                    if (index > 0) append(',')
                    appendQuote(key)
                    append(':')
                    writeCanonical(element[key] ?: JsonNull)
                }
                append('}')
            }
            is JsonArray -> {
                append('[')
                element.forEachIndexed { index, item ->
                    if (index > 0) append(',')
                    writeCanonical(item)
                }
                append(']')
            }
            is JsonPrimitive -> {
                if (element.isString) appendQuote(element.content) else append(element.content)
            }
            is JsonNull -> append("null")
        }
    }

    /** 与 Python json.dumps(ensure_ascii=False) 一致的字符串转义。 */
    private fun StringBuilder.appendQuote(value: String) {
        append('"')
        for (ch in value) {
            when (ch) {
                '"' -> append("\\\"")
                '\\' -> append("\\\\")
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                '\b' -> append("\\b")
                '' -> append("\\f")
                else -> if (ch < ' ') append("\\u%04x".format(ch.code)) else append(ch)
            }
        }
        append('"')
    }
}
