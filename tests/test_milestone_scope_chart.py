"""Tests for milestone scope composition chart."""

from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from artifact.jira_binding import JiraBinding

from extensions.twoa_programme.milestone_scope_chart import (
    build_milestone_scope_blocks,
    build_milestone_scope_html,
    build_milestone_scope_rows,
    chart_dtrain_phases,
    chart_max_lane_weight,
    lane_bar_segments,
    milestone_scope_segment_jql,
    milestone_scope_svg,
    resolve_issue_dtrain_phase,
    rollup_milestone_lane_phases,
    timeline_bar_segment_order,
    _format_lane_total,
    _UNPOINTED_SEGMENT,
    _wrap_text_lines,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "milestone-scope-chart.json"
_BINDING = JiraBinding.from_file(Path(__file__).resolve().parents[1] / "config" / "jira-binding.json")


def _fields(
    *,
    squads: list[str] | None = None,
    change_types: list[str] | None = None,
    platform: str | None = None,
    sp: float | None = 5.0,
    status: str = "Doing",
) -> dict:
    return {
        "issuetype": {"name": "Story"},
        "status": {"name": status},
        "customfield_11102": [{"value": v} for v in (squads or [])],
        "customfield_10079": [{"value": v} for v in (change_types or [])],
        "customfield_10120": {"value": platform} if platform else None,
        "customfield_10026": sp,
        "issuelinks": [],
    }


class MilestoneScopeChartTests(unittest.TestCase):
    def test_chart_dtrain_phases_omits_decide(self):
        phases = chart_dtrain_phases()
        self.assertIn("Dream", phases)
        self.assertIn("Deploy", phases)
        self.assertNotIn("Decide", phases)

    def test_resolve_issue_dtrain_phase_from_status_map(self):
        self.assertEqual(resolve_issue_dtrain_phase("In Development", _BINDING), "Develop")
        self.assertEqual(resolve_issue_dtrain_phase("PRD", _BINDING), "Deploy")

    def test_milestone_scope_segment_jql(self):
        rollup = {
            "phaseIssueKeys": {"Design": ["EPCE-1", "EPCE-2"]},
            "unpointedIssueKeys": ["EPCE-9"],
        }
        self.assertEqual(
            milestone_scope_segment_jql(rollup, "Design"),
            "key in (EPCE-1, EPCE-2) AND status != Rejected",
        )
        self.assertEqual(
            milestone_scope_segment_jql(rollup, _UNPOINTED_SEGMENT),
            "key in (EPCE-9) AND status != Rejected",
        )

    def test_append_scope_composition_overlay_splits_kpmg_referenced_keys(self):
        from extensions.twoa_programme.milestone_scope_chart import append_scope_composition_overlay

        rollup = {"phaseIssueKeys": {"Design": ["EPCE-1", "EPCE-2"]}, "unpointedIssueKeys": []}
        segments = [{"key": "Design", "fraction": 1.0, "weight": 5.0}]
        parts: list[str] = []
        append_scope_composition_overlay(
            parts,
            rollup=rollup,
            segments=segments,
            x0=0.0,
            y0=0.0,
            bar_w=100.0,
            bar_h=10.0,
            kpmg_reference_by_key={"EPCE-1": "TWOA-999"},
            kpmg_search_url_builder=lambda jql: f"https://kpmg.example/issues/?jql={jql}",
        )
        html_out = "".join(parts)
        self.assertIn("https://kpmg.example/issues/?jql=key in (TWOA-999)", html_out)
        self.assertIn("key%20in%20%28EPCE-2%29%20AND%20status%20%21%3D%20Rejected", html_out)
        self.assertEqual(html_out.count("<a href"), 2)

    def test_append_scope_composition_overlay_single_link_without_kpmg_data(self):
        from extensions.twoa_programme.milestone_scope_chart import append_scope_composition_overlay

        rollup = {"phaseIssueKeys": {"Design": ["EPCE-1", "EPCE-2"]}, "unpointedIssueKeys": []}
        segments = [{"key": "Design", "fraction": 1.0, "weight": 5.0}]
        parts: list[str] = []
        append_scope_composition_overlay(
            parts,
            rollup=rollup,
            segments=segments,
            x0=0.0,
            y0=0.0,
            bar_w=100.0,
            bar_h=10.0,
        )
        html_out = "".join(parts)
        self.assertEqual(html_out.count("<a href"), 1)
        self.assertIn("key%20in%20%28EPCE-1%2C%20EPCE-2%29%20AND%20status%20%21%3D%20Rejected", html_out)

    def test_rollup_lane_phase_buckets(self):
        children = [
            {"key": "EPCE-1", "fields": _fields(squads=["Kākāriki Krew"], sp=5.0, status="In Design")},
            {"key": "EPCE-2", "fields": _fields(squads=["Kākāriki Krew"], sp=8.0, status="In Development")},
            {"key": "EPCE-3", "fields": _fields(squads=["Kākāriki Krew"], sp=None)},
            {
                "key": "EPCE-4",
                "fields": _fields(platform="azure-integration-services", sp=3.0, status="Open"),
            },
        ]
        lanes = rollup_milestone_lane_phases(
            children,
            delivery_squad_field="customfield_11102",
            change_types_field="customfield_10079",
            platform_field="customfield_10120",
            story_points_field="customfield_10026",
            binding=_BINDING,
            skip_issue=lambda _issue: False,
        )
        ec = lanes["educationCloud"]
        self.assertEqual(ec["phases"]["Design"], 5.0)
        self.assertEqual(ec["phaseIssueKeys"]["Design"], ["EPCE-1"])
        self.assertEqual(ec["phaseIssueKeys"]["Develop"], ["EPCE-2"])
        self.assertEqual(ec["unpointedIssueKeys"], ["EPCE-3"])
        self.assertEqual(ec["phases"]["Develop"], 8.0)
        self.assertEqual(ec["unpointedCount"], 1)
        self.assertEqual(ec["totalWeight"], 14.0)
        self.assertEqual(lanes["integration"]["phases"]["Dream"], 3.0)

    def test_lane_bar_segments_include_unpointed_proportion(self):
        segments = lane_bar_segments(
            {
                "phases": {"Develop": 8.0, "Unknown": 0.0},
                "unpointedCount": 2,
                "totalWeight": 10.0,
            }
        )
        keys = [row["key"] for row in segments]
        self.assertEqual(keys, ["Develop", "Unpointed"])
        self.assertAlmostEqual(segments[0]["fraction"], 0.8)
        self.assertAlmostEqual(segments[1]["fraction"], 0.2)

    def test_timeline_bar_segment_order_reverses_dtrain_phases(self):
        order = timeline_bar_segment_order()
        phases = chart_dtrain_phases()
        self.assertEqual(order[0], phases[-1])
        self.assertEqual(order[len(phases) - 1], phases[0])
        self.assertEqual(order[-2:], ["Unknown", "Unpointed"])

    def test_lane_bar_segments_timeline_order_places_drive_before_dream(self):
        segments = lane_bar_segments(
            {
                "phases": {"Dream": 3.0, "Deploy": 10.0, "Drive": 10.0},
                "unpointedCount": 0,
                "totalWeight": 23.0,
            },
            segment_order=timeline_bar_segment_order(),
        )
        self.assertEqual([row["key"] for row in segments], ["Drive", "Deploy", "Dream"])

    def test_build_blocks_from_fixture(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        blocks = build_milestone_scope_blocks(payload)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(len(blocks[0]["lanes"]), 2)
        self.assertEqual(blocks[1]["lanes"], [])

    def test_build_rows_from_fixture(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        rows = build_milestone_scope_rows(payload)
        kinds = [row["kind"] for row in rows]
        self.assertIn("milestone_header", kinds)
        self.assertIn("lane_bar", kinds)
        self.assertIn("milestone_empty", kinds)

    def test_wrap_text_lines_truncates_long_titles(self):
        lines = _wrap_text_lines(
            "Semester A App Open - 24th August 2026 for all programmes",
            max_chars=20,
            max_lines=2,
        )
        self.assertLessEqual(len(lines), 2)
        self.assertTrue(lines[-1].endswith("…"))

    def test_format_lane_total(self):
        self.assertEqual(
            _format_lane_total({"totalWeight": 21.0, "storyPoints": 20.0, "unpointedCount": 1}),
            "21 (20 SP + 1 unpt)",
        )

    def test_svg_renders_scaled_bars_and_totals(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        svg = milestone_scope_svg(
            payload,
            quarter_start="2026-04-01",
            quarter_end="2026-08-20",
            sprint_bands=[
                {
                    "start": date(2026, 4, 1),
                    "end": date(2026, 4, 14),
                    "fill": "#deebff",
                    "label": "S1",
                }
            ],
        )
        self.assertIn("PDE-3834", svg)
        self.assertIn("Education Cloud", svg)
        self.assertIn("Integration", svg)
        self.assertIn("#c1c7d0", svg)
        self.assertIn("21 (20 SP + 1 unpt)", svg)
        self.assertIn("No quarter scope linked", svg)
        self.assertIn("Quarter calendar", svg)
        self.assertIn("Date</text>", svg)
        self.assertIn("chart-key-phase-strip", build_milestone_scope_html(
            payload,
            generated_on="11 Jun 2026",
            page_title="Milestone Scope Composition",
            quarter_start="2026-04-01",
            quarter_end="2026-08-20",
        ))
        self.assertIn("Key — quarter calendar", build_milestone_scope_html(
            payload,
            generated_on="11 Jun 2026",
            page_title="Milestone Scope Composition",
            quarter_start="2026-04-01",
            quarter_end="2026-08-20",
        ))
        max_weight = chart_max_lane_weight(payload)
        self.assertGreater(max_weight, 0)

    def test_build_html_report(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        html_doc = build_milestone_scope_html(
            payload,
            generated_on="11 Jun 2026",
            page_title="Milestone Scope Composition",
        )
        self.assertIn("Milestone Scope Composition", html_doc)
        self.assertIn("<svg", html_doc)


if __name__ == "__main__":
    unittest.main()
