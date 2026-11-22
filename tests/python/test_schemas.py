"""JSON Schema 一致性测试（可选依赖 jsonschema）。

schemas/ 是两端共同的规范文档；本测试在安装了 jsonschema 的环境
（如 CI）中验证范例包内每个 JSON 文件都符合对应 Schema，
防止 Schema 与代码实现漂移。未安装时跳过。
"""

import json
import unittest
from pathlib import Path

from .util import fixture_bytes, read_entries

try:
    import jsonschema
except ImportError:  # pragma: no cover - 环境未安装时跳过
    jsonschema = None

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "schemas"

#: 包内路径 -> Schema 文件
SCHEMA_MAP = {
    "session.json": "session/session.schema.json",
    "device.json": "session/device.schema.json",
    "calibration/index.json": "session/calibration-index.schema.json",
    "layout.json": "session/layout.schema.json",
    "recipe.json": "session/recipe.schema.json",
    "experiment.json": "session/experiment.schema.json",
    "patches/P0001/attempts/A001/attempt.json": "session/attempt.schema.json",
    "patches/P0001/attempts/A001/observations.json": "session/observations.schema.json",
}

# calibration 条目文件只需要是合法 JSON，Schema 由具体条目在后续 PR 细化
CALIBRATION_ITEM_PATHS = {
    "calibration/camera_intrinsics.json",
    "calibration/screen_mapping.json",
    "calibration/response.json",
    "calibration/timing.json",
}


@unittest.skipIf(jsonschema is None, "未安装 jsonschema，跳过 Schema 一致性检查")
class SchemaConformanceTests(unittest.TestCase):
    def test_fixture_matches_schemas(self):
        entries = read_entries(fixture_bytes())
        validator = jsonschema.Draft202012Validator
        checked = 0
        for path, schema_rel in SCHEMA_MAP.items():
            schema = json.loads((SCHEMA_DIR / schema_rel).read_text(encoding="utf-8"))
            instance = json.loads(entries[path])
            errors = sorted(validator(schema).iter_errors(instance), key=lambda e: list(e.path))
            if errors:
                first = errors[0]
                location = "/".join(str(p) for p in first.path) or "<root>"
                self.fail(f"{path} 不符合 {schema_rel}（{location}: {first.message}）")
            checked += 1
        # 其余 calibration 条目必须至少是可解析的 JSON 对象
        for path in CALIBRATION_ITEM_PATHS:
            self.assertIsInstance(json.loads(entries[path]), dict)
        self.assertGreater(checked, 0)

    def test_result_job_schema_states(self):
        """job.schema.json 定义的状态枚举必须与 mirror_core.contracts 一致。"""
        from mirror_core import contracts

        schema = json.loads((SCHEMA_DIR / "results" / "job.schema.json").read_text(encoding="utf-8"))
        props = schema["properties"]
        self.assertEqual(set(props["status"]["enum"]), set(contracts.JOB_STATUSES))
        self.assertEqual(set(props["support_status"]["enum"]), set(contracts.SUPPORT_STATUSES))


if __name__ == "__main__":
    unittest.main()
