"""``mirror_core.optics.cases`` 的单元测试:注册表、验证报告与导出。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mirror_core.contracts import ContractError
from mirror_core.optics import cases


class RegistryTest(unittest.TestCase):
    def test_case_names_stable(self):
        self.assertEqual(
            sorted(cases.CASES),
            [
                "cylinder_neg",
                "cylinder_pos",
                "cylinder_y",
                "plane",
                "ripple",
                "saddle",
                "sphere_neg",
                "sphere_pos",
                "tilted_plane",
            ],
        )

    def test_unknown_case_raises(self):
        with self.assertRaisesRegex(ContractError, "未知合成案例"):
            cases.case_definition("hyperbola")

    def test_expected_quadratic_present(self):
        for name, case in cases.CASES.items():
            self.assertEqual(len(case.expected_quadratic), 3, msg=name)


class VerificationTest(unittest.TestCase):
    """全部案例:verify_case 报告结构完整且验收项全部通过。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.reports = {
            name: cases.verify_case(cases.run_case(name)) for name in cases.CASES
        }

    def test_all_cases_pass(self):
        for name, report in self.reports.items():
            self.assertTrue(report["all_passed"], msg=f"{name}: {report['checks']}")

    def test_report_structure_and_units(self):
        # 验收"单位明确":报告与导出必须显式声明单位
        for name, report in self.reports.items():
            self.assertEqual(report["provenance"], "synthetic", msg=name)
            units = report["units"]
            self.assertEqual(units["length"], "m")
            self.assertEqual(units["angle"], "rad")
            self.assertIn("screen_coord", units)
            self.assertIn("max_normal_angle_error_rad", report["cross_validation"])
            self.assertIn("solver_notes", report)
            self.assertIn("height_constant_unobservable", report["solver_notes"])

    def test_plane_cases_report_no_fake_curvature(self):
        for name in ("plane", "tilted_plane"):
            names = [c["name"] for c in self.reports[name]["checks"]]
            self.assertIn("no_fake_curvature_on_plane", names, msg=name)

    def test_cylinder_reports_direction(self):
        for name in ("cylinder_pos", "cylinder_neg", "cylinder_y"):
            names = [c["name"] for c in self.reports[name]["checks"]]
            self.assertIn("direction_identifiable_90deg", names, msg=name)

    def test_sphere_reports_global_quadratic(self):
        for name in ("sphere_pos", "sphere_neg"):
            names = [c["name"] for c in self.reports[name]["checks"]]
            self.assertIn("global_quadratic_retained", names, msg=name)


class ExportTest(unittest.TestCase):
    def test_export_writes_deterministic_documents(self):
        run = cases.run_case("cylinder_pos")
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            dir1, dir2 = Path(tmp1), Path(tmp2)
            cases.export_case(run, dir1)
            cases.export_case(run, dir2)
            names = ["case.json", "forward.json", "replay.json", "verify.json"]
            self.assertEqual(
                sorted(p.name for p in dir1.iterdir()), sorted(names)
            )
            for name in names:
                self.assertEqual(
                    (dir1 / name).read_bytes(),
                    (dir2 / name).read_bytes(),
                    msg=f"{name} 应字节级确定",
                )

    def test_documents_declare_units_and_provenance(self):
        import json

        run = cases.run_case("plane")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            cases.export_case(run, output)
            for name in ("case.json", "forward.json", "replay.json"):
                doc = json.loads((output / name).read_text(encoding="utf-8"))
                self.assertEqual(doc["provenance"], "synthetic", msg=name)
                units = doc["units"]
                self.assertEqual(units["length"], "m", msg=name)
                self.assertEqual(units["screen_coord"], "normalized [0,1] over active screen rectangle", msg=name)
                self.assertIn("coordinate_frame", doc, msg=name)
            # §8.2:模型交点来源标注
            forward_doc = json.loads((output / "forward.json").read_text(encoding="utf-8"))
            self.assertEqual(
                forward_doc["point_geometry_provenance"], "model_intersection"
            )
            replay_doc = json.loads((output / "replay.json").read_text(encoding="utf-8"))
            self.assertEqual(
                replay_doc["point_geometry_provenance"], "model_intersection"
            )
            # 逐像素记录存在且有序
            self.assertGreater(len(forward_doc["observations"]), 0)
            self.assertEqual(len(replay_doc["pixels"]), len(forward_doc["observations"]))

    def test_export_refuses_file_output(self):
        run = cases.run_case("plane")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "not_a_dir"
            target.write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "不是目录"):
                cases.export_case(run, target)


if __name__ == "__main__":
    unittest.main()
