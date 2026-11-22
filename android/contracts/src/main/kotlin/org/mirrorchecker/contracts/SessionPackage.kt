package org.mirrorchecker.contracts

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.util.zip.ZipInputStream

/**
 * 离线会话包（自包含 ZIP）的解析与契约校验，对应 python/mirror_core/session.py。
 *
 * 与 Python 端强制同一套规则：缺帧、未知单位、变换维度错误、标定/配置不匹配
 * 都必须抛出 [ContractException] 并给出可定位的消息（PR-01 验收项）。
 * 范例数据由两端共用同一份 ZIP（tests/fixtures/synthetic_session_v1.zip）。
 */
class SessionPackage private constructor(
    val path: File,
    private val session: JsonObject,
    val attemptCount: Int,
    val totalFrames: Int,
) {
    val schemaVersion: String = session.requireString("schema_version", Contracts.SESSION_MANIFEST_NAME)
    val sessionId: String = session.requireString("session_id", Contracts.SESSION_MANIFEST_NAME)
    val provenance: String = session.requireString("provenance", Contracts.SESSION_MANIFEST_NAME)
    val captureStatus: String = session.requireString("capture_status", Contracts.SESSION_MANIFEST_NAME)
    val manifestFileCount: Int = session.requireArray("files", Contracts.SESSION_MANIFEST_NAME).size

    companion object {
        fun open(file: File): SessionPackage {
            val entries = readZipEntries(file)
            val sessionBytes = entries[Contracts.SESSION_MANIFEST_NAME]
                ?: throw ContractException("$file: 会话缺少 ${Contracts.SESSION_MANIFEST_NAME}")
            val session = parseJson(sessionBytes, Contracts.SESSION_MANIFEST_NAME)
            val result = validate(session, entries, file)
            return SessionPackage(file, session, result.attemptCount, result.totalFrames)
        }

        private class ValidationResult(val attemptCount: Int, val totalFrames: Int)

        private fun readZipEntries(file: File): Map<String, ByteArray> {
            val entries = LinkedHashMap<String, ByteArray>()
            ZipInputStream(file.inputStream().buffered()).use { stream ->
                while (true) {
                    val entry = stream.nextEntry ?: break
                    if (entry.isDirectory) {
                        throw ContractException("$file: 不支持目录条目 ${entry.name}（清单只登记文件）")
                    }
                    if (entries.containsKey(entry.name)) {
                        throw ContractException("$file: ZIP 内存在重名条目 ${entry.name}")
                    }
                    entries[entry.name] = stream.readBytes()
                }
            }
            return entries
        }

        private fun parseJson(data: ByteArray, where: String): JsonObject {
            val element = try {
                Json.parseToJsonElement(data.decodeToString())
            } catch (exc: Exception) {
                throw ContractException("$where: JSON 解析失败（${exc.message}）")
            }
            return element as? JsonObject
                ?: throw ContractException("$where: 根节点必须是对象")
        }

        private fun requireEntry(entries: Map<String, ByteArray>, path: String): ByteArray =
            entries[path] ?: throw ContractException("$path: 契约要求的文件不在包内")

        // ------------------------------------------------------------------
        // 校验（与 python/mirror_core/session.py 相同的顺序与规则）
        // ------------------------------------------------------------------

        private fun validate(session: JsonObject, entries: Map<String, ByteArray>, file: File): ValidationResult {
            validateHeader(session)
            validateManifest(session, entries)
            val device = validateDevice(session, entries)
            val recipe = validateRecipe(session, entries, device)
            val calibrationId = validateCalibration(session, entries, device)
            validateLayout(entries)
            validateExperiment(entries)

            val expectedSequence = expectedPatternSequence(recipe)
            val stream = device.requireObject("camera", Contracts.DEVICE_PATH)
                .requireObject("stream", "device.json: camera")
            val streamW = stream.requirePositiveInt("width_px", "device.json: camera.stream")
            val streamH = stream.requirePositiveInt("height_px", "device.json: camera.stream")
            val attempts = validatePatches(
                session, entries, recipe, calibrationId, device,
                expectedSequence, streamW, streamH,
            )
            validateCompletion(session, attempts)

            val totalFrames = attempts.sumOf { it.second.requireArray("frames", it.first).size }
            return ValidationResult(attempts.size, totalFrames)
        }

        private fun validateHeader(session: JsonObject) {
            val where = Contracts.SESSION_MANIFEST_NAME
            Contracts.checkSchemaVersion(session, where)
            if (session.requireString("package_kind", where) != Contracts.PACKAGE_KIND_CAPTURE_SESSION) {
                throw ContractException(
                    "$where: package_kind 不被支持（本契约只描述 ${Contracts.PACKAGE_KIND_CAPTURE_SESSION}）"
                )
            }
            Contracts.checkEnum(session["provenance"]?.jsonPrimitive?.contentOrNull, Contracts.PROVENANCES, "provenance", where)
            Contracts.checkEnum(session["capture_status"]?.jsonPrimitive?.contentOrNull, Contracts.CAPTURE_STATUSES, "capture_status", where)
            Contracts.checkEnum(session["transfer_status"]?.jsonPrimitive?.contentOrNull, Contracts.TRANSFER_STATUSES, "transfer_status", where)

            val units = session.requireObject("units", where)
            if (units["length"]?.jsonPrimitive?.contentOrNull != Contracts.UNIT_LENGTH) {
                throw ContractException(
                    "$where: units.length: 未知长度单位 ${units["length"]}（契约只允许 '${Contracts.UNIT_LENGTH}'，米）"
                )
            }
            if (units["angle"]?.jsonPrimitive?.contentOrNull != Contracts.UNIT_ANGLE) {
                throw ContractException(
                    "$where: units.angle: 未知角度单位 ${units["angle"]}（契约只允许 '${Contracts.UNIT_ANGLE}'，弧度）"
                )
            }

            val conv = session.requireObject("coordinate_conventions", where)
            if (conv["transform"]?.jsonPrimitive?.contentOrNull != Contracts.TRANSFORM_CONVENTION) {
                throw ContractException(
                    "$where: coordinate_conventions.transform: 变换方向约定错误，必须声明为 '${Contracts.TRANSFORM_CONVENTION}'" +
                        "（from_frame 坐标变换到 to_frame）"
                )
            }
            for (key in listOf("image_coordinates", "screen_coordinates", "mirror_frame")) {
                conv[key]?.jsonPrimitive?.contentOrNull
                    ?: throw ContractException("$where: coordinate_conventions.$key 必须是非空字符串说明")
            }
        }

        private fun validateManifest(session: JsonObject, entries: Map<String, ByteArray>) {
            val where = "${Contracts.SESSION_MANIFEST_NAME}: files"
            val files = session.requireArray("files", Contracts.SESSION_MANIFEST_NAME)
            val manifest = LinkedHashMap<String, JsonObject>()
            files.forEachIndexed { i, element ->
                val entryWhere = "$where[$i]"
                val entry = element as? JsonObject
                    ?: throw ContractException("$entryWhere: 必须是对象")
                val path = entry.requireString("path", entryWhere)
                if (path == Contracts.SESSION_MANIFEST_NAME) {
                    throw ContractException("$entryWhere: 清单不得登记 ${Contracts.SESSION_MANIFEST_NAME} 自身")
                }
                if (manifest.containsKey(path)) {
                    throw ContractException("$entryWhere: 清单重复登记 $path")
                }
                val sha = entry.requireString("sha256", entryWhere)
                if (!Contracts.isSha256(sha)) {
                    throw ContractException("$entryWhere: sha256 必须是 64 位小写十六进制 SHA-256 字符串")
                }
                entry.requireInt("size_bytes", entryWhere)
                manifest[path] = entry
            }

            val zipNames = entries.keys - Contracts.SESSION_MANIFEST_NAME
            val missing = (manifest.keys - zipNames).sorted()
            if (missing.isNotEmpty()) {
                throw ContractException("$where: 清单中的文件在包内不存在（缺文件/缺帧）: ${missing.take(3)}")
            }
            val extra = (zipNames - manifest.keys).sorted()
            if (extra.isNotEmpty()) {
                throw ContractException("$where: 包内存在未登记文件: ${extra.take(3)}")
            }

            for ((path, entry) in manifest) {
                val data = entries.getValue(path)
                val size = entry.requireInt("size_bytes", path)
                if (data.size != size) {
                    throw ContractException("$path: 文件大小与清单不一致（清单 $size 字节，实际 ${data.size} 字节）")
                }
                val actual = JsonUtil.sha256Hex(data)
                if (actual != entry.requireString("sha256", path)) {
                    throw ContractException("$path: 文件 SHA-256 与清单不一致")
                }
            }
        }

        private fun validateDevice(session: JsonObject, entries: Map<String, ByteArray>): JsonObject {
            val ref = session.requireObject("device", Contracts.SESSION_MANIFEST_NAME)
            if (ref.requireString("path", "session.json: device") != Contracts.DEVICE_PATH) {
                throw ContractException("${Contracts.SESSION_MANIFEST_NAME}: device.path 必须是 '${Contracts.DEVICE_PATH}'")
            }
            val device = parseJson(requireEntry(entries, Contracts.DEVICE_PATH), Contracts.DEVICE_PATH)
            Contracts.checkSchemaVersion(device, Contracts.DEVICE_PATH)
            device.requireString("device_id", Contracts.DEVICE_PATH)

            val config = device.requireObject("device_config", Contracts.DEVICE_PATH)
            val recomputed = JsonUtil.canonicalSha256(config)
            val registered = device.requireString("device_config_hash", Contracts.DEVICE_PATH)
            if (registered != recomputed) {
                throw ContractException(
                    "${Contracts.DEVICE_PATH}: device_config_hash 与 device_config 内容不匹配（配置不匹配；" +
                        "登记 $registered，实际 $recomputed）"
                )
            }
            if (ref.requireString("config_hash", "session.json: device") != registered) {
                throw ContractException(
                    "${Contracts.SESSION_MANIFEST_NAME}: device.config_hash 与 ${Contracts.DEVICE_PATH} 的 device_config_hash 不一致（配置不匹配）"
                )
            }

            val camera = device.requireObject("camera", Contracts.DEVICE_PATH)
            val stream = camera.requireObject("stream", "device.json: camera")
            stream.requirePositiveInt("width_px", "device.json: camera.stream")
            stream.requirePositiveInt("height_px", "device.json: camera.stream")
            device.requireObject("display", Contracts.DEVICE_PATH)
                .requireObject("effective_luminous", "device.json: display")
                .requireNumber("width_m", "device.json: display.effective_luminous")
            return device
        }

        private fun validateRecipe(
            session: JsonObject,
            entries: Map<String, ByteArray>,
            device: JsonObject,
        ): JsonObject {
            val ref = session.requireObject("recipe", Contracts.SESSION_MANIFEST_NAME)
            if (ref.requireString("path", "session.json: recipe") != Contracts.RECIPE_PATH) {
                throw ContractException("${Contracts.SESSION_MANIFEST_NAME}: recipe.path 必须是 '${Contracts.RECIPE_PATH}'")
            }
            val recipe = parseJson(requireEntry(entries, Contracts.RECIPE_PATH), Contracts.RECIPE_PATH)
            Contracts.checkSchemaVersion(recipe, Contracts.RECIPE_PATH)
            recipe.requireString("recipe_id", Contracts.RECIPE_PATH)

            val registered = recipe.requireString("recipe_hash", Contracts.RECIPE_PATH)
            if (!Contracts.isSha256(registered)) {
                throw ContractException("${Contracts.RECIPE_PATH}: recipe_hash 必须是 64 位小写十六进制字符串")
            }
            val recomputed = JsonUtil.canonicalSha256Excluding(recipe, "recipe_hash")
            if (registered != recomputed) {
                throw ContractException(
                    "${Contracts.RECIPE_PATH}: recipe_hash 与配方内容不匹配（配置不匹配；" +
                        "登记 $registered，按当前内容计算为 $recomputed）"
                )
            }
            if (ref.requireString("recipe_hash", "session.json: recipe") != registered) {
                throw ContractException(
                    "${Contracts.SESSION_MANIFEST_NAME}: recipe.recipe_hash 与 ${Contracts.RECIPE_PATH} 的 recipe_hash 不一致（配置不匹配）"
                )
            }

            val patterns = recipe.requireArray("patterns", Contracts.RECIPE_PATH)
            if (patterns.isEmpty()) {
                throw ContractException("${Contracts.RECIPE_PATH}: patterns 必须是非空数组")
            }
            val seenIds = HashSet<String>()
            val seenOrders = HashSet<Int>()
            for ((i, element) in patterns.withIndex()) {
                val patternWhere = "${Contracts.RECIPE_PATH}: patterns[$i]"
                val pattern = element as? JsonObject
                    ?: throw ContractException("$patternWhere: 必须是对象")
                val patternId = pattern.requireString("pattern_id", patternWhere)
                if (!Contracts.isPatternId(patternId)) {
                    throw ContractException("$patternWhere: pattern_id 不是合法图案 ID")
                }
                if (!seenIds.add(patternId)) {
                    throw ContractException("$patternWhere: pattern_id=$patternId 重复")
                }
                val kind = pattern.requireString("kind", patternWhere)
                if (kind !in setOf("fringe", "gray", "mask", "white", "black")) {
                    throw ContractException("$patternWhere: kind=$kind 不在允许集合内")
                }
                val order = pattern.requireInt("display_order", patternWhere)
                if (!seenOrders.add(order)) {
                    throw ContractException("$patternWhere: display_order=$order 重复")
                }
                when (kind) {
                    "fringe" -> {
                        pattern.requireInt("direction_deg", patternWhere)
                        pattern.requireNumber("frequency_cycles_per_pattern", patternWhere)
                        pattern.requireNumber("phase_shift_rad", patternWhere)
                    }
                    "gray" -> pattern.requirePositiveInt("level", patternWhere)
                }
            }
            val repeats = recipe.requireInt("repeats", Contracts.RECIPE_PATH)
            if (repeats < 1) {
                throw ContractException("${Contracts.RECIPE_PATH}: repeats 必须是 >=1 的整数")
            }
            Contracts.checkNsTimestamp(
                recipe.requireObject("wait_strategy", Contracts.RECIPE_PATH)["timeout_ns"],
                "wait_strategy.timeout_ns",
                Contracts.RECIPE_PATH,
            )
            val applicableDev = recipe.requireString("applicable_device_config_hash", Contracts.RECIPE_PATH)
            if (applicableDev != device.requireString("device_config_hash", Contracts.DEVICE_PATH)) {
                throw ContractException(
                    "${Contracts.RECIPE_PATH}: applicable_device_config_hash 与本次 device_config_hash 不匹配（标定/配置不匹配）"
                )
            }
            return recipe
        }

        private fun expectedPatternSequence(recipe: JsonObject): List<String> {
            val patterns = recipe.requireArray("patterns", Contracts.RECIPE_PATH)
            val ordered = patterns
                .map { it as JsonObject }
                .sortedBy { it.requireInt("display_order", Contracts.RECIPE_PATH) }
            val repeats = recipe.requireInt("repeats", Contracts.RECIPE_PATH)
            return List(repeats) { ordered.map { it.requireString("pattern_id", Contracts.RECIPE_PATH) } }.flatten()
        }

        private fun validateCalibration(
            session: JsonObject,
            entries: Map<String, ByteArray>,
            device: JsonObject,
        ): String? {
            val ref = session["calibration"] as? JsonObject
                ?: throw ContractException(
                    "${Contracts.SESSION_MANIFEST_NAME}: calibration 必须是含 present 布尔值的对象；" +
                        "诊断采集可以显式 present=false，但必须声明"
                )
            val present = (ref["present"] as? JsonPrimitive)?.takeIf { !it.isString }
                ?.contentOrNull?.toBooleanStrict()
                ?: throw ContractException("${Contracts.SESSION_MANIFEST_NAME}: calibration.present 必须是布尔值")
            if (!present) return null

            if (ref.requireString("path", "session.json: calibration") != Contracts.CALIBRATION_INDEX_PATH) {
                throw ContractException("${Contracts.SESSION_MANIFEST_NAME}: calibration.path 必须是 '${Contracts.CALIBRATION_INDEX_PATH}'")
            }
            val index = parseJson(requireEntry(entries, Contracts.CALIBRATION_INDEX_PATH), Contracts.CALIBRATION_INDEX_PATH)
            Contracts.checkSchemaVersion(index, Contracts.CALIBRATION_INDEX_PATH)
            val calibrationId = index.requireString("calibration_id", Contracts.CALIBRATION_INDEX_PATH)
            val items = index.requireArray("items", Contracts.CALIBRATION_INDEX_PATH)
            for ((i, element) in items.withIndex()) {
                val itemWhere = "${Contracts.CALIBRATION_INDEX_PATH}: items[$i]"
                val item = element as? JsonObject
                    ?: throw ContractException("$itemWhere: 必须是对象")
                val file = item.requireString("file", itemWhere)
                val itemPath = "calibration/$file"
                if (itemPath !in entries) {
                    throw ContractException("$itemWhere: 标定条目文件 $itemPath 不在包内")
                }
                parseJson(entries.getValue(itemPath), itemPath)
            }
            val conditions = index.requireObject("applicable_conditions", Contracts.CALIBRATION_INDEX_PATH)
            if (conditions.requireString("device_config_hash", Contracts.CALIBRATION_INDEX_PATH) !=
                device.requireString("device_config_hash", Contracts.DEVICE_PATH)
            ) {
                throw ContractException(
                    "${Contracts.CALIBRATION_INDEX_PATH}: applicable_conditions.device_config_hash 与本次设备配置不匹配（标定/配置不匹配）"
                )
            }
            return calibrationId
        }

        private fun validateLayout(entries: Map<String, ByteArray>) {
            val layout = parseJson(requireEntry(entries, Contracts.LAYOUT_PATH), Contracts.LAYOUT_PATH)
            Contracts.checkSchemaVersion(layout, Contracts.LAYOUT_PATH)
            layout.requireString("layout_id", Contracts.LAYOUT_PATH)
            val strips = layout.requireArray("strips", Contracts.LAYOUT_PATH)
            if (strips.isEmpty()) {
                throw ContractException("${Contracts.LAYOUT_PATH}: strips 必须是非空数组")
            }
            for ((s, element) in strips.withIndex()) {
                val stripWhere = "${Contracts.LAYOUT_PATH}: strips[$s]"
                val strip = element as? JsonObject
                    ?: throw ContractException("$stripWhere: 必须是对象")
                val markers = strip.requireArray("markers", stripWhere)
                for ((m, markerElement) in markers.withIndex()) {
                    val markerWhere = "$stripWhere: markers[$m]"
                    val marker = markerElement as? JsonObject
                        ?: throw ContractException("$markerWhere: 必须是对象")
                    marker.requireInt("tag_id", markerWhere)
                    val corners = marker.requireArray("corners_layout_m", markerWhere)
                    if (corners.size != 4) {
                        throw ContractException(
                            "$markerWhere: corners_layout_m 必须是 4 个三维角点（左上/右上/右下/左下，布局系，米）"
                        )
                    }
                    for ((c, corner) in corners.withIndex()) {
                        val vec = corner as? JsonArray
                            ?: throw ContractException("$markerWhere: corners_layout_m[$c]: 变换维度错误——必须是 3 个数值分量")
                        if (vec.size != 3) {
                            throw ContractException(
                                "$markerWhere: corners_layout_m[$c]: 变换维度错误——必须是 3 个数值分量，实际为 ${vec.size} 个"
                            )
                        }
                    }
                }
            }
            val mirrorRef = layout.requireObject("mirror_reference", Contracts.LAYOUT_PATH)
            Transform.fromMapping(mirrorRef["T_M_L"], "${Contracts.LAYOUT_PATH}: mirror_reference.T_M_L")
        }

        private fun validateExperiment(entries: Map<String, ByteArray>) {
            val experiment = parseJson(requireEntry(entries, Contracts.EXPERIMENT_PATH), Contracts.EXPERIMENT_PATH)
            Contracts.checkSchemaVersion(experiment, Contracts.EXPERIMENT_PATH)
            experiment.requireArray("entries", Contracts.EXPERIMENT_PATH)
        }

        /** 返回 (attempt 路径, attempt 对象) 列表。 */
        private fun validatePatches(
            session: JsonObject,
            entries: Map<String, ByteArray>,
            recipe: JsonObject,
            calibrationId: String?,
            device: JsonObject,
            expectedSequence: List<String>,
            streamW: Int,
            streamH: Int,
        ): List<Pair<String, JsonObject>> {
            val recipeHash = recipe.requireString("recipe_hash", Contracts.RECIPE_PATH)
            val deviceHash = device.requireString("device_config_hash", Contracts.DEVICE_PATH)
            val patches = session.requireArray("patches", Contracts.SESSION_MANIFEST_NAME)
            val attempts = ArrayList<Pair<String, JsonObject>>()
            for ((p, element) in patches.withIndex()) {
                val patchWhere = "${Contracts.SESSION_MANIFEST_NAME}: patches[$p]"
                val patch = element as? JsonObject
                    ?: throw ContractException("$patchWhere: 必须是对象")
                val patchId = patch.requireString("patch_id", patchWhere)
                val attRefs = patch.requireArray("attempts", patchWhere)
                for ((a, attElement) in attRefs.withIndex()) {
                    val attWhere = "$patchWhere: attempts[$a]"
                    val attRef = attElement as? JsonObject
                        ?: throw ContractException("$attWhere: 必须是对象")
                    val attemptId = attRef.requireString("attempt_id", attWhere)
                    val ajPath = "patches/$patchId/attempts/$attemptId/attempt.json"
                    if (attRef.requireString("path", attWhere) != ajPath) {
                        throw ContractException("$attWhere: path 必须是 '$ajPath'")
                    }
                    val attempt = parseJson(requireEntry(entries, ajPath), ajPath)
                    validateAttempt(
                        attempt, ajPath, entries, patchId, attemptId,
                        recipeHash, calibrationId, deviceHash, expectedSequence, streamW, streamH,
                    )
                    attempts.add(ajPath to attempt)
                }
            }
            return attempts
        }

        private fun validateAttempt(
            attempt: JsonObject,
            ajPath: String,
            entries: Map<String, ByteArray>,
            patchId: String,
            attemptId: String,
            recipeHash: String,
            calibrationId: String?,
            deviceHash: String,
            expectedSequence: List<String>,
            streamW: Int,
            streamH: Int,
        ) {
            Contracts.checkSchemaVersion(attempt, ajPath)
            if (attempt.requireString("patch_id", ajPath) != patchId ||
                attempt.requireString("attempt_id", ajPath) != attemptId
            ) {
                throw ContractException("$ajPath: patch_id/attempt_id 与所在路径不一致")
            }
            Contracts.checkEnum(
                attempt["capture_status"]?.jsonPrimitive?.contentOrNull,
                Contracts.CAPTURE_STATUSES,
                "capture_status",
                ajPath,
            )

            if (attempt.requireString("recipe_hash", ajPath) != recipeHash) {
                throw ContractException("$ajPath: attempt 绑定的 recipe_hash 与会话配方不一致（标定/配置不匹配）")
            }
            val attCal = attempt["calibration_id"]?.let { element ->
                if (element is JsonNull) null else (element as? JsonPrimitive)?.contentOrNull
            }
            if (attCal != calibrationId) {
                throw ContractException(
                    "$ajPath: attempt 绑定的 calibration_id=$attCal 与会话标定 $calibrationId 不一致（标定/配置不匹配）"
                )
            }
            if (attempt.requireString("device_config_hash", ajPath) != deviceHash) {
                throw ContractException("$ajPath: attempt 绑定的 device_config_hash 与设备配置不一致（标定/配置不匹配）")
            }

            val expected = attempt.requireArray("expected_frames", ajPath).map {
                (it as? JsonPrimitive)?.content ?: throw ContractException("$ajPath: expected_frames 项必须是字符串")
            }
            if (expected != expectedSequence) {
                throw ContractException("$ajPath: expected_frames 与配方图案序列不一致（配置不匹配）")
            }

            val frames = attempt.requireArray("frames", ajPath)
            if (frames.isEmpty()) {
                throw ContractException("$ajPath: frames 必须是非空数组")
            }
            val actual = frames.map { (it as? JsonObject)?.get("pattern_id")?.jsonPrimitive?.contentOrNull }
            if (actual != expectedSequence) {
                val missing = expectedSequence.filter { it !in actual }
                val extra = actual.filterNotNull().filter { it !in expectedSequence }
                val details = buildList {
                    if (missing.isNotEmpty()) add("缺少图案帧 ${missing.take(3)}")
                    if (extra.isNotEmpty()) add("多余图案帧 ${extra.take(3)}")
                }
                throw ContractException(
                    "$ajPath: 帧序列与配方不一致（缺帧/乱序/重复）：${details.joinToString("；").ifEmpty { "顺序不匹配" }}；" +
                        "期望 ${expectedSequence.size} 帧，实际 ${frames.size} 帧"
                )
            }

            val baseDir = "patches/$patchId/attempts/$attemptId"
            for ((i, element) in frames.withIndex()) {
                val frameWhere = "$ajPath: frames[$i]"
                val frame = element as? JsonObject
                    ?: throw ContractException("$frameWhere: 必须是对象")
                if (frame.requireInt("frame_index", frameWhere) != i) {
                    throw ContractException("$frameWhere: frame_index 与数组下标 $i 不一致（帧序号必须连续）")
                }
                val file = frame.requireString("file", frameWhere)
                if (!Regex("^frames/[A-Za-z0-9][A-Za-z0-9._-]*$").matches(file)) {
                    throw ContractException("$frameWhere: file=$file 必须形如 'frames/<名称>'（位于本 attempt 目录内）")
                }
                val format = frame.requireString("format", frameWhere)
                if (format !in Contracts.FRAME_FORMATS) {
                    throw ContractException("$frameWhere: 未知帧格式 $format")
                }
                val w = frame.requirePositiveInt("width_px", frameWhere)
                val h = frame.requirePositiveInt("height_px", frameWhere)
                if (w != streamW || h != streamH) {
                    throw ContractException("$frameWhere: 帧尺寸 ${w}x${h} 与设备流配置 ${streamW}x${streamH} 不一致（配置不匹配）")
                }
                val framePath = "$baseDir/$file"
                val data = entries[framePath]
                    ?: throw ContractException("$frameWhere: 帧文件 $framePath 不在包内（缺帧）")
                if (format == "raw8" && data.size != w * h) {
                    throw ContractException("$framePath: raw8 帧数据字节数 ${data.size} 与 ${w}x${h}=${w * h} 不一致")
                }
                Contracts.checkNsTimestamp(frame["sensor_timestamp_ns"], "sensor_timestamp_ns", frameWhere)
                Contracts.checkNsTimestamp(frame["exposure_time_ns"], "exposure_time_ns", frameWhere)
                Contracts.checkEnum(
                    frame["timestamp_source"]?.jsonPrimitive?.contentOrNull,
                    Contracts.TIMESTAMP_SOURCES,
                    "timestamp_source",
                    frameWhere,
                )
            }

            val obsRef = attempt.requireObject("observations", ajPath)
            if (obsRef.requireString("path", "$ajPath: observations") != "observations.json") {
                throw ContractException("$ajPath: observations.path 必须是 'observations.json'（本 attempt 目录内）")
            }
            val obsPath = "patches/$patchId/attempts/$attemptId/observations.json"
            validateObservations(parseJson(requireEntry(entries, obsPath), obsPath), obsPath)
        }

        private fun validateObservations(observations: JsonObject, where: String) {
            Contracts.checkSchemaVersion(observations, where)
            val markers = observations.requireArray("markers", where)
            for ((i, element) in markers.withIndex()) {
                val markerWhere = "$where: markers[$i]"
                val marker = element as? JsonObject
                    ?: throw ContractException("$markerWhere: 必须是对象")
                val corners = marker.requireArray("corners_image_px", markerWhere)
                if (corners.size != 4) {
                    throw ContractException("$markerWhere: corners_image_px 必须是 4 个二维角点（图像系，像素）")
                }
                for ((c, corner) in corners.withIndex()) {
                    val vec = corner as? JsonArray
                        ?: throw ContractException("$markerWhere: corners_image_px[$c]: 必须是 [x, y] 两个数值")
                    if (vec.size != 2) {
                        throw ContractException("$markerWhere: corners_image_px[$c]: 必须是 [x, y] 两个数值，实际为 ${vec.size} 个")
                    }
                }
            }
            observations.optObject("imu")?.let { imu ->
                val segments = imu["segments"] as? JsonArray
                    ?: throw ContractException("$where: imu.segments 必须是数组")
                for ((i, element) in segments.withIndex()) {
                    val segWhere = "$where: imu.segments[$i]"
                    val seg = element as? JsonObject ?: throw ContractException("$segWhere: 必须是对象")
                    Contracts.checkNsTimestamp(seg["t_start_ns"], "t_start_ns", segWhere)
                    Contracts.checkNsTimestamp(seg["t_end_ns"], "t_end_ns", segWhere)
                }
            }
            observations.optObject("preliminary_pose")?.let { pose ->
                pose["T_L_C"]?.let { transform ->
                    val parsed = Transform.fromMapping(transform, "$where: preliminary_pose.T_L_C")
                    if (parsed.fromFrame != "L" || parsed.toFrame != "C") {
                        throw ContractException("$where: preliminary_pose.T_L_C 的 from_frame/to_frame 必须分别是 'L'/'C'")
                    }
                }
            }
        }

        private fun validateCompletion(session: JsonObject, attempts: List<Pair<String, JsonObject>>) {
            if (session.requireString("capture_status", Contracts.SESSION_MANIFEST_NAME) != "complete") return
            for ((path, attempt) in attempts) {
                val status = attempt["capture_status"]?.jsonPrimitive?.contentOrNull
                if (status != "complete") {
                    throw ContractException(
                        "$path: 会话标记 complete，但该尝试状态为 $status；未完整落盘的组不得标为 complete"
                    )
                }
            }
        }
    }
}
