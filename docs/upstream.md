# 上游固定与许可

## OpenCSP（SOFAST 参考实现）

| 项 | 值 |
| --- | --- |
| 仓库 | https://github.com/sandialabs/OpenCSP |
| 固定提交 | `356e3a98eeb880146b57955112b1a9759692531f` |
| 许可 | Apache License 2.0（与本仓库 LICENSE 相同） |
| 锁定日期 | 2026-11-21（实施方案 v2 核查版本） |

在 PR-02 引入实际复用代码前，本文件即为上游锚点；届时任何 vendored /
改动的文件必须保留 Apache-2.0 声明，并在文件头与下表中记录相对固定提交的
修改内容（实施方案 §6.1）。

### 计划复用范围（见实施方案 §6.2）

| 上游模块 | 用途 |
| --- | --- |
| `opencsp/app/sofast/lib/Fringes.py` | 条纹频率、相位与顺序的图案定义参考 |
| `ImageCalibrationGlobal / Scaling` | 响应校准（电脑端复用） |
| `image_processing.py` | 掩膜、相移解码、屏幕坐标展开 |
| `Camera / DisplayShape / SpatialOrientation` | 像素射线、屏幕映射与坐标关系 |
| `SlopeSolver / slope_fitting_2d` | 局部反射几何与拟合 |
| `MeasurementSofastFringe / DistanceOpticScreen` | 参考管线输入适配 |

第三方示例、文档与代码版本不一致时，以固定提交中的可运行路径和回放结果为准；
上游研究代码不自动构成本项目的计量保证。

### 升级策略

上游提交只在满足以下条件时更新：新提交解决了影响本项目的问题，且已有回放
数据在新旧提交上均通过一致性检查。更新时同步修改本表并重跑回归。

## 第三方依赖许可

- Python 端核心零运行时依赖（仅标准库）；测试可选 `jsonschema`（MPL 2.0）。
- Android 端：Kotlin（Apache 2.0）、kotlinx.serialization（Apache 2.0）、
  JUnit 4（EPL 1.0，仅测试）。

新增依赖时必须在本文件登记来源、版本与许可。
