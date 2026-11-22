plugins {
    alias(libs.plugins.kotlin.jvm)
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    // 复用契约模块的规范 JSON/哈希（JsonUtil）与契约常量；
    // 探测报告是诊断产物，不是会话契约，二者分开维护。
    api(project(":contracts"))
    testImplementation(libs.junit)
}
