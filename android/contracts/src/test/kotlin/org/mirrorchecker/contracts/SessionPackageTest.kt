package org.mirrorchecker.contracts

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream

/**
 * 与 Python 端（tests/python/test_session_validate.py）对应的契约校验测试。
 * 两端读取同一份 tests/fixtures/synthetic_session_v1.zip（PR-01 验收项）。
 */
class SessionPackageTest {

    private val fixturePath: String =
        requireNotNull(System.getProperty("mirror.fixture")) { "缺少 mirror.fixture 系统属性" }

    private fun fixtureFile(): File = File(fixturePath)

    private fun readEntries(file: File): LinkedHashMap<String, ByteArray> {
        val entries = LinkedHashMap<String, ByteArray>()
        ZipInputStream(file.inputStream().buffered()).use { stream ->
            while (true) {
                val entry = stream.nextEntry ?: break
                if (!entry.isDirectory) entries[entry.name] = stream.readBytes()
            }
        }
        return entries
    }

    /** 生成被篡改的会话副本；fixManifest=true 时同步修复清单哈希以暴露更深层契约错误。 */
    private fun rewritten(
        changes: Map<String, ByteArray?>,
        fixManifest: Boolean = true,
        block: (File) -> Unit,
    ) {
        val entries = readEntries(fixtureFile())
        for ((name, content) in changes) {
            if (content == null) entries.remove(name) else entries[name] = content
        }
        if (fixManifest && entries.containsKey("session.json")) {
            val session = Json.parseToJsonElement(entries.getValue("session.json").decodeToString()) as JsonObject
            val kept = session["files"]!!.let { files ->
                val list = (files as kotlinx.serialization.json.JsonArray).mapNotNull { element ->
                    val entry = element as JsonObject
                    val path = (entry["path"] as JsonPrimitive).content
                    val content = entries[path] ?: return@mapNotNull null
                    buildJsonObject {
                        put("path", path)
                        put("sha256", JsonUtil.sha256Hex(content))
                        put("size_bytes", content.size)
                    }
                }
                kotlinx.serialization.json.JsonArray(list)
            }
            val updated = JsonObject((session.toMutableMap()).apply { put("files", kept) })
            entries["session.json"] = prettyJson(updated).encodeToByteArray()
        }
        val temp = File.createTempFile("tampered", ".zip").apply { deleteOnExit() }
        ZipOutputStream(temp.outputStream().buffered()).use { stream ->
            for ((name, content) in entries) {
                stream.putNextEntry(ZipEntry(name))
                stream.write(content)
                stream.closeEntry()
            }
        }
        block(temp)
    }

    private fun prettyJson(obj: JsonObject): String {
        // 测试辅助：与生成器的缩进形式保持一致即可，校验只依赖解析结果
        return obj.toString()
    }

    private fun editSessionJson(mutate: (JsonObject) -> JsonObject): ByteArray {
        val session = Json.parseToJsonElement(readEntries(fixtureFile()).getValue("session.json").decodeToString()) as JsonObject
        return prettyJson(mutate(session)).encodeToByteArray()
    }

    private fun editJson(path: String, mutate: (JsonObject) -> JsonObject): ByteArray {
        val obj = Json.parseToJsonElement(readEntries(fixtureFile()).getValue(path).decodeToString()) as JsonObject
        return prettyJson(mutate(obj)).encodeToByteArray()
    }

    private fun withObject(obj: JsonObject, key: String, value: kotlinx.serialization.json.JsonElement): JsonObject =
        JsonObject(obj.toMutableMap().apply { put(key, value) })

    @Test
    fun `范例会话在 Android 端可解析并校验通过`() {
        val pkg = SessionPackage.open(fixtureFile())
        assertEquals("5f2c1a4e-8b3d-4c6a-9e0f-1a2b3c4d5e6f", pkg.sessionId)
        assertEquals("synthetic", pkg.provenance)
        assertEquals("complete", pkg.captureStatus)
        assertEquals(1, pkg.attemptCount)
        assertEquals(18, pkg.totalFrames)
        assertTrue(pkg.manifestFileCount > 0)
    }

