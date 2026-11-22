# android/ —— Android 构建入口与契约模块

本目录是 Android 侧的 Gradle 工程入口（Windows 与 CI 均通过 Gradle wrapper
构建，无需本机安装 Gradle）。

## 模块

| 模块 | 说明 |
| --- | --- |
| `:contracts` | 纯 Kotlin/JVM 模块：会话数据契约的解析与校验，与 `python/mirror_core` 强制同一套规则。后续被采集应用（PR-03 的 `:app`）复用。 |

PR-01 只交付契约模块与构建入口；安卓采集应用（AGP `:app` 模块）在 PR-03
按真机信息（H01）锁定 AGP/SDK 版本后加入。

## 构建与测试

需要 JDK 17（Gradle 工具链会自动解析）：

```bash
cd android
./gradlew --no-daemon :contracts:test          # Windows: gradlew.bat --no-daemon :contracts:test
```

测试读取仓库根目录 `tests/fixtures/synthetic_session_v1.zip`，
与 Python 端共用同一份范例数据（双端读取同一字节）。

## 版本锁定

Gradle wrapper、Kotlin、kotlinx-serialization 与 JUnit 版本固定在
`gradle/libs.versions.toml` 与 `gradle/wrapper/gradle-wrapper.properties`；
升级策略见 `docs/dependencies.md`。
