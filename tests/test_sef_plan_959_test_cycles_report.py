"""Regression tests for Plan 959 test cycle category classification."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "sef"
    / "build_plan_959_test_cycles_report.py"
)

_spec = importlib.util.spec_from_file_location("build_plan_959_test_cycles_report", _MODULE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Unable to load module: {_MODULE_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


class Plan959CategoryClassificationTests(unittest.TestCase):
    def test_parallel_summary_maps_to_parallel_run_testing(self) -> None:
        category = _mod._classify_category(
            key="PDE-TEST-1",
            issue_type="Story",
            summary="Testing | Parallel | Test Suite Preparation",
            test_type="",
        )
        self.assertEqual(category, "parallel run testing")

    def test_non_integrated_parallel_remains_distinct(self) -> None:
        category = _mod._classify_category(
            key="PDE-TEST-2",
            issue_type="Story",
            summary="Non Integrated Parallel | Data Seeding",
            test_type="",
        )
        self.assertEqual(category, "non integrated parallel")

    def test_integration_test_type_maps_to_integration_testing(self) -> None:
        category = _mod._classify_category(
            key="PDE-TEST-3",
            issue_type="Gate Level 1",
            summary="Integration Testing | Entry Gate",
            test_type="Integration",
        )
        self.assertEqual(category, "integration testing")

    def test_non_integrated_parallel_run_maps_to_nip(self) -> None:
        category = _mod._classify_category(
            key="PDE-TEST-4",
            issue_type="Story",
            summary="SEF | Phase 1 | HCM and Payroll | Test Plan | Non Integrated Payroll Parallel Run 1",
            test_type="Non Integrated Parallel",
        )
        self.assertEqual(category, "non integrated parallel")


if __name__ == "__main__":
    unittest.main()
