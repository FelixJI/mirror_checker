package org.mirrorchecker.contracts

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull

/**
 * 三维坐标变换 T_to_from：把 fromFrame 坐标变换到 toFrame。
 * JSON 表示与语义见 docs/contracts/README.md 第 3 节：
 * rotation 为 3x3 行主序矩阵，translationM 单位米。
 */
data class Transform(
    val fromFrame: String,
    val toFrame: String,
    val rotation: Array<DoubleArray>,
    val translationM: DoubleArray,
) {
    companion object {
        fun fromMapping(element: kotlinx.serialization.json.JsonElement?, where: String): Transform {
            val mapping = element as? JsonObject
                ?: throw ContractException("$where: 变换必须是对象")
            for (key in listOf("from_frame", "to_frame", "rotation", "translation_m", "convention")) {
                if (mapping[key] == null) {
                    throw ContractException("$where: 变换缺少必需字段 $key")
                }
            }
            val convention = (mapping["convention"] as? JsonPrimitive)?.takeIf { it.isString }?.content
            if (convention != Contracts.TRANSFORM_CONVENTION) {
                throw ContractException(
                    "$where: convention=$convention 不被支持（契约只允许 ${Contracts.TRANSFORM_CONVENTION}，" +
                        "即 from_frame 坐标变换到 to_frame）"
                )
            }
            val fromFrame = (mapping["from_frame"] as? JsonPrimitive)?.takeIf { it.isString }?.content
            val toFrame = (mapping["to_frame"] as? JsonPrimitive)?.takeIf { it.isString }?.content
            if (fromFrame == null || !Contracts.isFrameId(fromFrame)) {
                throw ContractException("$where: from_frame=$fromFrame 不是合法坐标系标识（大写字母开头的 [A-Z0-9_]）")
            }
            if (toFrame == null || !Contracts.isFrameId(toFrame)) {
                throw ContractException("$where: to_frame=$toFrame 不是合法坐标系标识（大写字母开头的 [A-Z0-9_]）")
            }
            val rotation = parseMatrix(mapping["rotation"], "$where: rotation")
            val translation = parseVector(mapping["translation_m"], "$where: translation_m")
            return Transform(fromFrame, toFrame, rotation, translation)
        }

        private fun parseMatrix(element: kotlinx.serialization.json.JsonElement?, where: String): Array<DoubleArray> {
            val rows = element as? JsonArray
                ?: throw ContractException("$where: 变换维度错误——rotation 必须是 3x3 数值矩阵（行主序）")
            if (rows.size != 3) {
                throw ContractException("$where: 变换维度错误——rotation 行数为 ${rows.size}，必须为 3")
            }
            return Array(3) { i -> parseRow(rows[i], "$where[$i]") }
        }

        private fun parseRow(element: kotlinx.serialization.json.JsonElement, where: String): DoubleArray {
            val row = element as? JsonArray
                ?: throw ContractException("$where: 变换维度错误——矩阵每行必须有 3 个数值")
            if (row.size != 3) {
                throw ContractException("$where: 变换维度错误——矩阵每行必须有 3 个数值，实际为 ${row.size} 个")
            }
            val values = DoubleArray(3)
            for (j in 0 until 3) {
                val primitive = row[j] as? JsonPrimitive
                    ?: throw ContractException("$where[$j]: 矩阵元素必须是数值")
                val value = primitive.doubleOrNull
                if (value == null || primitive.isString) {
                    throw ContractException("$where[$j]: 矩阵元素必须是数值，实际为 ${primitive.content}")
                }
                if (value.isNaN() || value.isInfinite()) {
                    throw ContractException("$where[$j]: 矩阵元素必须是有限数值，实际为 $value")
                }
                values[j] = value
            }
            return values
        }

        private fun parseVector(element: kotlinx.serialization.json.JsonElement?, where: String): DoubleArray {
            val list = element as? JsonArray
                ?: throw ContractException("$where: 变换维度错误——平移向量必须有 3 个分量（单位米）")
            if (list.size != 3) {
                throw ContractException("$where: 变换维度错误——平移向量必须有 3 个分量，实际为 ${list.size} 个")
            }
            val values = DoubleArray(3)
            for (i in 0 until 3) {
                val primitive = list[i] as? JsonPrimitive
                    ?: throw ContractException("$where[$i]: 平移分量必须是数值")
                val value = primitive.doubleOrNull
                if (value == null || primitive.isString) {
                    throw ContractException("$where[$i]: 平移分量必须是数值，实际为 ${primitive.content}")
                }
                if (value.isNaN() || value.isInfinite()) {
                    throw ContractException("$where[$i]: 平移分量必须是有限数值，实际为 $value")
                }
                values[i] = value
            }
            return values
        }
    }

    /** 把 fromFrame 中的点变换到 toFrame。 */
    fun applyPoint(x: Double, y: Double, z: Double): DoubleArray {
        val p = doubleArrayOf(x, y, z)
        return DoubleArray(3) { i ->
            var acc = 0.0
            for (j in 0 until 3) acc += rotation[i][j] * p[j]
            acc + translationM[i]
        }
    }
}
