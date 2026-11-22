# schemas/ —— 版本化数据契约

本目录是两端（Python 与 Android/Kotlin）共同遵守的协议规范。每个 JSON 文件
是 JSON Schema（draft 2020-12）格式的**规范文档**；两端代码各自内置同一套
强制校验（`python/mirror_core`、`android/contracts`），错误必须显式报出，
不允许静默宽容解析。

## 文件与适用对象

| Schema | 适用文件 |
| --- | --- |
| `session/session.schema.json` | 会话 ZIP 内 `session.json` |
| `session/device.schema.json` | `device.json` |
| `session/calibration-index.schema.json` | `calibration/index.json` |
| `session/layout.schema.json` | `layout.json` |
| `session/recipe.schema.json` | `recipe.json` |
| `session/attempt.schema.json` | `patches/<PID>/attempts/<AID>/attempt.json` |
| `session/observations.schema.json` | `patches/<PID>/attempts/<AID>/observations.json` |
| `session/experiment.schema.json` | `experiment.json` |
| `results/job.schema.json` | 派生结果的求解任务登记（PR-07+ 产生） |

单位、坐标方向、规范 JSON 哈希与状态语义的完整说明见
`docs/contracts/README.md`。

## 版本策略

- `schema_version` 采用语义化版本（当前 `1.0.0`）。
- **主版本**升级表示不兼容变更：读取端必须对未知主版本显式报错。
- 追加可选字段属于**次版本**升级：旧读取端应忽略未知字段而不是失败。
- 两端代码内置支持的主版本与 schema 声明不一致时，一律拒绝解析。

## 一致性验证

`tests/python/test_schemas.py` 在安装了 `jsonschema` 的环境（如 CI）中
验证范例会话的每个 JSON 文件都符合对应 Schema，防止规范文档与代码实现
漂移；两端的手写校验器是运行时唯一的强制手段。
