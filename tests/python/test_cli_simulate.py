"""``mirror_cli simulate`` 子命令行为测试(子进程调用真实入口)。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(args: list[str]) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    parts = [str(REPO_ROOT / "python")] + ([existing] if existing else [])
    env["PYTHONPATH"] = os.pathsep.join(parts)
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


class SimulateCommandTest(unittest.TestCase):
    def test_simulate_exports_and_passes_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            result = _run(["simulate", "--case", "cylinder_neg", "--output", str(output)])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("合成案例已执行并导出", result.stdout)
            for name in ("case.json", "forward.json", "replay.json", "verify.json"):
                self.assertTrue((output / name).is_file(), msg=name)
            verify = json.loads(
                (output / "verify.json").read_text(encoding="utf-8")
            )
            self.assertTrue(verify["all_passed"])
            self.assertEqual(verify["case"], "cylinder_neg")

    def test_simulate_deterministic_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out1 = Path(tmp) / "run1"
            out2 = Path(tmp) / "run2"
            first = _run(["simulate", "--case", "tilted_plane", "--output", str(out1)])
            second = _run(["simulate", "--case", "tilted_plane", "--output", str(out2)])
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            for name in ("case.json", "forward.json", "replay.json", "verify.json"):
                self.assertEqual(
                    (out1 / name).read_bytes(),
                    (out2 / name).read_bytes(),
                    msg=f"{name} 应字节级确定",
                )

    def test_unknown_case_fails_with_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(["simulate", "--case", "nope", "--output", str(Path(tmp) / "o")])
            self.assertEqual(result.returncode, 1)
            self.assertIn("未知合成案例", result.stderr)


if __name__ == "__main__":
    unittest.main()