    @Test
    fun `未知长度单位必须明确报错`() {
        val session = editSessionJson { obj ->
            withObject(obj, "units", JsonObject((obj["units"] as JsonObject).toMutableMap().apply { put("length", JsonPrimitive("cm")) }))
        }
        rewritten(mapOf("session.json" to session), fixManifest = false) { file ->
            try {
                SessionPackage.open(file)
                fail("应当抛出 ContractException")
            } catch (e: ContractException) {
                assertTrue(e.message!!.contains("未知长度单位"))
            }
        }
    }

    @Test
    fun `清单文件缺失必须明确报错`() {
        rewritten(mapOf("patches/P0001/attempts/A001/frames/0007.bin" to null), fixManifest = false) { file ->
            try {
                SessionPackage.open(file)
                fail("应当抛出 ContractException")
            } catch (e: ContractException) {
                assertTrue(e.message!!.contains("在包内不存在"))
            }
        }
    }

    @Test
    fun `变换维度错误必须明确报错`() {
        val obs = editJson("patches/P0001/attempts/A001/observations.json") { obj ->
            val pose = obj["preliminary_pose"] as JsonObject
            val transform = pose["T_L_C"] as JsonObject
            val broken = withObject(transform, "rotation", Json.parseToJsonElement("[[1.0,0.0],[0.0,1.0]]"))
            withObject(obj, "preliminary_pose", withObject(pose, "T_L_C", broken))
        }
        rewritten(mapOf("patches/P0001/attempts/A001/observations.json" to obs)) { file ->
            try {
                SessionPackage.open(file)
                fail("应当抛出 ContractException")
            } catch (e: ContractException) {
                assertTrue(e.message!!.contains("变换维度错误"))
            }
        }
    }

    @Test
    fun `标定不匹配必须明确报错`() {
        val attempt = editJson("patches/P0001/attempts/A001/attempt.json") { obj ->
            withObject(obj, "calibration_id", JsonPrimitive("cal-synthetic-0002"))
        }
        rewritten(mapOf("patches/P0001/attempts/A001/attempt.json" to attempt)) { file ->
            try {
                SessionPackage.open(file)
                fail("应当抛出 ContractException")
            } catch (e: ContractException) {
                assertTrue(e.message!!.contains("标定/配置不匹配"))
            }
        }
    }

    @Test
    fun `配方哈希不匹配必须明确报错`() {
        val recipe = editJson("recipe.json") { obj ->
            val patterns = obj["patterns"] as kotlinx.serialization.json.JsonArray
            val first = patterns[0] as JsonObject
            val changed = withObject(first, "frequency_cycles_per_pattern", JsonPrimitive(6))
            val newPatterns = kotlinx.serialization.json.JsonArray(patterns.toMutableList().apply { set(0, changed) })
            withObject(obj, "patterns", newPatterns)
        }
        rewritten(mapOf("recipe.json" to recipe)) { file ->
            try {
                SessionPackage.open(file)
                fail("应当抛出 ContractException")
            } catch (e: ContractException) {
                assertTrue(e.message!!.contains("recipe_hash 与配方内容不匹配"))
            }
        }
    }

    @Test
    fun `缺帧必须明确报错`() {
        val attemptPath = "patches/P0001/attempts/A001/attempt.json"
        val attempt = editJson(attemptPath) { obj ->
            val frames = obj["frames"] as kotlinx.serialization.json.JsonArray
            kotlinx.serialization.json.JsonArray(frames.toMutableList().apply { removeAt(7) })
                .let { withObject(obj, "frames", it) }
        }
        rewritten(
            mapOf(
                "patches/P0001/attempts/A001/frames/0007.bin" to null,
                attemptPath to attempt,
            ),
        ) { file ->
            try {
                SessionPackage.open(file)
                fail("应当抛出 ContractException")
            } catch (e: ContractException) {
                assertTrue(e.message!!.contains("帧序列与配方不一致"))
            }
        }
    }

    @Test
    fun `规范 JSON 与 Python 端字节一致`() {
        // 该用例依赖 fixture 内 device.json 的 device_config 与其哈希；
        // 若两端规范序列化不一致，open() 会在 device_config_hash 校验处失败。
        val pkg = SessionPackage.open(fixtureFile())
        assertEquals("1.0.0", pkg.schemaVersion)
    }
}
