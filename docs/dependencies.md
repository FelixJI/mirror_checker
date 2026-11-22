# 依赖管理与版本锁定

## Python

- **验证环境**：CPython 3.11（CI 以 3.11 为准；本地 3.13 亦可通过测试，
  但发布口径以 3.11 回放结果为准，见实施方案 §2.3）。
- **运行时依赖**：无。`mirror_core` / `mirror_cli` 只使用标准库，
  保证采集端（未来安卓侧的会话导出校验）与回放端无环境负担。
- **开发依赖**：`jsonschema`（可选，用于 `tests/python/test_schemas.py`
  的 Schema 一致性检查；未安装时该组测试跳过）、pytest（可选，
  测试同时兼容 `python -m unittest`）。
- **锁文件**：`python/requirements-lock.txt`。当前运行时依赖为空；
  PR-02 起引入 NumPy/SciPy/OpenCV 等上游约束依赖时，逐版本锁定并附哈希，
  升级必须以“固定上游提交 + 回放数据一致”为依据，不得直接升到最新版本。

运行方式（无需安装）：

```bash
PYTHONPATH=python python -m mirror_cli validate tests/fixtures/synthetic_session_v1.zip
PYTHONPATH=python python -m unittest discover -s tests -p "test_*.py" -t .
```

或 `pip install -e .`（`pyproject.toml` 已把 `python/` 映射为包目录）。

## Android / Kotlin

| 项 | 版本 | 锁定位置 |
| --- | --- | --- |
| Gradle | 8.10.2（wrapper） | `android/gradle/wrapper/gradle-wrapper.properties` |
| Kotlin | 2.0.21 | `android/gradle/libs.versions.toml` |
| kotlinx-serialization-json | 1.7.3 | 同上 |
| JUnit | 4.13.2（仅测试） | 同上 |
| JDK 工具链 | 17 | `android/contracts/build.gradle.kts` |
| AGP | 8.7.3 | `android/gradle/libs.versions.toml` |
| compileSdk / targetSdk | 35 | `android/app/build.gradle.kts` |
| minSdk | 26 | 同上（H03 首台平板确认后复核） |
| Compose BOM | 2024.10.01 | `android/gradle/libs.versions.toml` |
| androidx core / activity / lifecycle | 1.13.1 / 1.9.3 / 2.8.7 | 同上 |

`android/contracts` 与 `android/probe` 是纯 Kotlin/JVM 模块，构建只需要
JDK（Gradle wrapper 自动解析工具链与发行版），不需要 Android SDK。
`android/app`（AGP 应用模块，PR-03 起）需要 Android SDK：CI 由
ubuntu-latest 自带 SDK（`ANDROID_HOME`）构建；无 SDK 的本地环境在
`settings.gradle.kts` 中自动跳过 `:app`，契约与探测测试仍可运行。
AGP/SDK 版本为无真机信息时的保守锁定，H03 提交首台平板报告后复核。

## CI

GitHub Actions（`.github/workflows/ci.yml`）：

- Python 任务：ubuntu-latest + windows-latest × Python 3.11，
  运行 unittest 与 CLI 校验，安装 jsonschema 以启用 Schema 一致性检查。
- Android 任务：ubuntu-latest × JDK 17（Temurin），运行
  `:contracts:test`、`:probe:test`，构建 `:app:assembleDebug` 并上传
  诊断 APK artifact（H03 真机安装用）。
- 发布工作流（`.github/workflows/release.yml`，手动触发）：选择
  patch/minor/major 递增或填写显式版本号（x.y.z）；在
  `android/app/build.gradle.kts` 中更新 `versionName` 并将 `versionCode`
  单调 +1，提交并打 `vX.Y.Z` 标签（仅允许在 main 上运行），随后构建
  APK、生成 SHA-256 并创建 GitHub Release。

CI 使用仓库内小型合成回归包，不下载大体积真实数据（实施方案 §2.3）。
