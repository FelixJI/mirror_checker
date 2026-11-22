"""会话包契约校验测试：验收 PR-01 的各项明确报错。"""

import json
import tempfile
import unittest
from pathlib import Path

from mirror_core import contracts
from mirror_core.session import SessionPackage

from .util import edit_json, fixture_bytes, read_entries, rewrite

ATTEMPT_JSON = "patches/P0001/attempts/A001/attempt.json"
OBSERVATIONS_JSON = "patches/P0001/attempts/A001/observations.json"
FRAME_7 = "patches/P0001/attempts/A001/frames/0007.bin"


class ValidSessionTests(unittest.TestCase):
    def test_fixture_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.zip"
            path.write_bytes(fixture_bytes())
            package = SessionPackage.open(path)
        self.assertEqual(package.provenance, "synthetic")
        self.assertEqual(package.capture_status, "complete")
        self.assertEqual(package.calibration_id, "cal-synthetic-0001")
        self.assertEqual(package.total_frames, 18)
        self.assertEqual(len(package.attempts), 1)
        self.assertEqual(package.session_id, "5f2c1a4e-8b3d-4c6a-9e0f-1a2b3c4d5e6f")


class SessionValidationFailureTests(unittest.TestCase):
    def _assert_error(self, data: bytes, pattern: str):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.zip"
            path.write_bytes(data)
            with self.assertRaisesRegex(contracts.ContractError, pattern):
                SessionPackage.open(path)

    def test_unknown_length_unit(self):
        def mutate(session):
            session["units"]["length"] = "cm"
            return session

        data = rewrite(fixture_bytes(), {"session.json": edit_json(read_entries(fixture_bytes())["session.json"], mutate)})
        self._assert_error(data, "未知长度单位")

    def test_unknown_angle_unit(self):
        def mutate(session):
            session["units"]["angle"] = "deg"
            return session

        data = rewrite(fixture_bytes(), {"session.json": edit_json(read_entries(fixture_bytes())["session.json"], mutate)})
        self._assert_error(data, "未知角度单位")

    def test_unsupported_schema_version(self):
        def mutate(session):
            session["schema_version"] = "0.9.0"
            return session

        data = rewrite(fixture_bytes(), {"session.json": edit_json(read_entries(fixture_bytes())["session.json"], mutate)})
        self._assert_error(data, "不支持的 schema_version")

    def test_missing_manifest_file(self):
        # 清单仍登记该帧，但文件被删除 → 缺文件/缺帧
        data = rewrite(fixture_bytes(), {FRAME_7: None}, fix_manifest=False)
        self._assert_error(data, "在包内不存在")

    def test_missing_frame_after_manifest_fix(self):
        # 清单同步修复后，帧序列与配方不一致 → 缺帧
        def drop_frame(attempt):
            attempt["frames"] = attempt["frames"][:7] + attempt["frames"][8:]
            return attempt

        entries = read_entries(fixture_bytes())
        changes = {
            FRAME_7: None,
            ATTEMPT_JSON: edit_json(entries[ATTEMPT_JSON], drop_frame),
        }
        data = rewrite(fixture_bytes(), changes)
        self._assert_error(data, "帧序列与配方不一致.*缺少图案帧")

    def test_frame_hash_mismatch(self):
        # 长度保持一致、内容被篡改 → 大小检查通过，哈希检查报错
        data = rewrite(fixture_bytes(), {FRAME_7: b"\x00" * 3072}, fix_manifest=False)
        self._assert_error(data, "SHA-256 与清单不一致")

    def test_extra_unregistered_file(self):
        data = rewrite(fixture_bytes(), {"stray.txt": b"hello"}, fix_manifest=False)
        self._assert_error(data, "未登记文件")

    def test_transform_dimension_error(self):
        def mutate(obs):
            obs["preliminary_pose"]["T_L_C"]["rotation"] = [[1, 0], [0, 1]]
            return obs

        entries = read_entries(fixture_bytes())
        data = rewrite(fixture_bytes(), {OBSERVATIONS_JSON: edit_json(entries[OBSERVATIONS_JSON], mutate)})
        self._assert_error(data, "变换维度错误")

    def test_calibration_id_mismatch(self):
        def mutate(attempt):
            attempt["calibration_id"] = "cal-synthetic-0002"
            return attempt

        entries = read_entries(fixture_bytes())
        data = rewrite(fixture_bytes(), {ATTEMPT_JSON: edit_json(entries[ATTEMPT_JSON], mutate)})
        self._assert_error(data, "calibration_id.*标定/配置不匹配")

    def test_device_config_hash_mismatch(self):
        def mutate(device):
            device["device_config"]["display_brightness"] = 200
            return device

        entries = read_entries(fixture_bytes())
        data = rewrite(fixture_bytes(), {"device.json": edit_json(entries["device.json"], mutate)})
        self._assert_error(data, "device_config_hash 与 device_config 内容不匹配")

    def test_recipe_hash_mismatch(self):
        def mutate(recipe):
            recipe["patterns"][0]["frequency_cycles_per_pattern"] = 6
            return recipe

        entries = read_entries(fixture_bytes())
        data = rewrite(fixture_bytes(), {"recipe.json": edit_json(entries["recipe.json"], mutate)})
        self._assert_error(data, "recipe_hash 与配方内容不匹配")

    def test_frame_size_mismatch(self):
        def mutate(attempt):
            attempt["frames"][7]["width_px"] = 60
            return attempt

        entries = read_entries(fixture_bytes())
        data = rewrite(fixture_bytes(), {ATTEMPT_JSON: edit_json(entries[ATTEMPT_JSON], mutate)})
        self._assert_error(data, "帧尺寸 60x48 与设备流配置 64x48 不一致")

    def test_raw8_byte_length_mismatch(self):
        # 保持宽高声明，替换为错误长度的数据（manifest 同步修复以绕过哈希检查）
        data = rewrite(fixture_bytes(), {FRAME_7: b"\x00" * 100})
        self._assert_error(data, "raw8 帧数据字节数 100 与 64x48")

    def test_timestamp_as_number(self):
        def mutate(attempt):
            attempt["frames"][0]["sensor_timestamp_ns"] = 1773724800000000000
            return attempt

        entries = read_entries(fixture_bytes())
        data = rewrite(fixture_bytes(), {ATTEMPT_JSON: edit_json(entries[ATTEMPT_JSON], mutate)})
        self._assert_error(data, "十进制数字字符串")

    def test_session_complete_but_attempt_aborted(self):
        def mutate(attempt):
            attempt["capture_status"] = "aborted"
            return attempt

        entries = read_entries(fixture_bytes())
        data = rewrite(fixture_bytes(), {ATTEMPT_JSON: edit_json(entries[ATTEMPT_JSON], mutate)})
        self._assert_error(data, "会话标记 complete.*aborted")

    def test_duplicate_frame_pattern(self):
        def mutate(attempt):
            attempt["frames"][8] = dict(attempt["frames"][7])
            attempt["frames"][8]["frame_index"] = 8
            attempt["frames"][8]["file"] = "frames/0007.bin"
            return attempt

        entries = read_entries(fixture_bytes())
        data = rewrite(fixture_bytes(), {ATTEMPT_JSON: edit_json(entries[ATTEMPT_JSON], mutate)})
        self._assert_error(data, "帧序列与配方不一致")

    def test_missing_session_json(self):
        data = rewrite(fixture_bytes(), {"session.json": None})
        self._assert_error(data, "缺少 session.json")

    def test_malformed_json(self):
        data = rewrite(fixture_bytes(), {"device.json": b"{ not json"})
        self._assert_error(data, "JSON 解析失败")

    def test_calibration_reference_inconsistent(self):
        def mutate(session):
            session["calibration"]["calibration_id"] = "cal-other"
            return session

        entries = read_entries(fixture_bytes())
        data = rewrite(fixture_bytes(), {"session.json": edit_json(entries["session.json"], mutate)})
        self._assert_error(data, "calibration.calibration_id.*不一致")

    def test_coordinate_convention_wrong(self):
        def mutate(session):
            session["coordinate_conventions"]["transform"] = "T_B_A"
            return session

        entries = read_entries(fixture_bytes())
        data = rewrite(fixture_bytes(), {"session.json": edit_json(entries["session.json"], mutate)})
        self._assert_error(data, "变换方向约定错误")


class SampleRegenerationTests(unittest.TestCase):
    def test_regenerated_sample_is_deterministic(self):
        from mirror_core.sample import write_sample_session

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "regen.zip"
            write_sample_session(path)
            self.assertEqual(path.read_bytes(), fixture_bytes())


if __name__ == "__main__":
    unittest.main()
