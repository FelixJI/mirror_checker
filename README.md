# mirror_checker

家用穿衣镜镜面成像质量检测：安卓负责可靠采集，电脑（Python/SOFAST 参考
实现）负责完整求解。目标是在指定观察位置输出镜面相对理想平面镜的横向、
纵向成像比例变化（`Mx`、`My`、`Mx/My-1`）。

实施计划见 [docs/plans/SOFAST_安卓镜面检测实施方案_v2.md](docs/plans/SOFAST_安卓镜面检测实施方案_v2.md)。
当前进度：**PR-01（数据契约与工程基线）**。本仓库尚不输出任何实际镜子
的测量结论。

## 目录结构

| 路径 | 内容 |
| --- | --- |
| `android/` | Android 构建入口与 Kotlin 契约模块（采集应用自 PR-03 加入） |
| `python/mirror_core/` | 契约、坐标变换、会话校验与合成数据生成（光学核心自 PR-02 加入） |
| `python/mirror_cli/` | `validate` / `make-sample` 命令（`solve`→PR-07、`workbench`→PR-08） |
| `schemas/` | 会话、设备、标定、布局、配方、观测与结果的版本化 JSON Schema |
| `tests/` | Python 单元测试与双端共用合成范例包 `fixtures/synthetic_session_v1.zip` |
| `docs/` | 契约规范、上游固定、依赖管理、实施方案 |
| `native/` | 后续可选 C++/JNI 核心；首版留空 |

## 快速开始

Python（零第三方依赖，需 Python 3.11+）：

```bash
# 校验会话包是否符合数据契约
PYTHONPATH=python python -m mirror_cli validate tests/fixtures/synthetic_session_v1.zip

# 运行全部 Python 测试
PYTHONPATH=python python -m unittest discover -s tests -p "test_*.py" -t .

# 生成明确标注为 synthetic 的合成范例会话
PYTHONPATH=python python -m mirror_cli make-sample --output sample.zip
```

Android/Kotlin 契约测试（需要 JDK 17，Gradle wrapper 自动解析）：

```bash
cd android
./gradlew --no-daemon :contracts:test      # Windows: gradlew.bat --no-daemon :contracts:test
```

## 数据契约

单位（米/弧度/纳秒字符串）、坐标系（M/C/D/P/L）、变换方向（`T_A_B` 把
B 系坐标变换到 A 系）、状态枚举、文件清单哈希与明确报错要求，统一见
[docs/contracts/README.md](docs/contracts/README.md)。Python 与 Kotlin
两端强制同一套规则，并共用同一份合成范例包做回归。

## 许可

Apache License 2.0（见 [LICENSE](LICENSE)）。上游 OpenCSP 固定提交与
复用范围见 [docs/upstream.md](docs/upstream.md)。
