# 数据契约：单位、坐标、变换、哈希与状态

本文件是 `schemas/` 的规范说明，也是两端实现（`python/mirror_core`、
`android/contracts`）共同强制执行的规则。任何读取端遇到不符合本契约的
数据必须显式报错，不允许静默宽容解析（PR-01 验收项）。

## 1. 包结构与清单

离线交换单元是一个自包含 ZIP（实施方案 §8.1）：

```
session.json                                   清单、状态与引用
device.json                                    设备能力与配置快照
calibration/index.json (+ 条目文件)            本次使用的标定内容
layout.json                                    条带标记布局与镜面参考关系
recipe.json                                    采集配方（不可变、带哈希）
patches/<PID>/attempts/<AID>/attempt.json      一次尝试的绑定与逐帧元数据
patches/<PID>/attempts/<AID>/frames/<N>.bin    无损帧数据（raw8）
patches/<PID>/attempts/<AID>/observations.json 标记角点、IMU 与初步位姿
experiment.json                                人工操作记录
```

- `session.json` 的 `files` 数组登记**除自身外**的每一个文件：相对路径、
  SHA-256、字节数。清单与 ZIP 条目必须精确一致：清单里的文件不存在（缺文件/缺帧）、
  包内存在未登记文件、大小或哈希不一致，都是明确报错。
- 包内路径一律 POSIX 分隔、无 `..`、无目录条目。
- `provenance` 字段区分 `synthetic`（合成数据，仅用于契约与回归）与
  `device`（真机采集）。合成包必须在各文件内显式标注。

## 2. 单位

| 量 | 单位 | 说明 |
| --- | --- | --- |
| 长度 | `m` | 所有 `_m` 后缀字段；未知单位（如 cm、mm）必须报错 |
| 角度 | `rad` | 所有 `_rad` / `_deg`（显式命名）后缀字段 |
| 时间 | `s` | 字段名以 `_ns` 结尾的纳秒时间戳使用**十进制字符串** |
| 图像坐标 | `pixel` | `_px` 后缀字段 |
| 屏幕对应坐标 | 归一化 `[0,1]` | 有效发光矩形内的 `u/v` |

`session.json` 的 `units` 对象固定为 `{"length": "m", "angle": "rad", "time": "s"}`；
读取端校验该对象，任何其他取值都是“未知单位”错误。

**纳秒时间戳必须是十进制字符串**（如 `"1773724800000000000"`），
避免 JavaScript 数值精度损失（实施方案 §8.1）。

## 3. 坐标系与变换方向

统一约定 `T_A_B` 表示**把 B 系坐标变换到 A 系**。JSON 对象：

```json
{
  "from_frame": "P",
  "to_frame": "M",
  "convention": "T_A_B",
  "rotation": [[r00, r01, r02], [r10, r11, r12], [r20, r21, r22]],
  "translation_m": [tx, ty, tz]
}
```

- 该对象即 `T_M_P`：`P_A = R @ P_B + t`（A=`to_frame`，B=`from_frame`）。
- `rotation` 是 3×3 **行主序**矩阵；`translation_m` 单位米。
- 维度错误（行/列数不为 3）、非有限数值、非法坐标系标识、约定字段不是
  `T_A_B`，都必须显式报错。
- 法线方向量跟随同一旋转（`n_A = R @ n_B`），没有平移项。

### 3.1 已登记坐标系

| 标识 | 含义 |
| --- | --- |
| `M` | 镜面参考系：右手系，原点在镜面参考点，x 向右、y 向上、z 指向观察者 |
| `C` | 相机系（Camera2 图像坐标系对应的相机坐标系） |
| `D` | 屏幕（Display）系 |
| `P` | 单站局部系（SOFAST 单站 facet 输出的局部坐标系） |
| `L` | 布局系（条带标记布局定义的坐标系，见 `layout.json` 的 `layout_frame`） |

坐标系标识为 `[A-Z][A-Z0-9_]*`。新坐标系在加入时必须先在本文件登记其定义。

### 3.2 图像与屏幕坐标

- **图像坐标**：原点在左上角像素的左上角，x 向右、y 向下，单位像素；
  角点可为亚像素浮点。角点顺序：左上、右上、右下、左下。
- **屏幕对应坐标**：`u`、`v` 为有效发光矩形内的归一化坐标 `[0,1]`，
  `u` 向右、`v` 向下，按 `device.json` 记录的实际渲染方向解释。
  `unwrap_phase` 等后续字段输出弧度、周期数还是归一化坐标，
  一律通过字段名与单位后缀显式表达（如 `_norm_u`、`_cycles`、`_rad`）。

## 4. 会话与结果状态

（实施方案 §8.3；枚举在 `schemas/results/job.schema.json` 与两端代码同步）

| 类别 | 取值 |
| --- | --- |
| 采集状态 | `collecting` / `complete` / `aborted` |
| 传输状态 | `local_only` / `transferring` / `verified` |
| 求解状态 | `queued` / `running` / `succeeded` / `failed` / `cancelled` |
| 结果支持状态 | `diagnostic` / `local_validated` / `global_validated` |

- 会话标记 `complete` 时，所有尝试必须 `complete` 且帧序列完整；
  未完整落盘的组不得标为 `complete`。
- 中止后重采创建新 `attempt_id`；不得从两次尝试拼凑相移序列。

## 5. 绑定与完整性

每次尝试（attempt）绑定 `recipe_hash`、`calibration_id`、`device_config_hash`：

- `device_config_hash` = `device.json` 中 `device_config` 对象的规范 JSON SHA-256；
- `recipe_hash` = `recipe.json` 中除 `recipe_hash` 外全部内容的规范 JSON SHA-256；
- attempt 的绑定值必须与会话级引用一致，配方声明的适用标定/设备配置也必须
  与本次一致。任何不一致都归类为**标定/配置不匹配**并明确报错。
- `expected_frames` 必须等于配方图案按 `display_order` 排列并乘以 `repeats`
  的序列；实际 `frames` 与之逐项一致（缺帧、多余、重复、乱序都报错）。
- `raw8` 帧数据字节数必须等于 `width_px * height_px`，且帧尺寸与设备流
  配置一致。

## 6. 规范 JSON 与哈希

内容哈希基于“规范 JSON 字节串”：

- UTF-8 编码，无 BOM；
- 对象键按码点升序排序；
- 分隔符 `,` 与 `:`，无任何空白；
- 数值按源文本原样保留（生成端必须先写出规范形式再计算哈希）；
- 不允许 NaN / Infinity。

两端实现（`mirror_core.canonical`、`org.mirrorchecker.contracts.JsonUtil`）
对同一对象必须产生**完全相同的字节串**；Kotlin 测试通过校验 Python
生成的 `device_config_hash` / `recipe_hash` 来锁定这一一致性。

## 7. 版本策略

`schema_version` 当前为 `1.0.0`：

- **主版本**升级 = 不兼容变更；读取端对未知主版本显式报错。
- 追加可选字段属于**次版本**升级；旧读取端忽略未知字段。
- 每次契约变更需同步更新：`schemas/`、两端校验实现、双端测试与范例包。

## 8. 明确报错的最低要求（PR-01 验收）

1. 最小有效会话可解析；
2. 缺帧 / 缺文件 → 报错并指明缺失对象；
3. 未知单位 → 报错并指明字段与非法取值；
4. 变换维度错误 → 报错并指明期望维度；
5. 标定 / 配置不匹配 → 报错并指明两侧取值；
6. 范例数据同时被两端读取（Python 测试与 Kotlin 测试共用
   `tests/fixtures/synthetic_session_v1.zip`）。
