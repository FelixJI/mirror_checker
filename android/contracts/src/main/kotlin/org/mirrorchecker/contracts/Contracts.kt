package org.mirrorchecker.contracts

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive

/** 契约违规。消息以“包内路径: 字段路径”开头，与 Python 端 mirror_core 一致。 */
class ContractException(message: String) : RuntimeException(message)

/** 共同契约常量与基础校验，对应 python/mirror_core/contracts.py。 */
object Contracts {
    const val SCHEMA_VERSION = "1.0.0"
    const val PACKAGE_KIND_CAPTURE_SESSION = "capture_session"
    const val TRANSFORM_CONVENTION = "T_A_B"
    const val UNIT_LENGTH = "m"
    const val UNIT_ANGLE = "rad"

    val CAPTURE_STATUSES = setOf("collecting", "complete", "aborted")
    val TRANSFER_STATUSES = setOf("local_only", "transferring", "verified")
    val PROVENANCES = setOf("synthetic", "device")
    val FRAME_FORMATS = setOf("raw8")
    val TIMESTAMP_SOURCES = setOf("REALTIME", "UNKNOWN")

    const val SESSION_MANIFEST_NAME = "session.json"
    const val DEVICE_PATH = "device.json"
    const val CALIBRATION_INDEX_PATH = "calibration/index.json"
    const val LAYOUT_PATH = "layout.json"
    const val RECIPE_PATH = "recipe.json"
    const val EXPERIMENT_PATH = "experiment.json"

    private val FRAME_ID = Regex("^[A-Z][A-Z0-9_]*$")
    private val SHA256 = Regex("^[0-9a-f]{64}$")
    private val NS_TIMESTAMP = Regex("^(0|[1-9][0-9]*)$")
    private val PATTERN_ID = Regex("^[A-Za-z0-9][A-Za-z0-9._-]*$")

    fun checkSchemaVersion(obj: JsonObject, where: String): String {
        val value = obj.requireString("schema_version", where)
        if (value != SCHEMA_VERSION) {
            throw ContractException(
                "$where: 不支持的 schema_version=$value（当前契约版本为 $SCHEMA_VERSION；" +
                    "主版本或未知版本必须显式报错，不得静默解析）"
            )
        }
        return value
    }

    fun checkEnum(value: String?, allowed: Set<String>, field: String, where: String): String {
        if (value == null || value !in allowed) {
            throw ContractException("$where: $field=$value 不在允许集合 (${allowed.sorted().joinToString("/")}) 内")
        }
        return value
    }

    fun checkNsTimestamp(value: JsonElement?, field: String, where: String): String {
        val text = value?.let { runCatching { it.jsonPrimitive.content }.getOrNull() }
        if (text == null || !NS_TIMESTAMP.matches(text)) {
            throw ContractException(
                "$where: $field 必须是十进制数字字符串（纳秒），实际为 $text；" +
                    "JSON 数值形式的纳秒时间戳会有精度损失，契约不允许"
            )
        }
        return text
    }

    fun isPatternId(value: String?): Boolean = value != null && PATTERN_ID.matches(value)
    fun isSha256(value: String?): Boolean = value != null && SHA256.matches(value)
    fun isFrameId(value: String?): Boolean = value != null && FRAME_ID.matches(value)
}

/** JsonObject 取值辅助：类型不符时抛出带定位的 ContractException。 */
fun JsonObject.requireObject(key: String, where: String): JsonObject {
    val value = this[key] as? JsonObject
        ?: throw ContractException("$where: 缺少必需字段 $key 或其类型不是对象")
    return value
}

fun JsonObject.requireArray(key: String, where: String): kotlinx.serialization.json.JsonArray {
    val value = this[key] as? kotlinx.serialization.json.JsonArray
        ?: throw ContractException("$where: 缺少必需字段 $key 或其类型不是数组")
    return value
}

fun JsonObject.requireString(key: String, where: String): String {
    val value = this[key]
    if (value == null || value is kotlinx.serialization.json.JsonNull) {
        throw ContractException("$where: 缺少必需字段 $key")
    }
    val primitive = value as? kotlinx.serialization.json.JsonPrimitive
        ?: throw ContractException("$where: $key 必须是字符串")
    if (!primitive.isString) {
        throw ContractException("$where: $key 必须是字符串，实际为 ${primitive.content}")
    }
    if (primitive.content.isEmpty()) {
        throw ContractException("$where: $key 必须是非空字符串")
    }
    return primitive.content
}

fun JsonObject.requireInt(key: String, where: String): Int {
    val value = this[key] as? kotlinx.serialization.json.JsonPrimitive
        ?: throw ContractException("$where: 缺少必需字段 $key")
    val content = value.content
    val parsed = content.toIntOrNull()
    if (parsed == null || value.isString) {
        throw ContractException("$where: $key 必须是整数，实际为 $content")
    }
    return parsed
}

fun JsonObject.requirePositiveInt(key: String, where: String): Int {
    val value = requireInt(key, where)
    if (value <= 0) throw ContractException("$where: $key=$value 必须为正")
    return value
}

fun JsonObject.requireNumber(key: String, where: String): Double {
    val value = this[key] as? kotlinx.serialization.json.JsonPrimitive
        ?: throw ContractException("$where: 缺少必需字段 $key")
    val parsed = value.content.toDoubleOrNull()
    if (parsed == null || value.isString) {
        throw ContractException("$where: $key 必须是数值，实际为 ${value.content}")
    }
    if (parsed.isNaN() || parsed.isInfinite()) {
        throw ContractException("$where: $key 必须是有限数值，实际为 $parsed")
    }
    return parsed
}

fun JsonObject.optObject(key: String): JsonObject? = this[key] as? JsonObject
