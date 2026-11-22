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
| AGP / compileSdk | 未锁定 | PR-03 按 H01 真机信息决定 |

`android/contracts` 是纯 Kotlin/JVM 模块，构建只需要 JDK（Gradle wrapper
自动解析工具链与发行版），不需要 Android SDK；PR-03 加入 `:app`
（AGP）模块时再锁定 AGP 与 SDK 版本。

## CI

GitHub Actions（`.github/workflows/ci.yml`）：

- Python 任务：ubuntu-latest + windows-latest × Python 3.11，
  运行 unittest 与 CLI 校验，安装 jsonschema 以启用 Schema 一致性检查。
- Android 任务：ubuntu-latest × JDK 17（Temurin），运行
  `./gradlew --no-daemon :contracts:test`。

CI 使用仓库内小型合成回归包，不下载大体积真实数据（实施方案 §2.3）。
