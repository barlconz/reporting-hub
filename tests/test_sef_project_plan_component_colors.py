"""Tests for SEF project plan workstream colour mapping."""

from __future__ import annotations

import unittest
from pathlib import Path

from extensions.twoa_programme.sef_project_plan_component_colors import (
    load_sef_project_plan_component_colors,
    workstream_names_from_issue,
)

_REPO = Path(__file__).resolve().parents[1]


class SefProjectPlanComponentColorsTests(unittest.TestCase):
    def test_loads_jira_plans_palette(self) -> None:
        colors = load_sef_project_plan_component_colors(_REPO / "config" / "sef-project-plan-component-colors.json")
        self.assertEqual(colors.default_fill, "#7A869A")
        self.assertEqual(colors.workstreams["Payroll"], "#FFE380")
        self.assertEqual(colors.workstreams["Testing"], "#00875A")
        self.assertEqual(colors.workstreams["Change"], "#998DD9")

    def test_fill_for_row_uses_first_matching_workstream(self) -> None:
        colors = load_sef_project_plan_component_colors(_REPO / "config" / "sef-project-plan-component-colors.json")
        self.assertEqual(colors.fill_for_row({"workstreams": ["HCM"]}), "#FF8B66")
        self.assertEqual(colors.fill_for_row({"workstreams": ["Change"]}), "#998DD9")
        self.assertEqual(colors.fill_for_row({"workstreams": []}), "#7A869A")
        self.assertEqual(colors.fill_for_row({}), "#7A869A")

    def test_fill_for_row_maps_slugged_workstreams(self) -> None:
        colors = load_sef_project_plan_component_colors(_REPO / "config" / "sef-project-plan-component-colors.json")
        self.assertEqual(colors.fill_for_row({"workstreams": ["data-migration"]}), "#0052CC")
        self.assertEqual(colors.fill_for_row({"workstreams": ["people-and-change"]}), "#998DD9")

    def test_workstream_names_from_issue_prefers_workstream_field(self) -> None:
        issue = {
            "fields": {
                "customfield_12291": [{"value": "Deployment"}, {"name": "People"}, "Data"],
                "components": [{"name": "Legacy Component"}],
            }
        }
        self.assertEqual(workstream_names_from_issue(issue), ["Deployment", "People", "Data"])

    def test_workstream_names_from_issue_falls_back_to_components(self) -> None:
        issue = {
            "fields": {
                "customfield_12291": None,
                "components": [{"name": "Payroll"}, {"name": "Testing"}],
            }
        }
        self.assertEqual(workstream_names_from_issue(issue), ["Payroll", "Testing"])


if __name__ == "__main__":
    unittest.main()
