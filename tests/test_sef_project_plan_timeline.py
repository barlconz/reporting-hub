"""Tests for SEF integrated project plan Block Gantt scaffold."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from extensions.twoa_programme.sef_project_plan_reporting import (
    PhaseHubDiscovery,
    discover_phase_hub_issues,
    load_sef_project_plan_reporting_config,
)
from extensions.twoa_programme.sef_project_plan_timeline import (
    _issue_dimension_values,
    _build_hierarchy_from_flat,
    build_payload_filter_variants,
    build_sef_project_plan_report_html,
    filter_payload_by_dimension_value,
    resolve_chart_window_for_phases,
    sef_project_plan_timeline_svg,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sef-project-plan-timeline.json"
_REPO = Path(__file__).resolve().parents[1]


class SefProjectPlanTimelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    def test_config_loads_phase_hub_discovery(self) -> None:
        config = load_sef_project_plan_reporting_config(_REPO / "config" / "sef-project-plan-reporting.json")
        self.assertIsNotNone(config.phase_hub_discovery)
        assert config.phase_hub_discovery is not None
        self.assertIn("Block Level Two", config.phase_hub_discovery.jql or "")
        self.assertEqual(config.detail_issue_type, "Block Level Minus One")
        self.assertEqual(config.test_cycle_issue_type, "Test Cycle")
        self.assertIn("Meeting Gate", config.milestone_issue_types)
        self.assertEqual(config.filter_dimensions[0].id, "workstream")
        self.assertTrue(any(d.id == "tenant" for d in config.filter_dimensions))
        self.assertTrue(any(d.id == "environment" for d in config.filter_dimensions))
        self.assertTrue(any(d.id == "platforms" for d in config.filter_dimensions))
        self.assertTrue(any(d.id == "testTypes" for d in config.filter_dimensions))
        self.assertTrue(any(d.id == "smeCommitment" for d in config.filter_dimensions))
        self.assertEqual(config.pages_publish_path, "docs/sef/project-plan.html")

    def test_issue_dimension_values_extract_new_filter_fields(self) -> None:
        issue = {
            "fields": {
                "customfield_14734": {"value": "Tenant A"},
                "customfield_10408": [{"value": "TST"}, {"value": "PRD"}],
                "customfield_10046": [{"value": "HRIS"}],
                "customfield_10079": {"value": "Data"},
                "customfield_10145": [{"value": "Regression"}, {"value": "Smoke"}],
            }
        }
        self.assertEqual(_issue_dimension_values(issue, source_field="tenant"), ["Tenant A"])
        self.assertEqual(_issue_dimension_values(issue, source_field="environment"), ["TST", "PRD"])
        self.assertEqual(_issue_dimension_values(issue, source_field="platforms"), ["HRIS", "Data"])
        self.assertEqual(_issue_dimension_values(issue, source_field="testTypes"), ["Regression", "Smoke"])

    def test_chart_window_spans_full_project_delivery(self) -> None:
        start, end = resolve_chart_window_for_phases(self.payload["phases"])
        self.assertLessEqual(start.isoformat(), "2026-06-04")
        self.assertGreaterEqual(end.isoformat(), "2026-10-23")

    def test_svg_renders_phase_hub_chapters_streams_and_details(self) -> None:
        svg = sef_project_plan_timeline_svg(self.payload)
        self.assertIn("SEF Phase 1 | HCM and Payroll", svg)
        self.assertIn("PDE-4249", svg)
        self.assertIn("Mobilisation", svg)
        self.assertIn("Functional - HCM Stream", svg)
        self.assertIn("SIT cycle 1", svg)
        self.assertIn("PDE-4086", svg)
        self.assertIn("PDE-4078", svg)
        self.assertIn("<svg ", svg)
        self.assertIn('id="sef-x-axis-top"', svg)

    def test_html_report_shell(self) -> None:
        html_doc = build_sef_project_plan_report_html(
            self.payload,
            generated_on="01 Jan 2026 12:00 NZDT",
            page_title="SEF | Integrated Project Plan",
        )
        self.assertIn("SEF | Integrated Project Plan", html_doc)
        self.assertIn("chart-wrap-sef-plan", html_doc)
        self.assertIn("data-sef-filter-clear", html_doc)

    def test_timeline_bars_use_workstream_colours(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["phases"][0]["chapters"][1]["workstreams"] = ["Testing"]
        svg = sef_project_plan_timeline_svg(payload)
        self.assertIn('fill="#00875A"', svg)
        self.assertIn('fill="#7A869A"', svg)

    def test_svg_includes_today_marker_when_in_chart_window(self) -> None:
        svg = sef_project_plan_timeline_svg(self.payload)
        self.assertIn('class="chart-today-marker"', svg)
        self.assertIn('class="chart-today-line"', svg)

    def test_svg_renders_blocked_by_link_icon(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        chapter = payload["phases"][0]["chapters"][0]
        package = chapter["packages"][0]
        chapter["blockedByKeys"] = [package["key"]]

        svg = sef_project_plan_timeline_svg(payload)
        self.assertIn('class="sef-block-link-icon"', svg)
        self.assertIn('is blocked by', svg)
        self.assertIn('onclick="sefToggleBlockedFocus(', svg)

    def test_html_includes_blocked_focus_script(self) -> None:
        html_doc = build_sef_project_plan_report_html(
            self.payload,
            generated_on="01 Jan 2026 12:00 NZDT",
            page_title="SEF | Integrated Project Plan",
        )
        self.assertIn("window.sefToggleBlockedFocus", html_doc)
        self.assertIn("data-sef-dep-from", html_doc)
        self.assertIn("data-sef-key", html_doc)

    def test_discover_phase_hub_issues_skips_missing_configured_keys(self) -> None:
        from unittest.mock import MagicMock, patch

        from extensions.twoa_programme.sef_project_plan_reporting import SefProjectPlanReportingConfig

        config = SefProjectPlanReportingConfig(
            project_key="PDE",
            phase_hub_keys=("PDE-MISSING", "PDE-4249"),
            phase_hub_discovery=None,
            manifest_path=_REPO / "config" / "sef-project-plan-blocks.json",
            chart_window_start="2026-06-01",
            chart_window_end="2027-12-03",
            chapter_issue_type="Block Level One",
            package_issue_type="Block Level Zero",
            detail_issue_type="Block Level Minus One",
            test_cycle_issue_type="Test Cycle",
            scope_filter_id=None,
            scope_filter_name=None,
            timeline_artifact="sef-project-plan-timeline.json",
            html_artifact="sef-project-plan-chart.html",
            pages_publish_path="docs/sef/project-plan.html",
            pages_site_path="sef/project-plan.html",
            page_title="SEF | Integrated Project Plan",
            milestone_issue_types=("Meeting Gate", "Milestone"),
            filter_dimensions=(),
        )
        adapter = MagicMock()
        with patch(
            "extensions.twoa_programme.jira_search.search_all",
            return_value=[
                {
                    "key": "PDE-4249",
                    "fields": {"summary": "SEF Phase 1 | HCM and Payroll", "status": {"name": "To Do"}},
                }
            ],
        ):
            issues, warnings = discover_phase_hub_issues(adapter, config, fields=["summary", "status"])
        self.assertEqual([issue["key"] for issue in issues], ["PDE-4249"])
        self.assertTrue(any("PDE-MISSING" in warning for warning in warnings))

    def test_fetch_timeline_tolerates_empty_phase_discovery(self) -> None:
        from unittest.mock import MagicMock, patch

        from extensions.twoa_programme.sef_project_plan_reporting import SefProjectPlanReportingConfig
        from extensions.twoa_programme.sef_project_plan_timeline import fetch_sef_project_plan_timeline

        config = SefProjectPlanReportingConfig(
            project_key="PDE",
            phase_hub_keys=(),
            phase_hub_discovery=PhaseHubDiscovery(filter_id=None, filter_name=None, jql="project = PDE AND key = PDE-NONE"),
            manifest_path=_REPO / "config" / "sef-project-plan-blocks.json",
            chart_window_start="2026-06-01",
            chart_window_end="2027-12-03",
            chapter_issue_type="Block Level One",
            package_issue_type="Block Level Zero",
            detail_issue_type="Block Level Minus One",
            test_cycle_issue_type="Test Cycle",
            scope_filter_id=None,
            scope_filter_name=None,
            timeline_artifact="sef-project-plan-timeline.json",
            html_artifact="sef-project-plan-chart.html",
            pages_publish_path="docs/sef/project-plan.html",
            pages_site_path="sef/project-plan.html",
            page_title="SEF | Integrated Project Plan",
            milestone_issue_types=("Meeting Gate", "Milestone"),
            filter_dimensions=(),
        )
        adapter = MagicMock()
        with patch(
            "extensions.twoa_programme.jira_search.search_all",
            return_value=[],
        ):
            payload = fetch_sef_project_plan_timeline(adapter, config)
        self.assertEqual(payload["phases"], [])
        self.assertTrue(payload["warnings"])

    def test_build_hierarchy_orders_siblings_by_start_date(self) -> None:
        from datetime import date

        from extensions.twoa_programme.sef_project_plan_reporting import load_sef_project_plan_reporting_config

        config = load_sef_project_plan_reporting_config(_REPO / "config" / "sef-project-plan-reporting.json")
        issues = [
            {
                "key": "PDE-4249",
                "fields": {
                    "summary": "SEF Phase 1",
                    "issuetype": {"name": "Block Level Two"},
                    "customfield_10015": "2026-05-01",
                    "duedate": "2027-04-19",
                    "status": {"name": "To Do"},
                },
            },
            {
                "key": "PDE-5002",
                "fields": {
                    "summary": "Later chapter",
                    "issuetype": {"name": "Block Level One"},
                    "parent": {"key": "PDE-4249"},
                    "customfield_10015": "2026-08-01",
                    "duedate": "2026-09-01",
                    "status": {"name": "To Do"},
                },
            },
            {
                "key": "PDE-5001",
                "fields": {
                    "summary": "Earlier chapter",
                    "issuetype": {"name": "Block Level One"},
                    "parent": {"key": "PDE-4249"},
                    "customfield_10015": "2026-06-01",
                    "duedate": "2026-07-01",
                    "status": {"name": "To Do"},
                },
            },
        ]
        phases, _, _ = _build_hierarchy_from_flat(
            issues,
            config,
            fallback_start=date(2026, 6, 1),
            fallback_end=date(2027, 12, 31),
        )
        chapter_keys = [chapter["key"] for chapter in phases[0]["chapters"]]
        self.assertEqual(chapter_keys, ["PDE-5001", "PDE-5002"])

    def test_build_hierarchy_places_test_cycles_under_parent(self) -> None:
        from datetime import date

        from extensions.twoa_programme.sef_project_plan_reporting import load_sef_project_plan_reporting_config

        config = load_sef_project_plan_reporting_config(_REPO / "config" / "sef-project-plan-reporting.json")
        issues = [
            {
                "key": "PDE-4249",
                "fields": {
                    "summary": "SEF Phase 1",
                    "issuetype": {"name": "Block Level Two"},
                    "customfield_10015": "2026-05-01",
                    "duedate": "2027-04-19",
                    "status": {"name": "To Do"},
                },
            },
            {
                "key": "PDE-4609",
                "fields": {
                    "summary": "Testing | Parallel Testing",
                    "issuetype": {"name": "Block Level One"},
                    "parent": {"key": "PDE-4249"},
                    "customfield_10015": "2027-02-12",
                    "duedate": "2027-03-18",
                    "status": {"name": "To Do"},
                },
            },
            {
                "key": "PDE-4616",
                "fields": {
                    "summary": "Testing | Parallel Testing",
                    "issuetype": {"name": "Test Cycle"},
                    "parent": {"key": "PDE-4249"},
                    "customfield_10015": "2027-02-12",
                    "duedate": "2027-03-18",
                    "status": {"name": "To Do"},
                },
            },
            {
                "key": "PDE-5000",
                "fields": {
                    "summary": "Testing Stream",
                    "issuetype": {"name": "Block Level Zero"},
                    "parent": {"key": "PDE-4609"},
                    "customfield_10015": "2027-01-01",
                    "duedate": "2027-01-31",
                    "status": {"name": "To Do"},
                },
            },
            {
                "key": "PDE-5001",
                "fields": {
                    "summary": "Cycle A",
                    "issuetype": {"name": "Test Cycle"},
                    "parent": {"key": "PDE-4609"},
                    "customfield_10015": "2027-02-01",
                    "duedate": "2027-02-14",
                    "status": {"name": "To Do"},
                },
            },
            {
                "key": "PDE-5002",
                "fields": {
                    "summary": "Cycle B",
                    "issuetype": {"name": "Test Cycle"},
                    "parent": {"key": "PDE-5000"},
                    "customfield_10015": "2027-01-10",
                    "duedate": "2027-01-20",
                    "status": {"name": "To Do"},
                },
            },
        ]
        phases, _, _ = _build_hierarchy_from_flat(
            issues,
            config,
            fallback_start=date(2026, 6, 1),
            fallback_end=date(2027, 12, 31),
        )
        chapters = phases[0]["chapters"]
        chapter_keys = [chapter["key"] for chapter in chapters]
        self.assertEqual(chapter_keys, ["PDE-4609", "PDE-4616"])
        parallel_chapter = chapters[0]
        self.assertEqual(
            [row["key"] for row in parallel_chapter["packages"]],
            ["PDE-5000", "PDE-5001"],
        )
        self.assertEqual(parallel_chapter["packages"][0]["details"][0]["key"], "PDE-5002")
        self.assertEqual(parallel_chapter["packages"][0]["details"][0]["issueType"], "Test Cycle")
        hub_test_cycle = chapters[1]
        self.assertEqual(hub_test_cycle["issueType"], "Test Cycle")
        self.assertEqual(hub_test_cycle["packages"], [])

    def test_svg_renders_scope_overlay_when_scope_rollup_present(self) -> None:
        svg = sef_project_plan_timeline_svg(self.payload)
        self.assertIn('class="block-scope-segment"', svg)

    def test_svg_renders_payload_milestone_overlays(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["milestones"] = [
            {
                "key": "PDE-9999",
                "summary": "Gate Alpha",
                "startDate": "2026-07-14",
                "isMeetingGate": True,
            }
        ]
        svg = sef_project_plan_timeline_svg(payload)
        self.assertIn("Gate Alpha", svg)
        self.assertIn("(14/07)", svg)

    def test_build_hierarchy_includes_meeting_gate_milestones(self) -> None:
        from datetime import date

        config = load_sef_project_plan_reporting_config(_REPO / "config" / "sef-project-plan-reporting.json")
        issues = [
            {
                "key": "PDE-4249",
                "fields": {
                    "summary": "SEF Phase 1",
                    "issuetype": {"name": "Block Level Two"},
                    "customfield_10015": "2026-06-01",
                    "duedate": "2026-12-31",
                    "status": {"name": "To Do"},
                },
            },
            {
                "key": "PDE-5000",
                "fields": {
                    "summary": "Testing Stream",
                    "issuetype": {"name": "Block Level One"},
                    "parent": {"key": "PDE-4249"},
                    "customfield_10015": "2026-06-10",
                    "duedate": "2026-07-15",
                    "status": {"name": "To Do"},
                },
            },
            {
                "key": "PDE-5001",
                "fields": {
                    "summary": "Gate 1",
                    "issuetype": {"name": "Meeting Gate", "iconUrl": "/images/icons/mg.svg"},
                    "parent": {"key": "PDE-5000"},
                    "customfield_10015": "2026-06-20",
                    "duedate": "2026-06-20",
                    "status": {"name": "To Do"},
                },
            },
        ]
        phases, _, _ = _build_hierarchy_from_flat(
            issues,
            config,
            fallback_start=date(2026, 6, 1),
            fallback_end=date(2026, 12, 31),
        )
        milestone = phases[0]["chapters"][0]["packages"][0]
        self.assertEqual(milestone["issueType"], "Meeting Gate")
        self.assertTrue(milestone["isMeetingGate"])
        self.assertEqual(milestone["issueTypeIconUrl"], "/images/icons/mg.svg")

    def test_workstream_filter_preserves_matching_hierarchy(self) -> None:
        payload = {
            "chartWindowStart": "2026-06-01",
            "chartWindowEnd": "2026-12-31",
            "filterDimensions": [
                {"id": "workstream", "label": "Workstream", "sourceField": "workstreams", "options": ["HCM", "Payroll"]}
            ],
            "phases": [
                {
                    "key": "PDE-1",
                    "summary": "Phase",
                    "startDate": "2026-06-01",
                    "endDate": "2026-12-31",
                    "chapters": [
                        {
                            "key": "PDE-2",
                            "summary": "Chapter",
                            "startDate": "2026-06-01",
                            "endDate": "2026-09-01",
                            "workstreams": ["HCM"],
                            "packages": [
                                {
                                    "key": "PDE-3",
                                    "summary": "Package",
                                    "startDate": "2026-06-10",
                                    "endDate": "2026-08-01",
                                    "workstreams": ["HCM"],
                                    "details": [
                                        {
                                            "key": "PDE-4",
                                            "summary": "Detail",
                                            "startDate": "2026-06-12",
                                            "endDate": "2026-06-30",
                                            "workstreams": ["HCM"],
                                        }
                                    ],
                                },
                                {
                                    "key": "PDE-5",
                                    "summary": "Payroll Package",
                                    "startDate": "2026-07-01",
                                    "endDate": "2026-08-15",
                                    "workstreams": ["Payroll"],
                                    "details": [],
                                },
                            ],
                        }
                    ],
                }
            ],
        }
        filtered = filter_payload_by_dimension_value(payload, dimension_id="workstream", value="Payroll")
        packages = filtered["phases"][0]["chapters"][0]["packages"]
        self.assertEqual([row["key"] for row in packages], ["PDE-5"])

    def test_filter_variants_include_all_and_workstream_values(self) -> None:
        payload = {
            "chartWindowStart": "2026-06-01",
            "chartWindowEnd": "2026-12-31",
            "filterDimensions": [
                {"id": "workstream", "label": "Workstream", "sourceField": "workstreams", "options": ["HCM", "Payroll"]}
            ],
            "phases": self.payload.get("phases") or [],
        }
        variants = build_payload_filter_variants(payload)
        keys = {variant["key"] for variant in variants}
        self.assertIn("__all__", keys)
        self.assertIn("workstream:HCM", keys)
        self.assertIn("workstream:Payroll", keys)


if __name__ == "__main__":
    unittest.main()
