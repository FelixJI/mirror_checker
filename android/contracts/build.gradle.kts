plugins {
    alias(libs.plugins.kotlin.jvm)
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    // 只用 kotlinx-serialization 的解析能力（parseToJsonElement），
    // 不使用编译器插件，保持与未来 Android 应用模块的兼容性。
    api(libs.kotlinx.serialization.json)
    testImplementation(libs.junit)
}

tasks.test {
    useJUnit()
    // 与 Python 端共用仓库根目录下的同一份合成范例会话
    val fixture = rootProject.projectDir.parentFile.resolve("tests/fixtures/synthetic_session_v1.zip")
    systemProperty("mirror.fixture", fixture.absolutePath)
}
