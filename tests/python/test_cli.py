"""mirror_cli 命令行行为测试（通过子进程调用真实入口）。"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .util import FIXTURE, fixture_bytes, rewrite

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(args: list[str]) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    parts = [str(REPO_ROOT / "python")] + ([existing] if existing else [])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    # 子进程输出强制 UTF-8，避免依赖宿主控制台代码页
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "mirror_cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=REPO_ROOT,
    )


class CliTests(unittest.TestCase):
    def test_validate_fixture_succeeds(self):
        result = _run(["validate", str(FIXTURE)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("契约校验通过", result.stdout)
        self.assertIn("synthetic", result.stdout)

    def test_validate_corrupt_package_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.zip"
            bad.write_bytes(rewrite(fixture_bytes(), {"device.json": b"{ broken"}, fix_manifest=False))
            result = _run(["validate", str(bad)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("契约校验失败", result.stderr)

    def test_validate_missing_file_fails(self):
        result = _run(["validate", str(REPO_ROOT / "no" / "such.zip")])
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr)

    def test_make_sample_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sample.zip"
            result = _run(["make-sample", "--output", str(out)])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(out.exists())
            check = _run(["validate", str(out)])
            self.assertEqual(check.returncode, 0, check.stderr)

    def test_solve_is_explicit_not_implemented(self):
        result = _run(["solve", str(FIXTURE), "--output", str(REPO_ROOT / "unused")])
        self.assertEqual(result.returncode, 2)
        self.assertIn("PR-07", result.stderr)

    def test_workbench_is_explicit_not_implemented(self):
        result = _run(["workbench", "--host", "127.0.0.1", "--port", "8765"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("PR-08", result.stderr)


if __name__ == "__main__":
    unittest.main()
