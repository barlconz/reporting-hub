"""HTML and Confluence bodies for EPCE quarterly dashboard (EPCE-6745 Phase 4)."""

from __future__ import annotations

import html
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from extensions.twoa_programme.epic_timeline import (
    EPIC_BAR_OPACITY_EARNED,
    EPIC_BAR_OPACITY_NO_SP,
    EPIC_BAR_OPACITY_SCOPE,
    EPIC_CHART_PX_PER_DAY,
    EPIC_EC_SQUAD_HEADER,
    EPIC_LABEL_WIDTH,
    EPIC_ROW_HEIGHT,
    EPIC_SWIMLANE_HEADER,
    LANE_DISPLAY_ORDER,
    build_epic_timeline_rows,
    epic_bar_fill,
    epic_sp_progress_ratio,
    epic_timeline_key_html,
    epic_timeline_plot_height,
    epic_timeline_tooltip,
    group_ec_epics_by_squad,
    group_epics_by_lane,
)
from extensions.twoa_programme.quarter_scope import EC_SQUAD_SPECS

from extensions.twoa_programme.pde_engine_releases import (
    carriage_cycle_label,
    carriage_delivery_kind,
    carriage_type_code,
    is_placeholder_engine_version,
    release_code_label,
    release_row_code,
)
from extensions.twoa_programme.quarter_scope import (
    EC_SQUAD_NAME_TO_SLUG,
    EC_SQUAD_SPECS,
    education_cloud_squad_jqls,
)
from extensions.twoa_programme.quarterly_reporting import aggregate_daily_burn

SPRINT_NUM_RE = re.compile(r"sprint\s*(\d+)", re.IGNORECASE)
_DASH_RE = re.compile(r"[\u2013\u2014]|–|—")

JIRA_SERVER = "https://twoa.atlassian.net"

# Atlassian Design System tokens (aligned with artifact delivery_health reports)
ATL = {
    "ink": "#172b4d",
    "text_subtle": "#5e6c84",
    "line": "#dfe1e6",
    "grid": "#ebecf0",
    "page": "#f4f5f7",
    "blue": "#0052cc",
    "green": "#00875a",
    "red": "#de350b",
    "amber": "#ff8b00",
    "purple": "#6554c0",
    "neutral": "#6b778c",
    "sprint_a": "#deebff",
    "sprint_b": "#e3fcef",
    "release_in_cycle": "#172b4d",
    "release_out_cycle": "#ffc400",
}
SPRINT_FILL = (ATL["sprint_a"], ATL["sprint_b"])
SVG_FONT = '-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Oxygen, Ubuntu, sans-serif'
Y_AXIS_LEFT = 76
CHART_AXIS_FONT = 10
REF_PLOT_HEIGHT = 272
PLOT_HEIGHT = 408
PLOT_BOTTOM_MARGIN = 72
LANE_PLOT_HEIGHT = PLOT_HEIGHT

LANE_ORDER = ("educationCloud", "integration", "dataMigration", "unassigned")
LANE_DEFAULT_LABELS = {
    "educationCloud": "Education Cloud",
    "integration": "Integration",
    "dataMigration": "Data Migration",
    "unassigned": "Unassigned",
}
LANE_STACK_FILL = {
    "educationCloud": "#4d9cff",
    "integration": "#9b7aff",
    "dataMigration": "#3ddb7a",
    "unassigned": "#ffcc33",
}
LANE_STACK_OPACITY = 0.72

# Rollover copy for metric labels (HTML abbr + SVG title elements).
TIP_ON_TRACK = (
    "Earned SP vs ideal linear pace to goal target ({target}). "
    "On track when variance is zero or positive."
)
TIP_BEHIND = (
    "Earned SP vs ideal linear pace to goal target ({target}). "
    "Behind when variance is negative."
)
TIP_NO_GOAL = "No quarter goal SP configured. Run fetch_quarter_goal.py --write."
TIP_ELAPSED = "Share of the delivery quarter calendar elapsed (as-of report date)."
TIP_DAYS_LEFT = "Calendar days remaining until quarter end (reporting window)."
TIP_GOAL_DAYS_LEFT = "Calendar days remaining until goal target ({target})."
TIP_EARNED_SP = (
    "Story/Bug SP credited when lane definition of done was first met "
    "(Deploy+ for Education Cloud and Integration; Done for Data Migration). Excludes Rejected."
)
TIP_GOAL_SP = (
    "Initiative sizing (size-epics on EPCE-3897): Story, Spike, and Bug under epics; "
    "excludes Rejected. Not quarter-filtered; may differ from Planned in quarter scope."
)
TIP_IDEAL_LINEAR = (
    "Goal SP × elapsed fraction to goal target ({target}) — "
    "expected earned if burning evenly to that date."
)
TIP_VARIANCE = (
    "Earned SP minus ideal linear earned to goal target ({target}). "
    "Positive means ahead of linear pace."
)
TIP_REQ_DAILY = "(Goal SP minus earned SP) divided by days left to goal target ({target})."
TIP_UNPOINTED = (
    "Story/Bug in quarter scope with empty Story Points field. Excludes Rejected."
)
TIP_PLANNED_QUARTER = (
    "Sum of pointed Story, Spike, and Bug in smart-current-quarter; excludes Rejected."
)
TIP_GLOBAL_EARNED = "Total deploy-earned SP across all lanes in quarter burn scope."
TIP_BREAKDOWN_SUM = "Sum of lane earned SP. Reconciliation check; should match global earned."
TIP_PLANNED_SLICE = (
    "Pointed SP in that lane's exclusive quarter slice (priority L3, then L2, then L1, then unassigned)."
)
TIP_EARNED_SLICE = "Deploy-earned SP credited to that lane."
TIP_UNPOINTED_SLICE = "Story/Bug in lane slice with no Story Points."
TIP_UNASSIGNED_SLICE = (
    "In quarter scope but no lane signal (Delivery Squad, Platform, or Change Types). Hygiene bucket."
)
TIP_EC_SQUAD_SLICE = (
    "Education Cloud squad partition within the lane (multi-select Delivery Squad field)."
)
TIP_SPRINT_EARNED = (
    "SP whose credit date falls in that Release Plan sprint window (all lanes combined)."
)
TIP_RELEASE_EARNED = (
    "Deploy-earned SP on issues tagged with this engine fixVersion when status category is Done; "
    "otherwise SP whose credit date falls in the PRD window (day after previous release through this release date)."
)
TIP_PROJECTED_ROW = "Sprint or release not yet started (as-of report date)."
TIP_IN_PROGRESS_ROW = (
    "In-progress sprint or active release: scoped Story/Bug SP and issue count "
    "(grey until deploy/Done credit is earned)."
)
TIP_SQUAD_CREDIT = "Deploy transitions credited in closed sprints overlapping the delivery quarter."
TIP_SQUAD_BASELINE = "Historical average deploy credit per sprint for that squad."
TIP_SQUAD_SPRINTS = "Count of closed sprints overlapping the delivery quarter."
TIP_CHART_GOAL_LINEAR = "Linear pace to Goal SP by goal target ({target})."
TIP_CHART_SCOPE_GOAL = "Total planned in quarter scope (linear to goal target {target})."
TIP_CHART_LANE_GOAL = "{lane} planned SP target (linear to goal target {target})."

def _sanitize_atlassian_text(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        char = match.group(0)
        return ", " if char in ("\u2014", "—") else "-"
    return _DASH_RE.sub(_replace, text)
