"""Transform 解析、维度校验与数学行为测试。"""

import math
import unittest

from mirror_core import contracts
from mirror_core.transforms import Transform

_WHERE = "test.json: T"


def _rotation_z(deg: float):
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]


def _mapping(**overrides):
    mapping = {
        "from_frame": "P",
        "to_frame": "M",
        "convention": "T_A_B",
        "rotation": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "translation_m": [0.0, 0.0, 0.0],
    }
    mapping.update(overrides)
    return mapping


class TransformParseTests(unittest.TestCase):
    def test_identity(self):
        t = Transform.from_mapping(_mapping(), _WHERE)
        self.assertEqual((t.from_frame, t.to_frame), ("P", "M"))
        self.assertEqual(t.apply_point((1.0, 2.0, 3.0)), (1.0, 2.0, 3.0))

    def test_rotation_dimension_error_two_rows(self):
        with self.assertRaisesRegex(contracts.ContractError, "变换维度错误"):
            Transform.from_mapping(_mapping(rotation=[[1, 0, 0], [0, 1, 0]]), _WHERE)

    def test_rotation_dimension_error_two_cols(self):
        with self.assertRaisesRegex(contracts.ContractError, "变换维度错误"):
            Transform.from_mapping(
                _mapping(rotation=[[1, 0], [0, 1], [0, 0]]), _WHERE
            )

    def test_translation_dimension_error(self):
        with self.assertRaisesRegex(contracts.ContractError, "变换维度错误"):
            Transform.from_mapping(_mapping(translation_m=[0.0, 0.0]), _WHERE)

    def test_non_numeric_matrix_entry(self):
        with self.assertRaisesRegex(contracts.ContractError, "必须是数值"):
            Transform.from_mapping(
                _mapping(rotation=[[1, 0, "x"], [0, 1, 0], [0, 0, 1]]), _WHERE
            )

    def test_wrong_convention(self):
        with self.assertRaisesRegex(contracts.ContractError, "convention"):
            Transform.from_mapping(_mapping(convention="T_B_A"), _WHERE)

    def test_bad_frame_id(self):
        with self.assertRaisesRegex(contracts.ContractError, "坐标系标识"):
            Transform.from_mapping(_mapping(from_frame="p"), _WHERE)

    def test_missing_fields(self):
        mapping = _mapping()
        del mapping["translation_m"]
        with self.assertRaisesRegex(contracts.ContractError, "缺少必需字段"):
            Transform.from_mapping(mapping, _WHERE)


class TransformMathTests(unittest.TestCase):
    def test_rotation_90_about_z(self):
        t = Transform.from_mapping(_mapping(rotation=_rotation_z(90)), _WHERE)
        x, y, z = t.apply_point((1.0, 0.0, 0.0))
        self.assertAlmostEqual(x, 0.0, places=12)
        self.assertAlmostEqual(y, 1.0, places=12)
        self.assertAlmostEqual(z, 0.0, places=12)

    def test_translation_applies_after_rotation(self):
        t = Transform.from_mapping(
            _mapping(rotation=_rotation_z(180), translation_m=[1.0, 0.0, 0.0]), _WHERE
        )
        x, y, _ = t.apply_point((1.0, 0.0, 0.0))
        self.assertAlmostEqual(x, 0.0, places=12)
        self.assertAlmostEqual(y, 0.0, places=12)


if __name__ == "__main__":
    unittest.main()
