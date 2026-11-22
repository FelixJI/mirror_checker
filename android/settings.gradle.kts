pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        mavenCentral()
        google()
    }
}

rootProject.name = "mirror-checker-android"

include(":contracts")
include(":probe")

// :app（诊断 APK）需要 Android SDK；CI 通过 ANDROID_HOME 提供。
// 本机未安装 SDK 时跳过 :app，:contracts:test 与 :probe:test 仍可在纯 JDK 下运行。
val androidHome = providers.environmentVariable("ANDROID_HOME").orNull
    ?: providers.environmentVariable("ANDROID_SDK_ROOT").orNull
val localProperties = rootProject.projectDir.resolve("local.properties")
val sdkDir = if (localProperties.isFile) {
    localProperties.readLines().firstOrNull { it.startsWith("sdk.dir=") }?.substringAfter("sdk.dir=")
} else {
    null
}
if (androidHome != null || !sdkDir.isNullOrEmpty()) {
    include(":app")
} else {
    logger.lifecycle("未检测到 Android SDK（ANDROID_HOME/local.properties），本次构建跳过 :app 模块")
}
