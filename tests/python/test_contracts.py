"""contracts / canonical 单元测试。"""

import unittest

from mirror_core import contracts
from mirror_core.canonical import canonical_json_bytes, canonical_sha256, hash_object_excluding, sha256_hex, source_object_hash


class CanonicalJsonTests(unittest.TestCase):
    def test_keys_sorted_and_compact(self):
        raw = {"b": 1, "a": {"d": [1, 2], "c": "文"}}
        self.assertEqual(canonical_json_bytes(raw), '{"a":{"c":"文","d":[1,2]},"b":1}'.encode("utf-8"))

    def test_deterministic(self):
        raw = {"x": [1.5, True, None], "y": "s"}
        self.assertEqual(canonical_sha256(raw), canonical_sha256({"y": "s", "x": [1.5, True, None]}))

    def test_hash_verification_preserves_source_numbers(self):
        config = b'{"z": [1.0E-5, "1.0E-5", -0], "a": 0.10}'
        expected = sha256_hex(b'{"a":0.10,"z":[1.0E-5,"1.0E-5",-0]}')
        device = b'{"device_config":' + config + b'}'
        recipe = config[:-1] + b', "recipe_hash":"ignored"}'
        self.assertEqual(source_object_hash(device, field="device_config"), expected)
        self.assertEqual(source_object_hash(recipe, exclude="recipe_hash"), expected)

    def test_nan_rejected(self):
        with self.assertRaises(contracts.ContractError):
            canonical_json_bytes({"a": float("nan")})

    def test_hash_excluding(self):
        obj = {"k": 1, "h": "ignored"}
        obj2 = {"k": 1, "h": "other"}
        self.assertEqual(hash_object_excluding(obj, "h"), hash_object_excluding(obj2, "h"))


class ContractHelpersTests(unittest.TestCase):
    def test_schema_version_mismatch(self):
        with self.assertRaisesRegex(contracts.ContractError, "不支持的 schema_version"):
            contracts.check_schema_version("2.0.0", "x.json")

    def test_schema_version_ok(self):
        self.assertEqual(contracts.check_schema_version(contracts.SCHEMA_VERSION, "x.json"),
                         contracts.SCHEMA_VERSION)

    def test_enum_reject(self):
        with self.assertRaisesRegex(contracts.ContractError, "不在允许集合"):
            contracts.check_enum("bad", ("a", "b"), "field", "where")

    def test_ns_timestamp_must_be_string(self):
        with self.assertRaisesRegex(contracts.ContractError, "十进制数字字符串"):
            contracts.check_ns_timestamp(12345678901234567890, "t_ns", "where")

    def test_ns_timestamp_ok(self):
        self.assertEqual(contracts.check_ns_timestamp("1773724800000000000", "t_ns", "where"),
                         "1773724800000000000")

    def test_rel_path_rejects_traversal(self):
        for bad in ("../x", "a/../../b", "/abs", "a\\b", "dir/"):
            with self.assertRaises(contracts.ContractError, msg=bad):
                contracts.check_rel_path(bad, "path", "where")

    def test_sha256_format(self):
        with self.assertRaisesRegex(contracts.ContractError, "SHA-256"):
            contracts.check_sha256("ABC", "sha256", "where")

    def test_frame_ids(self):
        self.assertTrue(contracts.is_frame_id("M"))
        self.assertTrue(contracts.is_frame_id("CD"))
        self.assertFalse(contracts.is_frame_id("m"))
        self.assertFalse(contracts.is_frame_id("1"))


if __name__ == "__main__":
    unittest.main()
