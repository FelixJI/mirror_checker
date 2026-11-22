// Android 工程根构建脚本。
// 纯 JVM 模块（:contracts、:probe）与 AGP 应用模块（:app，PR-03 起）的插件
// 统一在根声明并 apply false，保证各模块 Kotlin/AGP 插件族版本一致；
// :app 仅在检测到 Android SDK 时纳入构建（见 settings.gradle.kts）。
plugins {
    alias(libs.plugins.kotlin.jvm) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.android.application) apply false
}
