// Android 工程根构建脚本。纯 JVM 模块（:contracts、:probe）在此声明；
// AGP 应用模块（:app，PR-03 起）的插件只在 :app 内声明并在检测到 Android SDK 时
// 纳入构建（见 settings.gradle.kts），保证无 SDK 的纯 JDK 环境也能运行契约与探测测试。
plugins {
    alias(libs.plugins.kotlin.jvm) apply false
}
