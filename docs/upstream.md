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

## PR-02:公式移植对照与实跑证据

PR-02 采取**公式移植而非 vendored 文件**的方式复用上游:零依赖
纯 Python 重写,不引入 numpy 运行时依赖。移植对照表(逐公式对齐
固定提交 `356e3a9`,详见 [optics.md](optics.md)):

| 本仓库位置 | 上游来源 | 移植内容 |
| --- | --- | --- |
| `mirror_core/optics/fringes.py` | `opencsp/app/sofast/lib/Fringes.py` | 周期序列 `[0.9,4,16,64]`、4 步相移、y 先 x 后帧序、`(1-s)·period·2π` 幅角方向 |
| `mirror_core/optics/fringes.py` | `opencsp/app/sofast/lib/image_processing.py:unwrap_phase` | `atan2(c2−c4, c1−c3)` 与多频解缠公式 |
| `mirror_core/optics/forward.py` | `opencsp/app/sofast/lib/DisplayShape.py` | 矩形屏幕米制映射 `x=(u−0.5)·W, y=(v−0.5)·H` |
| `mirror_core/optics/solve.py` | `opencsp/common/lib/deflectometry/slope_fitting_2d.py` | 角平分法线、斜率符号、`poly_terms` 项序 |
| `mirror_core/optics/solve.py` | `opencsp/common/lib/deflectometry/SlopeSolver.py` | 射线∩拟合面迭代思路(上游 4 轮,本仓库 3 轮实测收敛) |
| `mirror_core/optics/solve.py` | `opencsp/app/sofast/lib/Surface2DParabolic.py:fit_slopes` | 斜率系数积分合成曲面系数 |

与本提交时上游源码的**有记录差异**(非遗漏,均为显式设计决定):

1. **屏幕坐标翻转**:上游对 y 轴 `uy = 1 − unwrapped`、x 轴直接取
   unwrapped(与其相机—屏幕成像几何绑定);本仓库正向模型按真实
   光路编码,两轴统一 `coord = 1 − unwrapped`。
2. **拟合阶数**:上游 Parabolic 面用一阶斜率多项式;本仓库默认
   全阶 4(覆盖波纹案例趋势,纯二次面同样精确恢复)。
3. **迭代范围**:上游含法线对齐与距离标定的完整外循环;本仓库
   首版以名义基准平面固定深度自由度 + 3 轮拟合面迭代,误差预算
   见 optics.md §5。

### 上游样例实跑记录(2026-11-22)

在独立 venv(Python 3.13.15 + numpy 2.5.5;上游 requirements 锁
numpy<2,但其 1.x 无 Python 3.13 轮子——`Fringes.py` 与
`unwrap_phase` 仅用基础运算,跨 numpy 大版本行为一致)中:

1. 从固定提交检出 `opencsp/app/sofast/lib/Fringes.py`(仅依赖
   numpy)与 `image_processing.py`;
2. 运行 `Fringes.from_num_periods(4).get_frames(96, 64, "float64",
   [0, 1])`,并提取 `unwrap_phase` 函数本体(文件顶层 import cv2,
   该函数仅用 `np.arctan2/np.mod`)在 numpy 命名空间执行;
3. 与本仓库 `mirror_core.optics.fringes` 逐点对比。

结果:**帧值 2016 个采样点最大差 2.8e-14;解包 7 个屏幕位置最大差
6.0e-10**(上游内部 float32 转换所致,非公式差异)。代表性采样点
固化于 `tests/python/test_optics_fringes.py:UpstreamRecordedValuesTest`,
CI 无 numpy 亦锁定一致。完整采样记录未入库;需要时按上述步骤
重新执行对比。

### 升级策略

上游提交只在满足以下条件时更新：新提交解决了影响本项目的问题，且已有回放
数据在新旧提交上均通过一致性检查。更新时同步修改本表并重跑回归。

## 第三方依赖许可

- Python 端核心零运行时依赖（仅标准库）；测试可选 `jsonschema`（MPL 2.0）。
- Android 端：Kotlin（Apache 2.0）、kotlinx.serialization（Apache 2.0）、
  JUnit 4（EPL 1.0，仅测试）。

新增依赖时必须在本文件登记来源、版本与许可。
