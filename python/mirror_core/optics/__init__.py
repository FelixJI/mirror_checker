"""光学核心:独立正向光线仿真、参考回放与解析交叉验证(PR-02)。

模块划分:

- :mod:`mirror_core.optics.linalg` — 向量与矩阵基础工具
- :mod:`mirror_core.optics.surfaces` — 高度场表面族与解析法线/曲率
- :mod:`mirror_core.optics.fringes` — 上游 SOFAST 条纹公式移植与相位解包
- :mod:`mirror_core.optics.forward` — 独立正向光线模型(真值生成)
- :mod:`mirror_core.optics.solve` — 回放求解:屏幕对应 → 斜率/法线 → 拟合
- :mod:`mirror_core.optics.cases` — 标准合成案例注册表与验证

约定:本包所有几何量在国际单位制(米、弧度)下计算;表面高度场在
镜面参考系 M 中定义,``+z`` 指向相机一侧;屏幕对应坐标为有效发光
矩形内的归一化 ``u/v ∈ [0, 1]``。零第三方运行时依赖。
"""

from __future__ import annotations

__all__ = [
    "cases",
    "forward",
    "fringes",
    "linalg",
    "solve",
    "surfaces",
]
