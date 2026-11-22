// Android 工程根构建脚本。PR-01 只有纯 JVM 契约模块；
// AGP 应用模块（:app）在 PR-03 按真机信息锁定版本后加入。
plugins {
    alias(libs.plugins.kotlin.jvm) apply false
}
