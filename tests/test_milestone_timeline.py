"""Tests for milestone delivery timeline chart."""

from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from extensions.twoa_programme.milestone_timeline import (
    MILESTONE_LABEL_FILL_ODD,
    MILESTONE_LABEL_WIDTH,
    MILESTONE_TIMELINE_MAX_SVG_WIDTH,
    build_milestone_timeline_html,
    milestone_timeline_chart_bounds,
    milestone_timeline_plot_width,
    milestone_timeline_svg,
    milestone_timeline_tooltip,
    resolve_milestone_window,
)


_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "milestone-timeline.json"


class MilestoneTimelineTests(unittest.TestCase):
    def test_resolve_milestone_window_uses_start_and_due(self):
        start, end = resolve_milestone_window(
            start_date="2026-04-15",
            created="2026-03-01",
            due_date="2026-06-11",
            quarter_start=date(2026, 4, 1),
            quarter_end=date(2026, 8, 20),
        )
        self.assertEqual(start, date(2026, 4, 15))
        self.assertEqual(end, date(2026, 6, 11))

    def test_resolve_milestone_window_falls_back_to_created(self):
        start, end = resolve_milestone_window(
            start_date=None,
            created="2026-04-10",
            due_date="2026-07-06",
            quarter_start=date(2026, 4, 1),
            quarter_end=date(2026, 8, 20),
        )
        self.assertEqual(start, date(2026, 4, 10))
        self.assertEqual(end, date(2026, 7, 6))

    def test_resolve_milestone_window_keeps_due_past_quarter_end(self):
        start, end = resolve_milestone_window(
            start_date="2026-04-01",
            created="2026-03-01",
            due_date="2026-12-18",
            quarter_start=date(2026, 4, 1),
            quarter_end=date(2026, 8, 20),
        )
        self.assertEqual(start, date(2026, 4, 1))
        self.assertEqual(end, date(2026, 12, 18))

    def test_chart_bounds_start_at_earliest_milestone_start(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        x_min, x_max = milestone_timeline_chart_bounds(
            payload["milestones"],
            quarter_start=date(2026, 4, 1),
            quarter_end=date(2026, 8, 20),
        )
        self.assertEqual(x_min, date(2026, 4, 1))
        self.assertEqual(x_max, date(2026, 8, 20))

        payload["milestones"][1]["startDate"] = "2026-05-01"
        x_min, _ = milestone_timeline_chart_bounds(
            payload["milestones"],
            quarter_start=date(2026, 4, 1),
            quarter_end=date(2026, 8, 20),
        )
        self.assertEqual(x_min, date(2026, 4, 15))

    def test_chart_bounds_extend_to_latest_due_date(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        payload["milestones"][0]["dueDate"] = "2026-12-18"
        payload["milestones"][0]["endDate"] = "2026-12-18"
        _, x_max = milestone_timeline_chart_bounds(
            payload["milestones"],
            quarter_start=date(2026, 4, 1),
            quarter_end=date(2026, 8, 20),
        )
        self.assertEqual(x_max, date(2026, 12, 18))

    def test_plot_width_capped_to_report_page(self):
        span_days = 141  # Q2 2026 quarter window
        plot_w = milestone_timeline_plot_width(span_days)
        self.assertLessEqual(
            plot_w + MILESTONE_LABEL_WIDTH + 24,
            MILESTONE_TIMELINE_MAX_SVG_WIDTH,
        )
        self.assertLess(plot_w, span_days * 11)

    def test_svg_fits_page_without_fixed_pixel_width(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        svg = milestone_timeline_svg(
            payload,
            quarter_start="2026-04-01",
            quarter_end="2026-08-20",
        )
        svg_open = svg.split(">", 1)[0]
        self.assertIn('width="100%"', svg_open)
        self.assertIn(
            f'viewBox="0 0 {MILESTONE_TIMELINE_MAX_SVG_WIDTH}',
            svg_open,
        )

    def test_svg_renders_sprint_calendar_and_bars(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        svg = milestone_timeline_svg(
            payload,
            quarter_start="2026-04-01",
            quarter_end="2026-08-20",
            sprint_bands=[
                {
                    "start": date(2026, 4, 1),
                    "end": date(2026, 4, 30),
                    "fill": "#deebff",
                    "label": "Sprint 1",
                    "sprintNumber": 1,
                }
            ],
        )
        self.assertIn("ED Cloud Data within Fabric", svg)
        self.assertIn("Fabric data pipeline", svg)
        self.assertIn(">S1<", svg)
        self.assertNotIn('opacity="0.65"/>', svg)
        self.assertIn("Date</text>", svg)
        self.assertIn('aria-label="Milestone delivery timeline"', svg)

    def test_sprint_labels_sit_above_first_milestone_bar(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        svg = milestone_timeline_svg(
            payload,
            quarter_start="2026-04-01",
            quarter_end="2026-08-20",
            sprint_bands=[
                {
                    "start": date(2026, 4, 1),
                    "end": date(2026, 4, 30),
                    "fill": "#deebff",
                    "label": "Sprint 1",
                    "sprintNumber": 1,
                }
            ],
        )
        from extensions.twoa_programme.milestone_timeline import (
            MILESTONE_BLOCK_PAD_Y,
            MILESTONE_CALENDAR_TOP,
            MILESTONE_SPRINT_LABEL_BAND,
        )

        sprint_label_y = MILESTONE_CALENDAR_TOP + 14
        first_bar_y = (
            MILESTONE_CALENDAR_TOP
            + MILESTONE_SPRINT_LABEL_BAND
            + MILESTONE_BLOCK_PAD_Y
        )
        self.assertIn(f'y="{sprint_label_y:.1f}"', svg)
        self.assertGreater(first_bar_y, sprint_label_y + 8)

    def test_html_report_does_not_cap_milestone_timeline_height(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        html_doc = build_milestone_timeline_html(
            payload,
            generated_on="11 Jun 2026",
            page_title="Milestone Timeline",
            quarter_start="2026-04-01",
            quarter_end="2026-08-20",
        )
        self.assertIn("max-height: none", html_doc)
        self.assertIn("overflow-y: visible", html_doc)
        self.assertIn("overflow-x: hidden", html_doc)

    def test_svg_renders_scope_overlay_on_bar(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        svg = milestone_timeline_svg(
            payload,
            quarter_start="2026-04-01",
            quarter_end="2026-08-20",
        )
        self.assertIn("#c1c7d0", svg)
        self.assertIn('opacity="0.92"', svg)
        self.assertIn('class="milestone-scope-segment"', svg)
        self.assertIn("key%20in%20%28EPCE-6501%29", svg)
        self.assertIn("Scope:", milestone_timeline_tooltip(payload["milestones"][0]))
        self.assertIn("Notes", milestone_timeline_tooltip(payload["milestones"][0]))
        self.assertIn("Fabric rollout", milestone_timeline_tooltip(payload["milestones"][0]))

    def test_svg_scope_segments_run_drive_to_dream_left_to_right(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        svg = milestone_timeline_svg(
            payload,
            quarter_start="2026-04-01",
            quarter_end="2026-08-20",
        )
        deploy_pos = svg.find('title>Deploy:')
        design_pos = svg.find('title>Design:')
        self.assertGreater(deploy_pos, -1)
        self.assertGreater(design_pos, -1)
        self.assertLess(deploy_pos, design_pos)

    def test_svg_renders_epic_sub_bars(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        svg = milestone_timeline_svg(
            payload,
            quarter_start="2026-04-01",
            quarter_end="2026-08-20",
        )
        self.assertIn("Fabric data pipeline", svg)
        self.assertIn('opacity="0.55"', svg)

    def test_svg_renders_milestone_lane_label_background_and_frame(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        svg = milestone_timeline_svg(
            payload,
            quarter_start="2026-04-01",
            quarter_end="2026-08-20",
        )
        self.assertIn(MILESTONE_LABEL_FILL_ODD, svg)
        self.assertIn('fill="none" stroke="#172b4d"', svg)
        self.assertNotIn('opacity="0.72"', svg)

    def test_build_html_report(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        html_doc = build_milestone_timeline_html(
            payload,
            generated_on="11 Jun 2026",
            page_title="Milestone Timeline",
            quarter_start="2026-04-01",
            quarter_end="2026-08-20",
        )
        self.assertIn("Milestone Timeline", html_doc)
        self.assertIn("Scope bars: D-Train phases left to right", html_doc)


if __name__ == "__main__":
    unittest.main()
