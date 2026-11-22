"""三维坐标变换的解析与校验。

契约约定（docs/contracts/README.md 第 3 节）：变换对象 ``T_A_B`` 表示
“把 B 系坐标变换到 A 系”，即::

    P_A = R_AB @ P_B + t_AB

JSON 表示::

    {
      "from_frame": "P",        # B 系
      "to_frame": "M",           # A 系，该对象即 T_M_P
      "convention": "T_A_B",
      "rotation": [[r00, r01, r02], [r10, r11, r12], [r20, r21, r22]],
      "translation_m": [tx, ty, tz]
    }

rotation 为 3x3 行主序矩阵，translation_m 单位为米。维度错误、非有限数值、
非法坐标系标识都必须显式报错。
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import TRANSFORM_CONVENTION, ContractError, is_frame_id

_DIM = 3


@dataclass(frozen=True)
class Transform:
    """T_to_from：把 from_frame 坐标变换到 to_frame。"""

    from_frame: str
    to_frame: str
    rotation: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
    translation_m: tuple[float, float, float]

    @classmethod
    def from_mapping(cls, mapping: object, where: str) -> "Transform":
        if not isinstance(mapping, dict):
            raise ContractError(f"{where}: 变换必须是对象，实际为 {type(mapping).__name__}")
        missing = [k for k in ("from_frame", "to_frame", "rotation", "translation_m", "convention") if k not in mapping]
        if missing:
            raise ContractError(f"{where}: 变换缺少必需字段 {missing}")

        convention = mapping["convention"]
        if convention != TRANSFORM_CONVENTION:
            raise ContractError(
                f"{where}: convention={convention!r} 不被支持（契约只允许 {TRANSFORM_CONVENTION}，"
                "即 from_frame 坐标变换到 to_frame）"
            )
        for key in ("from_frame", "to_frame"):
            if not is_frame_id(mapping[key]):
                raise ContractError(
                    f"{where}: {key}={mapping[key]!r} 不是合法坐标系标识（大写字母开头的 [A-Z0-9_]）"
                )

        rotation = _parse_matrix(mapping["rotation"], f"{where}: rotation")
        translation = _parse_vector(mapping["translation_m"], f"{where}: translation_m")
        return cls(
            from_frame=mapping["from_frame"],
            to_frame=mapping["to_frame"],
            rotation=rotation,
            translation_m=translation,
        )

    def apply_point(self, point: tuple[float, float, float]) -> tuple[float, float, float]:
        """把 from_frame 中的点变换到 to_frame。"""
        r = self.rotation
        t = self.translation_m
        return tuple(  # type: ignore[return-value]
            sum(r[i][j] * point[j] for j in range(_DIM)) + t[i] for i in range(_DIM)
        )


def _parse_matrix(value: object, where: str) -> tuple[tuple[float, float, float], ...]:
    if not isinstance(value, list) or len(value) != _DIM:
        raise ContractError(
            f"{where}: 变换维度错误——rotation 必须是 {_DIM}x{_DIM} 数值矩阵（行主序），"
            f"实际行数为 {len(value) if isinstance(value, list) else '非数组'}"
        )
    rows = []
    for i, row in enumerate(value):
        rows.append(_parse_row(row, f"{where}[{i}]"))
    return tuple(rows)  # type: ignore[return-value]


def _parse_row(row: object, where: str) -> tuple[float, float, float]:
    if not isinstance(row, list) or len(row) != _DIM:
        raise ContractError(
            f"{where}: 变换维度错误——矩阵每行必须有 {_DIM} 个数值，"
            f"实际为 {len(row) if isinstance(row, list) else '非数组'} 个"
        )
    values = []
    for j, v in enumerate(row):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ContractError(f"{where}[{j}]: 矩阵元素必须是数值，实际为 {type(v).__name__}")
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            raise ContractError(f"{where}[{j}]: 矩阵元素必须是有限数值，实际为 {v!r}")
        values.append(f)
    return (values[0], values[1], values[2])  # type: ignore[index]


def _parse_vector(value: object, where: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != _DIM:
        raise ContractError(
            f"{where}: 变换维度错误——平移向量必须有 {_DIM} 个分量（单位米），"
            f"实际为 {len(value) if isinstance(value, list) else '非数组'} 个"
        )
    out = []
    for i, v in enumerate(value):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ContractError(f"{where}[{i}]: 平移分量必须是数值，实际为 {type(v).__name__}")
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            raise ContractError(f"{where}[{i}]: 平移分量必须是有限数值，实际为 {v!r}")
        out.append(f)
    return (out[0], out[1], out[2])  # type: ignore[index]
