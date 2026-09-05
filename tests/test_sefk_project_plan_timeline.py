"""Tests for SEFK integrated project plan Gantt."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from extensions.twoa_programme.sefk_project_plan_reporting import load_sefk_project_plan_reporting_config
from extensions.twoa_programme.sefk_project_plan_timeline import (
    SEFK_EPIC_LABEL_X,
    SEFK_PHASE_LABEL_X,
    _bubble_scope_rollups,
    _build_sefk_hierarchy_from_flat,
    _merge_scope_rollups,
    _sefk_bar_fill,
    _sefk_render_scope_overlay,
    _sefk_work_stream_display_label,
    _sort_sub_phase_sibling_keys,
    build_sefk_project_plan_report_html,
    resolve_chart_window_for_phases,
    sefk_dtrain_key_html,
    sefk_project_plan_timeline_svg,
    sub_phase_order_index,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sefk-project-plan-timeline.json"
_REPO = Path(__file__).resolve().parents[1]


class SefkProjectPlanTimelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    def test_config_loads(self) -> None:
        config = load_sefk_project_plan_reporting_config(_REPO / "config" / "sefk-project-plan-reporting.json")
        self.assertEqual(config.project_key, "SEFK")
        self.assertEqual(config.sub_phase_issue_type, "Sub-Phase")
        self.assertEqual(config.work_stream_issue_type, "Work Stream")
        self.assertEqual(config.epic_issue_type, "Epic")
        self.assertEqual(config.scope_filter_name, "smart-project-sefk")
        self.assertIn("Task", config.scope_issue_types)
        self.assertIn("Milestone Level Zero", config.scope_issue_types)
        self.assertEqual(config.status_dtrain.get("Completed"), "Drive")
        self.assertIn("issuetype = Phase", config.phase_hub_discovery.jql or "")
        self.assertEqual(config.pages_publish_path, "docs/sefk/project-plan.html")
        self.assertEqual(
            config.sub_phase_order,
            ("Mobilisation", "Architecture", "Test", "Cross Phases", "Deploy"),
        )

    def test_sub_phase_order_sorts_configured_summaries(self) -> None:
        order = ("Mobilisation", "Architecture", "Test", "Cross Phases", "Deploy")
        by_key = {
            "SEFK-26": {"key": "SEFK-26", "fields": {"summary": "Deploy"}},
            "SEFK-27": {"key": "SEFK-27", "fields": {"summary": "Mobilisation and Planning"}},
            "SEFK-25": {"key": "SEFK-25", "fields": {"summary": "Architecture and Configure"}},
            "SEFK-1210": {"key": "SEFK-1210", "fields": {"summary": "Test"}},
            "SEFK-1307": {"key": "SEFK-1307", "fields": {"summary": "Cross Phases"}},
        }
        ordered = _sort_sub_phase_sibling_keys(list(by_key.keys()), by_key, order)
        self.assertEqual(ordered, ["SEFK-27", "SEFK-25", "SEFK-1210", "SEFK-1307", "SEFK-26"])
        self.assertEqual(sub_phase_order_index(by_key["SEFK-25"], order), 1)
        self.assertEqual(sub_phase_order_index({"fields": {"summary": "Architect & Configure"}}, order), 1)

    def test_sub_phase_order_prefers_run_order(self) -> None:
        order = ("Mobilisation", "Architecture", "Test", "Cross Phases", "Deploy")
        by_key = {
            "SEFK-26": {
                "key": "SEFK-26",
                "fields": {"summary": "Deploy", "customfield_10541": 1},
            },
            "SEFK-27": {
                "key": "SEFK-27",
                "fields": {"summary": "Mobilisation", "customfield_10541": 3},
            },
            "SEFK-25": {
                "key": "SEFK-25",
                "fields": {"summary": "Architecture", "customfield_10541": 2},
            },
        }
        ordered = _sort_sub_phase_sibling_keys(list(by_key.keys()), by_key, order)
        self.assertEqual(ordered, ["SEFK-26", "SEFK-25", "SEFK-27"])

    def test_chart_window_spans_fixture_dates(self) -> None:
        start, end = resolve_chart_window_for_phases(self.payload["phases"])
        self.assertLessEqual(start.isoformat(), "2026-06-04")
        self.assertGreaterEqual(end.isoformat(), "2026-10-23")

    def test_svg_renders_four_hierarchy_layers(self) -> None:
        svg = sefk_project_plan_timeline_svg(self.payload)
        self.assertIn("SEFK Phase 1 | Student Experience", svg)
        self.assertIn('class="chart-week-month-grid"', svg)
        self.assertIn('id="sefk-grid-lines"', svg)
        self.assertIn("data-grid=", svg)
        self.assertIn("Week start:", svg)
        self.assertIn("Month start:", svg)
        self.assertIn("Mobilisation", svg)
        self.assertIn("Functional Stream", svg)
        self.assertIn("Establish student profile foundations", svg)
        self.assertIn("EPCE-8001", svg)
        self.assertIn("<svg ", svg)
        self.assertIn('id="sefk-chev-sp-', svg)
        self.assertIn('id="sefk-cm-sp"', svg)
        self.assertIn('id="sefk-cfg"', svg)
        self.assertIn('id="sefk-x-axis"', svg)
        self.assertIn('data-parent-map=', svg)
        self.assertIn('&quot;baseSubH&quot;', svg)
        self.assertIn('data-level-zero-base-h=', svg)
        self.assertIn('data-level-zero-row-h=', svg)
        self.assertIn('data-status-dtrain-map=', svg)

    def test_svg_includes_work_stream_chevron_when_epics_present(self) -> None:
        svg = sefk_project_plan_timeline_svg(self.payload)
        self.assertIn('id="sefk-chev-ws-', svg)
        self.assertIn('id="sefk-sub-ws-', svg)

    def test_svg_renders_level_zero_row_wrapper(self) -> None:
        epic = self.payload["phases"][0]["subPhases"][0]["workStreams"][0]["epics"][0]
        epic["levelZero"] = [
            {
                "key": "EPCE-9001",
                "summary": "Draft profile schema",
                "issueType": "Task",
                "status": "Doing",
                "startDate": epic["startDate"],
                "endDate": epic["endDate"],
            }
        ]
        svg = sefk_project_plan_timeline_svg(self.payload)
        self.assertIn('class="sefk-level-zero-row"', svg)
        self.assertIn('data-level-zero-key="EPCE-9001"', svg)
        self.assertIn('data-epic-key="EPCE-8001"', svg)

    def test_svg_renders_issue_type_icons(self) -> None:
        self.payload["phases"][0]["issueTypeIconUrl"] = "https://twoa.atlassian.net/icon/phase.png"
        self.payload["phases"][0]["subPhases"][0]["issueTypeIconUrl"] = "https://twoa.atlassian.net/icon/sub-phase.png"
        self.payload["phases"][0]["subPhases"][0]["workStreams"][0]["issueTypeIconUrl"] = "https://twoa.atlassian.net/icon/work-stream.png"
        self.payload["phases"][0]["subPhases"][0]["workStreams"][0]["epics"][0]["issueTypeIconUrl"] = "https://twoa.atlassian.net/icon/epic.png"

        svg = sefk_project_plan_timeline_svg(self.payload)

        self.assertEqual(svg.count('data-sefk-icon="1"'), 4)
        self.assertIn(f'<text x="{SEFK_PHASE_LABEL_X:.1f}"', svg)

    def test_svg_uses_dedicated_icons_for_milestone_and_gate_levels(self) -> None:
        epics = self.payload["phases"][0]["subPhases"][0]["workStreams"][0]["epics"]
        epics[0]["issueType"] = "Milestone Level One"
        epics[0]["levelZero"] = [
            {
                "key": "SEFK-GATE-1",
                "summary": "Approval gate",
                "status": "Open",
                "startDate": "2026-06-10",
                "endDate": "2026-06-10",
                "issueType": "Gate Level One",
                "issueTypeIconUrl": "https://twoa.atlassian.net/icon/gate.png",
            }
        ]

        svg = sefk_project_plan_timeline_svg(self.payload)

        self.assertIn('<polygon points=', svg)
        self.assertIn('fill="#de350b"', svg)
        self.assertIn('href="https://twoa.atlassian.net/icon/gate.png"', svg)
        self.assertIn('data-sef-issue-type="Milestone Level One" data-sef-special="milestone"', svg)
        self.assertIn('data-sef-issue-type="Gate Level One" data-sef-special="gate"', svg)

    def test_svg_renders_dependency_marker_for_linked_sefk_epics(self) -> None:
        epics = self.payload["phases"][0]["subPhases"][0]["workStreams"][0]["epics"]
        blocker = epics[0]
        blocked = dict(blocker)
        blocked["key"] = "SEFK-DEPENDENT"
        blocked["summary"] = "Dependent epic"
        blocked["blockedByKeys"] = [blocker["key"]]
        epics.append(blocked)

        svg = sefk_project_plan_timeline_svg(self.payload)

        self.assertIn('data-sef-key="' + blocker["key"] + '" data-sef-row="1" data-sef-role="epic-bar"', svg)
        self.assertIn('data-sef-has-dependency="1"', svg)
        self.assertNotIn('class="sef-block-link-icon"', svg)
        self.assertIn(f'data-sef-dep-from="{blocker["key"]}" data-sef-dep-to="SEFK-DEPENDENT"', svg)
        self.assertIn('class="sefk-dependency-connector"', svg)
        self.assertIn('class="sefk-dependency-hit-area"', svg)
        self.assertIn(f"Dependency: {blocker['key']} blocks SEFK-DEPENDENT", svg)
        self.assertIn('<circle ', svg)
        self.assertIn(' C ', svg)
        self.assertIn('marker-end="url(#dep-arrow)"', svg)

    def test_svg_renders_level_zero_rows_under_epics(self) -> None:
        epic = self.payload["phases"][0]["subPhases"][0]["workStreams"][0]["epics"][0]
        epic["levelZero"] = [
            {
                "key": "SEFK-LEVEL0",
                "summary": "Level 0 delivery task",
                "status": "In Progress",
                "startDate": "2026-06-10",
                "endDate": "2026-06-20",
                "issueType": "Task",
            }
        ]

        svg = sefk_project_plan_timeline_svg(self.payload)

        self.assertIn("Level 0 delivery task", svg)
        self.assertIn('data-sef-key="SEFK-LEVEL0" data-sef-row="1" data-sef-role="level-zero-bar"', svg)
        self.assertIn('id="sefk-sub-epic-', svg)
        self.assertIn('visibility="hidden" style="display:none"', svg)
        self.assertIn(f'x="{SEFK_EPIC_LABEL_X - 24:.1f}"', svg)

    def test_work_stream_labels_use_horizontal_clip_inside_transforms(self) -> None:
        svg = sefk_project_plan_timeline_svg(self.payload)
        marker = 'id="sefk-ws-PDE-5003"'
        start = svg.find(marker)
        self.assertGreater(start, -1)
        end = svg.find('id="sefk-ws-', start + 1)
        block = svg[start:end] if end > start else svg[start : start + 4000]
        self.assertIn("Functional Stream", block)
        self.assertIn('clip-path="url(#sef-plan-label-col-x)"', block)

    def test_work_stream_display_label_strips_sub_phase_prefix(self) -> None:
        sub_phase = {"summary": "Architecture and Configure"}
        work_stream = {"summary": "Architecture and Configure | data-migration"}
        self.assertEqual(
            _sefk_work_stream_display_label(work_stream, sub_phase),
            "data migration",
        )

    def test_bar_without_scope_story_points_uses_status_dtrain_colour(self) -> None:
        row = {"status": "Not Started"}
        fill = _sefk_bar_fill(row)
        self.assertEqual(fill.lower(), "#de350b")
        self.assertFalse(_sefk_render_scope_overlay(row))

    def test_bar_with_scope_story_points_uses_composition_overlay(self) -> None:
        row = {
            "status": "Not Started",
            "scopeRollup": {"storyPoints": 3.0, "totalWeight": 3.0, "phases": {"Dream": 3.0}},
        }
        self.assertTrue(_sefk_render_scope_overlay(row))
        self.assertNotEqual(_sefk_bar_fill(row), "#de350b")

    def test_svg_uses_dtrain_palette_on_bars(self) -> None:
        svg = sefk_project_plan_timeline_svg(self.payload)
        self.assertIn("#00875a", svg.lower())
        self.assertIn("#de350b", svg.lower())

    def test_html_report_uses_milestone_style_shell(self) -> None:
        html_doc = build_sefk_project_plan_report_html(
            self.payload,
            generated_on="01 Jan 2026 12:00 NZDT",
            page_title="SEFK | Integrated Project Plan",
        )
        self.assertIn("SEFK | Integrated Project Plan", html_doc)
        self.assertIn("report-shell", html_doc)
        self.assertIn("chart-wrap-sefk", html_doc)
        self.assertIn("chart-key--dtrain", html_doc)
        self.assertIn("D-Train phases left to right", html_doc)
        self.assertIn("sefkToggleSubPhase", html_doc)
        self.assertIn("sefkToggleWorkStream", html_doc)
        self.assertIn("sefkToggleEpic", html_doc)
        self.assertIn("[id^=\"sefk-sub-epic-\"]", html_doc)
        self.assertIn("sefkShowPhaseLevel", html_doc)
        self.assertIn("sefkShowWorkStreamLevel", html_doc)
        self.assertIn("sefkShowEpicLevel", html_doc)
        self.assertIn('data-hierarchy-level="workstream"', html_doc)
        self.assertIn("reflowWorkStreamEpics", html_doc)
        self.assertIn("cumulativeShift += currentSubH - baseSubH", html_doc)
        self.assertIn("svg.getElementById('sefk-x-axis')", html_doc)
        self.assertIn("function refreshDependencyGeometry", html_doc)
        self.assertIn("path.setAttribute('d', pathD)", html_doc)
        self.assertIn("dependencyParentMap", html_doc)
        self.assertIn("node.style.opacity = visibleKeys[key] ? '1' : '0.16'", html_doc)
        self.assertIn("'[data-sef-special=\"' + kind + '\"]'", html_doc)
        self.assertIn("expandHierarchyPath", html_doc)
        self.assertIn("restoreHierarchyExpansionState", html_doc)
        self.assertIn("bindDependencyHover", html_doc)
        self.assertIn("sefk-dependency-related", html_doc)
        self.assertIn("collapse or expand", html_doc)

    def test_dtrain_key_lists_phases(self) -> None:
        key_html = sefk_dtrain_key_html()
        self.assertIn("Drive", key_html)
        self.assertIn("Dream", key_html)

    def test_merge_scope_rollups_sums_child_weights(self) -> None:
        child_a = {
            "phases": {"Drive": 5.0, "Discover": 3.0},
            "phaseIssueKeys": {"Drive": ["A"], "Discover": ["B"]},
            "unpointedCount": 0,
            "unpointedIssueKeys": [],
            "storyPoints": 8.0,
            "totalWeight": 8.0,
        }
        child_b = {
            "phases": {"Drive": 2.0},
            "phaseIssueKeys": {"Drive": ["C"]},
            "unpointedCount": 1,
            "unpointedIssueKeys": ["D"],
            "storyPoints": 2.0,
            "totalWeight": 3.0,
        }
        merged = _merge_scope_rollups([child_a, child_b])
        assert merged is not None
        self.assertEqual(merged["storyPoints"], 10.0)
        self.assertEqual(merged["totalWeight"], 11.0)
        self.assertEqual(merged["phases"]["Drive"], 7.0)

    def test_bubble_scope_rollups_populates_parent_rows(self) -> None:
        phases = json.loads(json.dumps(self.payload["phases"]))
        for phase in phases:
            phase.pop("scopeRollup", None)
            for sub_phase in phase.get("subPhases") or []:
                sub_phase.pop("scopeRollup", None)
                for work_stream in sub_phase.get("workStreams") or []:
                    work_stream.pop("scopeRollup", None)
        _bubble_scope_rollups(phases)
        self.assertIn("scopeRollup", phases[0]["subPhases"][0]["workStreams"][0])
        self.assertIn("scopeRollup", phases[0]["subPhases"][0])


    def test_build_hierarchy_from_flat_issue_list(self) -> None:
        config = load_sefk_project_plan_reporting_config(_REPO / "config" / "sefk-project-plan-reporting.json")
        issues = [
            {
                "key": "PDE-9001",
                "fields": {
                    "summary": "SEFK Phase 1",
                    "issuetype": {"name": "Phase"},
                    "status": {"name": "To Do"},
                    "customfield_10015": "2026-06-01",
                    "duedate": "2027-06-01",
                },
            },
            {
                "key": "PDE-9002",
                "fields": {
                    "summary": "Mobilisation",
                    "issuetype": {"name": "Sub-Phase"},
                    "status": {"name": "To Do"},
                    "parent": {"key": "PDE-9001"},
                    "customfield_10015": "2026-06-01",
                    "duedate": "2026-07-01",
                },
            },
            {
                "key": "PDE-9003",
                "fields": {
                    "summary": "Functional Stream",
                    "issuetype": {"name": "Work Stream"},
                    "status": {"name": "To Do"},
                    "parent": {"key": "PDE-9002"},
                    "customfield_10015": "2026-06-04",
                    "duedate": "2026-07-15",
                },
            },
            {
                "key": "EPCE-9001",
                "fields": {
                    "summary": "Student profile epic",
                    "issuetype": {"name": "Epic"},
                    "status": {"name": "Doing"},
                    "parent": {"key": "PDE-9003"},
                    "customfield_10015": "2026-06-04",
                    "duedate": "2026-07-10",
                },
            },
        ]
        from datetime import date

        phases, hub_keys, warnings, block_issues, epic_issues = _build_sefk_hierarchy_from_flat(
            issues,
            config,
            fallback_start=date(2026, 6, 1),
            fallback_end=date(2027, 12, 31),
        )
        self.assertEqual(hub_keys, ["PDE-9001"])
        self.assertEqual(len(phases), 1)
        self.assertEqual(phases[0]["subPhases"][0]["workStreams"][0]["epics"][0]["key"], "EPCE-9001")
        self.assertIn("PDE-9003", block_issues)
        self.assertIn("EPCE-9001", epic_issues)
        self.assertEqual(warnings, [])

    def test_build_hierarchy_skips_kpmg_deleted_issues(self) -> None:
        config = load_sefk_project_plan_reporting_config(_REPO / "config" / "sefk-project-plan-reporting.json")
        issues = [
            {
                "key": "SEFK-1",
                "fields": {
                    "summary": "Phase",
                    "issuetype": {"name": "Phase"},
                    "status": {"name": "Open"},
                    "customfield_10015": "2026-06-01",
                    "duedate": "2027-06-01",
                },
            },
            {
                "key": "SEFK-2",
                "fields": {
                    "summary": "Deleted epic",
                    "issuetype": {"name": "Epic"},
                    "status": {"name": "Closed"},
                    "labels": ["kpmg-deleted"],
                    "parent": {"key": "SEFK-1"},
                    "customfield_10015": "2026-06-01",
                    "duedate": "2026-07-01",
                },
            },
        ]
        from datetime import date

        phases, hub_keys, warnings, block_issues, epic_issues = _build_sefk_hierarchy_from_flat(
            issues,
            config,
            fallback_start=date(2026, 6, 1),
            fallback_end=date(2027, 12, 31),
        )
        self.assertEqual(hub_keys, ["SEFK-1"])
        self.assertEqual(phases[0]["subPhases"], [])
        self.assertNotIn("SEFK-2", epic_issues)
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
