"""SEF integrated project plan Block Gantt (PDE L2/L1/L0/L-1 hierarchy)."""

from __future__ import annotations

import html
import itertools
import json
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from artifact.atlassian import AtlassianAdapter

from extensions.twoa_programme.epic_timeline import (
    EPIC_CHART_PX_PER_DAY,
    EPIC_STATUS_FILL,
    epic_bar_fill,
)
from extensions.twoa_programme.jira_search import search_all
from extensions.twoa_programme.quarterly_dashboard_constants import ATL, CHART_AXIS_FONT, JIRA_SERVER, SVG_FONT
from extensions.twoa_programme.quarterly_dashboard_markup import REPORT_CSS, _svg_embedded_title
from extensions.twoa_programme.github_pages_nav import BREADCRUMB_CSS
from extensions.twoa_programme.quarterly_dashboard_svg_core import (
    QUARTERLY_REPORT_MAX_SVG_WIDTH,
    QUARTERLY_REPORT_MIN_PLOT_WIDTH,
    _append_today_marker,
    _chart_today_in_quarter,
    _svg_x_axis_labels,
    _svg_x_bottom_margin,
)
from extensions.twoa_programme.field_maps import field_aliases
from extensions.twoa_programme.milestone_scope_chart import (
    DTRAIN_PHASE_FILL,
    append_scope_composition_overlay,
    lane_bar_segments,
    timeline_bar_segment_order,
)
from extensions.twoa_programme.quarterly_dashboard_calendar import _week_start_dates
from extensions.twoa_programme.sef_block_scope import build_block_scope_rollups
from extensions.twoa_programme.sef_project_plan_component_colors import (
    SefProjectPlanComponentColors,
    WORKSTREAM_FIELD_ID,
    workstream_names_from_issue,
    load_sef_project_plan_component_colors,
    sef_project_plan_workstream_legend_html,
)
from extensions.twoa_programme.sef_project_plan_reporting import (
    SefFilterDimensionConfig,
    SefProjectPlanReportingConfig,
    discover_phase_hub_issues,
    load_sef_project_plan_reporting_config,
)

START_DATE_FIELD = "customfield_10015"
TENANT_FIELD_ID = "customfield_14734"
ENVIRONMENT_FIELD_ID = "customfield_10408"
PLATFORMS_FIELD_ID = "customfield_10046"
PLATFORM_FIELD_ID = "customfield_10079"
TEST_TYPES_FIELD_ID = "customfield_10145"

# Source-field names used in report filterDimensions and the Jira fields that feed them.
_DIMENSION_SOURCE_FIELD_IDS: dict[str, tuple[str, ...]] = {
    "workstreams": (WORKSTREAM_FIELD_ID, "components"),
    "tenant": (TENANT_FIELD_ID,),
    "environment": (ENVIRONMENT_FIELD_ID,),
    "platforms": (PLATFORMS_FIELD_ID, PLATFORM_FIELD_ID),
    "testTypes": (TEST_TYPES_FIELD_ID,),
    # SME commitment is intentionally configurable; set sourceField to a customfield id
    # in config when the authoritative Jira field is confirmed for PDE.
    "smeCommitment": (),
}


def _coerce_issue_field_values(raw: Any) -> list[str]:
    values: list[str] = []

    def _append(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, dict):
            text = str(
                item.get("value")
                or item.get("name")
                or item.get("displayName")
                or item.get("key")
                or ""
            ).strip()
        else:
            text = str(item).strip()
        if text:
            values.append(text)

    if isinstance(raw, list):
        for item in raw:
            _append(item)
    else:
        _append(raw)
    return values


def _issue_dimension_values(issue: dict[str, Any], *, source_field: str) -> list[str]:
    if source_field == "workstreams":
        return workstream_names_from_issue(issue)

    fields = issue.get("fields") or {}
    candidates: list[str] = []
    candidates.extend(_DIMENSION_SOURCE_FIELD_IDS.get(source_field, ()))
    if source_field.startswith("customfield_"):
        candidates.append(source_field)
    candidates.append(source_field)

    values: list[str] = []
    for field_id in candidates:
        values.extend(_coerce_issue_field_values(fields.get(field_id)))

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped

CHAPTER_ROW_HEIGHT = 36
PHASE_ROW_HEIGHT = 44
STREAM_ROW_HEIGHT = 24
DETAIL_ROW_HEIGHT = 20
LABEL_WIDTH = 300
RIGHT_PAD = 32
MILESTONE_RIGHT_LABEL_PAD = 200
CALENDAR_TOP = 48
BLOCK_GAP = 14
BLOCK_PAD_Y = 10
LABEL_PAD_X = 10
LABEL_MAX_CHARS = 42
SUB_LABEL_INDENT = 20
DETAIL_LABEL_INDENT = 36
CHAPTER_BAR_HEIGHT = CHAPTER_ROW_HEIGHT - 6
PHASE_BAR_HEIGHT = PHASE_ROW_HEIGHT - 8
STREAM_BAR_HEIGHT = STREAM_ROW_HEIGHT - 4
DETAIL_BAR_HEIGHT = DETAIL_ROW_HEIGHT - 4
BAR_OPACITY = 0.85
SUB_BAR_OPACITY = 0.55
DETAIL_BAR_OPACITY = 0.35
SCOPE_OVERLAY_OPACITY = 0.92
SUB_SCOPE_OVERLAY_OPACITY = 0.72
DETAIL_SCOPE_OVERLAY_OPACITY = 0.62
BLOCK_BORDER_WIDTH = 0.75
PHASE_GAP = 20
CHART_WINDOW_PADDING_DAYS = 0
MILESTONE_TRIANGLE_FILL = "#de350b"
DEPENDENCY_STROKE = MILESTONE_TRIANGLE_FILL
DEPENDENCY_STROKE_WIDTH = 1.1
DEPENDENCY_MIN_HORIZONTAL_RUN = 32.0
SWIMLANE_FILLS = ["#e8f4fd", "#e8f8ee"]  # alternating light blue / light green

# Map detail bar summary keywords to D-Train phase colours.
# Test Plan = Design, Test Preparation = Develop, Test Execution = Deliver, Test Summary Report = Drive
DETAIL_KEYWORD_FILLS: list[tuple[str, str]] = [
    ("test summary report", "#00875a"),  # Drive
    ("test memo", "#00875a"),             # Drive
    ("config workbooks", "#00875a"),      # Drive
    ("interface specs", "#00875a"),       # Drive
    ("report specs", "#00875a"),          # Drive
    ("test execution", "#5f6438"),        # Deliver
    ("test preparation", "#7f582d"),      # Develop
    ("test plan", "#9f4c22"),             # Design
]

TEST_CYCLE_BAR_FILL = "#1868db"  # Light blue for Test Cycle swimlane bars

# Package-level bars with specific keyword overrides.
PACKAGE_KEYWORD_FILLS: list[tuple[str, str]] = [
    ("data migration", "#0747a6"),       # Dark blue
    ("integration build", "#0747a6"),    # Dark blue
]


def _package_keyword_fill(summary: str) -> str | None:
    """Return a colour override for a known package type, or None to use default."""
    lower = summary.strip().lower()
    for keyword, color in PACKAGE_KEYWORD_FILLS:
        if keyword in lower:
            return color
    return None


def _detail_keyword_fill(summary: str) -> str | None:
    """Return a D-Train phase fill for a known detail type, or None to use default."""
    lower = summary.strip().lower()
    for keyword, color in DETAIL_KEYWORD_FILLS:
        if keyword in lower:
            return color
    return None

SEF_PROJECT_PLAN_EXTRA_CSS = """
.report-shell {
    max-width: none;
    width: min(100vw - 8px, 2200px);
    padding: 16px 4px 24px;
}
.chart-wrap-sef-plan.chart-wrap-timeline {
    max-height: 82vh;
    min-height: 400px;
    overflow-x: scroll;
    overflow-y: auto;
    scrollbar-gutter: stable both-edges;
    border: 1px solid #dfe1e6;
    border-radius: 4px;
}
/* Override .report-shell .chart-wrap (overflow-x: hidden) */
.report-shell .chart-wrap-sef-plan {
    overflow-x: scroll;
    overflow-y: auto;
    scrollbar-gutter: stable both-edges;
}
/* Override .report-shell .chart-wrap svg (width:100%, max-width:100%, height:auto)
   — SVG must render at its intrinsic pixel size so text is readable. */
.report-shell .chart-wrap-sef-plan svg {
  display: block;
  width: auto;
  height: auto;
  min-width: unset;
  max-width: unset;
}
.sef-plan-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 18px;
  margin: 12px 0 4px;
  font-size: 12px;
  color: #42526e;
}
.sef-plan-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.sef-plan-filters {
    display: flex;
    flex-wrap: wrap;
    gap: 12px 18px;
    margin: 8px 0 12px;
    align-items: end;
}
.sef-plan-filter {
    display: inline-flex;
    flex-direction: column;
    gap: 4px;
    font-size: 12px;
    color: #42526e;
}
.sef-plan-expander {
    min-width: 240px;
    background: #fff;
    border: 1px solid #dfe1e6;
    border-radius: 6px;
}
.sef-plan-expander > summary {
    list-style: none;
    padding: 7px 10px;
    cursor: pointer;
    color: #172b4d;
    font-weight: 500;
    user-select: none;
}
.sef-plan-expander > summary::-webkit-details-marker {
    display: none;
}
.sef-plan-expander > summary::after {
    content: "▾";
    float: right;
    color: #6b778c;
}
.sef-plan-expander[open] > summary::after {
    content: "▴";
}
.sef-plan-options {
    max-height: 260px;
    overflow: auto;
    border-top: 1px solid #ebecf0;
    padding: 6px 8px;
}
.sef-plan-option {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 3px 0;
    color: #172b4d;
}
.sef-plan-option input {
    margin: 0;
}
.sef-plan-option span {
    line-height: 1.2;
}
.sef-plan-option:hover {
    background: #f7f8fa;
}
.sef-plan-expander:focus-within {
    border-color: #4c9aff;
    box-shadow: 0 0 0 2px rgba(76, 154, 255, 0.2);
}
.sef-plan-filter-actions {
    display: inline-flex;
    align-items: flex-end;
    padding-bottom: 1px;
}
.sef-plan-clear {
    height: 34px;
    padding: 0 12px;
    border: 1px solid #dfe1e6;
    border-radius: 4px;
    background: #fff;
    color: #172b4d;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
}
.sef-plan-clear:hover {
    background: #f4f5f7;
}
.sef-plan-clear:disabled {
    opacity: 0.55;
    cursor: default;
}
.sef-plan-variant[hidden] {
    display: none;
}
.sef-plan-legend-swatch {
  width: 14px;
  height: 14px;
  border-radius: 2px;
  border: 1px solid rgba(9, 30, 66, 0.14);
  flex: 0 0 14px;
}
.chart-wrap-sef-plan svg a text {
  text-decoration: none;
}
.chart-wrap-sef-plan svg a:hover text {
  text-decoration: underline;
}
.chart-wrap-sef-plan .sef-block-link-icon {
    cursor: pointer;
    user-select: none;
}
.chart-wrap-sef-plan .sef-block-link-icon-bg {
    fill: #ffebe6;
    stroke: #ff8f73;
    stroke-width: 0.8;
}
.chart-wrap-sef-plan .sef-block-link-icon-glyph {
    fill: #bf2600;
    font-weight: 700;
}
.chart-wrap-sef-plan .sef-block-link-icon-dir {
    fill: #42526e;
    font-weight: 700;
}
.chart-wrap-sef-plan .sef-block-link-icon:hover .sef-block-link-icon-bg {
    fill: #ffdfd6;
    stroke: #de350b;
}
.chart-wrap-sef-plan .sef-block-link-icon.active .sef-block-link-icon-bg {
    fill: #ffbdad;
    stroke: #bf2600;
}
.chart-wrap-sef-plan .sef-block-link-icon[data-sef-dir="blocks"] .sef-block-link-icon-bg {
    fill: #e3fcef;
    stroke: #79f2c0;
}
.chart-wrap-sef-plan .sef-block-link-icon[data-sef-dir="blocks"] .sef-block-link-icon-glyph,
.chart-wrap-sef-plan .sef-block-link-icon[data-sef-dir="blocks"] .sef-block-link-icon-dir {
    fill: #006644;
}
.chart-wrap-sef-plan .sef-block-link-icon[data-sef-dir="both"] .sef-block-link-icon-bg {
    fill: #deebff;
    stroke: #4c9aff;
}
.chart-wrap-sef-plan .sef-block-link-icon[data-sef-dir="both"] .sef-block-link-icon-glyph,
.chart-wrap-sef-plan .sef-block-link-icon[data-sef-dir="both"] .sef-block-link-icon-dir {
    fill: #0747a6;
}
.sef-phase-divider {
  fill: #f4f5f7;
}
"""


def default_sef_project_plan_timeline_path(repo_root: Path | None = None) -> Path:
    config = load_sef_project_plan_reporting_config(repo_root=repo_root)
    return config.timeline_path(repo_root)


def load_sef_project_plan_timeline_payload(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_timeline_rows(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for phase in phases:
        rows.append(phase)
        for chapter in phase.get("chapters") or []:
            rows.append(chapter)
            for package in chapter.get("packages") or []:
                rows.append(package)
                for detail in package.get("details") or []:
                    rows.append(detail)
    return rows


def resolve_chart_window_for_phases(
    phases: list[dict[str, Any]],
    *,
    fallback_start: str = "2026-06-01",
    fallback_end: str = "2027-12-03",
    padding_days: int = CHART_WINDOW_PADDING_DAYS,
) -> tuple[date, date]:
    """Span the x-axis from earliest start through latest end across all plan rows."""
    all_starts: list[date] = []
    all_ends: list[date] = []
    actionable_starts: list[date] = []
    actionable_ends: list[date] = []

    for phase in phases:
        for chapter in phase.get("chapters") or []:
            # Include chapter dates so the window always spans the full plan,
            # even when package/detail rows exist with narrower date ranges.
            c_start = chapter.get("startDate")
            c_end = chapter.get("endDate")
            if c_start:
                actionable_starts.append(date.fromisoformat(str(c_start)[:10]))
            if c_end:
                actionable_ends.append(date.fromisoformat(str(c_end)[:10]))
            for package in chapter.get("packages") or []:
                p_start = package.get("startDate")
                p_end = package.get("endDate")
                if p_start:
                    actionable_starts.append(date.fromisoformat(str(p_start)[:10]))
                if p_end:
                    actionable_ends.append(date.fromisoformat(str(p_end)[:10]))
                for detail in package.get("details") or []:
                    d_start = detail.get("startDate")
                    d_end = detail.get("endDate")
                    if d_start:
                        actionable_starts.append(date.fromisoformat(str(d_start)[:10]))
                    if d_end:
                        actionable_ends.append(date.fromisoformat(str(d_end)[:10]))

    for row in _iter_timeline_rows(phases):
        start_raw = row.get("startDate")
        end_raw = row.get("endDate")
        if start_raw:
            all_starts.append(date.fromisoformat(str(start_raw)[:10]))
        if end_raw:
            all_ends.append(date.fromisoformat(str(end_raw)[:10]))

    starts = actionable_starts or all_starts
    ends = actionable_ends or all_ends
    if not starts or not ends:
        return date.fromisoformat(fallback_start), date.fromisoformat(fallback_end)
    pad = timedelta(days=padding_days)
    return min(starts) - pad, max(ends) + pad


def _payload_chart_window(payload: dict[str, Any]) -> tuple[date, date]:
    phases = payload.get("phases") or []
    if phases:
        return resolve_chart_window_for_phases(phases)
    return (
        date.fromisoformat(str(payload.get("chartWindowStart") or "2026-06-01")[:10]),
        date.fromisoformat(str(payload.get("chartWindowEnd") or "2027-12-03")[:10]),
    )


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _resolve_window(
    *,
    start_raw: str | None,
    created: str | None,
    due_raw: str | None,
    fallback_start: date,
    fallback_end: date,
) -> tuple[date, date]:
    start = _parse_day(start_raw) or _parse_day(created) or fallback_start
    end = _parse_day(due_raw) or start
    if end < start:
        end = start
    return start, end


def _issue_timeline_row(
    issue: dict[str, Any],
    *,
    fallback_start: date,
    fallback_end: date,
    milestone_issue_types: tuple[str, ...],
) -> dict[str, Any]:
    def _blocked_by_keys() -> list[str]:
        blocked_by: list[str] = []
        for link in (fields.get("issuelinks") or []):
            if not isinstance(link, dict):
                continue
            link_type = link.get("type") or {}
            inward_rel = str((link_type or {}).get("inward") or "").strip().lower()
            outward_rel = str((link_type or {}).get("outward") or "").strip().lower()

            inward_issue = link.get("inwardIssue") or {}
            outward_issue = link.get("outwardIssue") or {}

            inward_key = str(inward_issue.get("key") or "").strip()
            outward_key = str(outward_issue.get("key") or "").strip()

            if inward_key and "blocked by" in inward_rel:
                blocked_by.append(inward_key)
            if outward_key and "blocked by" in outward_rel:
                blocked_by.append(outward_key)

        return list(dict.fromkeys(key for key in blocked_by if key and key != str(issue.get("key") or "")))
    fields = issue.get("fields") or {}
    start_raw = fields.get(START_DATE_FIELD)
    if isinstance(start_raw, str):
        start_s = start_raw[:10]
    else:
        start_s = None
    due_raw = fields.get("duedate")
    due_s = str(due_raw)[:10] if due_raw else None
    created = str(fields.get("created") or "")[:10]
    start, end = _resolve_window(
        start_raw=start_s,
        created=created,
        due_raw=due_s,
        fallback_start=fallback_start,
        fallback_end=fallback_end,
    )
    status = str((fields.get("status") or {}).get("name") or "")
    summary = str(fields.get("summary") or "").strip()
    key = str(issue.get("key") or "")
    issue_type = str((fields.get("issuetype") or {}).get("name") or "")
    issue_type_icon_url = str((fields.get("issuetype") or {}).get("iconUrl") or "").strip()
    row: dict[str, Any] = {
        "key": key,
        "summary": summary,
        "status": status,
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
    }
    if issue_type:
        row["issueType"] = issue_type
    if issue_type_icon_url:
        row["issueTypeIconUrl"] = issue_type_icon_url
    if _is_milestone_issue_type(issue_type, milestone_issue_types):
        if "meeting gate" in issue_type.strip().lower():
            row["isMeetingGate"] = True
    workstreams = _issue_dimension_values(issue, source_field="workstreams")
    if workstreams:
        row["workstreams"] = workstreams
    for source_field in ("tenant", "environment", "platforms", "testTypes", "smeCommitment"):
        values = _issue_dimension_values(issue, source_field=source_field)
        if values:
            row[source_field] = values
    if due_s:
        row["dueDate"] = due_s
    blocked_by = _blocked_by_keys()
    if blocked_by:
        row["blockedByKeys"] = blocked_by
    return row


def _issue_start_sort_key(issue: dict[str, Any]) -> tuple[date, str]:
    """Sort siblings by Start date, then issue key."""
    fields = issue.get("fields") or {}
    start_raw = fields.get(START_DATE_FIELD)
    start = _parse_day(start_raw[:10] if isinstance(start_raw, str) else None)
    if start is None:
        start = _parse_day(str(fields.get("created") or "")[:10]) or date.max
    return start, str(issue.get("key") or "")


def _sort_sibling_keys(keys: list[str], by_key: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(keys, key=lambda key: _issue_start_sort_key(by_key[key]))


def _issue_type_name(issue: dict[str, Any]) -> str:
    return str(((issue.get("fields") or {}).get("issuetype") or {}).get("name") or "")


def _is_milestone_issue_type(issue_type: str, milestone_issue_types: tuple[str, ...]) -> bool:
    normalized = issue_type.strip().lower()
    if not normalized:
        return False
    if any(normalized == name.strip().lower() for name in milestone_issue_types):
        return True
    return "milestone" in normalized


def _unique_issue_types(issue_types: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for issue_type in issue_types:
        token = issue_type.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def _child_keys_for_types(
    parent_key: str,
    *,
    children_of: dict[str, list[str]],
    by_key: dict[str, dict[str, Any]],
    issue_types: set[str],
) -> list[str]:
    keys = children_of.get(parent_key, [])
    matched = [key for key in keys if key in by_key and _issue_type_name(by_key[key]) in issue_types]
    return _sort_sibling_keys(matched, by_key)


def _fetch_children(
    adapter: "AtlassianAdapter",
    *,
    parent_key: str,
    issue_type: str,
    fields: list[str],
) -> list[dict[str, Any]]:
    jql = (
        f'parent = {parent_key} AND issuetype = "{issue_type}" '
        f'ORDER BY "Start date" ASC, key ASC'
    )
    return search_all(adapter, jql, fields)


def _fetch_package_children(
    adapter: "AtlassianAdapter",
    *,
    parent_key: str,
    config: SefProjectPlanReportingConfig,
    fields: list[str],
) -> list[dict[str, Any]]:
    """Fetch Block Level Zero and Test Cycle children under a parent."""
    rows: list[dict[str, Any]] = []
    issue_types = _unique_issue_types(
        [config.package_issue_type, config.test_cycle_issue_type, *list(config.milestone_issue_types), *list(config.extra_package_issue_types)]
    )
    for issue_type in issue_types:
        rows.extend(
            _fetch_children(
                adapter,
                parent_key=parent_key,
                issue_type=issue_type,
                fields=fields,
            )
        )
    return sorted(rows, key=lambda issue: _issue_start_sort_key(issue))


def _fetch_detail_children(
    adapter: "AtlassianAdapter",
    *,
    parent_key: str,
    config: SefProjectPlanReportingConfig,
    fields: list[str],
) -> list[dict[str, Any]]:
    """Fetch Block Level Minus One and Test Cycle children under a package."""
    rows: list[dict[str, Any]] = []
    issue_types = _unique_issue_types(
        [config.detail_issue_type, config.test_cycle_issue_type, *list(config.milestone_issue_types)]
    )
    for issue_type in issue_types:
        rows.extend(
            _fetch_children(
                adapter,
                parent_key=parent_key,
                issue_type=issue_type,
                fields=fields,
            )
        )
    return sorted(rows, key=lambda issue: _issue_start_sort_key(issue))


def _resolve_scope_filter_jql(
    adapter: "AtlassianAdapter",
    config: "SefProjectPlanReportingConfig",
) -> str | None:
    """Return JQL for scope filter if configured, else None."""
    if config.scope_filter_id:
        from extensions.twoa_programme.delivery_milestones import fetch_jira_saved_filter
        payload = fetch_jira_saved_filter(adapter, config.scope_filter_id)
        jql = str(payload.get("jql") or "").strip()
        return jql or f"filter = {config.scope_filter_id}"
    if config.scope_filter_name:
        return f"filter = {config.scope_filter_name}"
    return None


def _build_hierarchy_from_flat(
    issues: list[dict[str, Any]],
    config: "SefProjectPlanReportingConfig",
    *,
    fallback_start: "date",
    fallback_end: "date",
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Build phase→chapter→package→detail hierarchy from a flat issue list.

    Returns (phases, hub_keys, warnings).
    """
    block_types = {
        config.chapter_issue_type,   # Block Level One
        config.package_issue_type,   # Block Level Zero
        config.detail_issue_type,    # Block Level Minus One
    }
    hub_type = "Block Level Two"
    milestone_types = set(config.milestone_issue_types)
    package_types = {config.package_issue_type, config.test_cycle_issue_type, *milestone_types, *config.extra_package_issue_types}
    detail_types = {config.detail_issue_type, config.test_cycle_issue_type, *milestone_types}
    chapter_types = {config.chapter_issue_type, config.test_cycle_issue_type, *milestone_types, *config.extra_chapter_issue_types}
    by_key: dict[str, dict[str, Any]] = {}
    for issue in issues:
        key = str(issue.get("key") or "")
        if not key:
            continue
        itype = _issue_type_name(issue)
        allowed_type = itype in {hub_type, *block_types, config.test_cycle_issue_type, *config.extra_package_issue_types} or _is_milestone_issue_type(
            itype,
            config.milestone_issue_types,
        )
        if not allowed_type:
            continue  # skip milestone levels etc.
        by_key[key] = issue

    # Build parent→children mapping
    children_of: dict[str, list[str]] = {}
    for key, issue in by_key.items():
        parent_key = ((issue.get("fields") or {}).get("parent") or {}).get("key") or ""
        children_of.setdefault(parent_key, []).append(key)

    # Hub issues are Block Level Two (parent not in our set)
    hub_keys_found = [
        key for key, issue in by_key.items()
        if _issue_type_name(issue) == hub_type
    ]
    hub_keys_found = _sort_sibling_keys(hub_keys_found, by_key)
    warnings: list[str] = []

    def make_detail(key: str) -> dict[str, Any]:
        return _issue_timeline_row(
            by_key[key],
            fallback_start=fallback_start,
            fallback_end=fallback_end,
            milestone_issue_types=config.milestone_issue_types,
        )

    def make_package(key: str) -> dict[str, Any]:
        row = _issue_timeline_row(
            by_key[key],
            fallback_start=fallback_start,
            fallback_end=fallback_end,
            milestone_issue_types=config.milestone_issue_types,
        )
        detail_keys = _child_keys_for_types(
            key,
            children_of=children_of,
            by_key=by_key,
            issue_types=detail_types,
        )
        row["details"] = [
            make_detail(dk)
            for dk in detail_keys
            if dk in by_key and _issue_type_name(by_key[dk]) in detail_types
        ]
        return row

    def make_chapter(key: str) -> dict[str, Any]:
        row = _issue_timeline_row(
            by_key[key],
            fallback_start=fallback_start,
            fallback_end=fallback_end,
            milestone_issue_types=config.milestone_issue_types,
        )
        pkg_keys = _child_keys_for_types(
            key,
            children_of=children_of,
            by_key=by_key,
            issue_types=package_types,
        )
        row["packages"] = [
            make_package(pk)
            for pk in pkg_keys
            if pk in by_key and _issue_type_name(by_key[pk]) in package_types
        ]
        return row

    phases: list[dict[str, Any]] = []
    for hub_key in hub_keys_found:
        hub_row = _issue_timeline_row(
            by_key[hub_key],
            fallback_start=fallback_start,
            fallback_end=fallback_end,
            milestone_issue_types=config.milestone_issue_types,
        )
        chapter_keys = _child_keys_for_types(
            hub_key,
            children_of=children_of,
            by_key=by_key,
            issue_types=chapter_types,
        )
        hub_row["chapters"] = [
            make_chapter(ck)
            for ck in chapter_keys
            if ck in by_key and _issue_type_name(by_key[ck]) in chapter_types
        ]
        phases.append(hub_row)

    if not phases:
        warnings.append("Scope filter returned no Block Level Two (phase hub) issues.")
    return phases, hub_keys_found, warnings


def _fetch_nz_auckland_holidays(window_start: date, window_end: date) -> list[dict[str, Any]]:
    """Fetch NZ Auckland public holidays from Enrico API for the chart window."""
    from urllib.request import Request as _Request
    from urllib.request import urlopen as _urlopen
    import json as _json

    url = (
        "https://kayaposoft.com/enrico/json/v2.0/?action=getHolidaysForDateRange"
        f"&fromDate={window_start.strftime('%d-%m-%Y')}"
        f"&toDate={window_end.strftime('%d-%m-%Y')}"
        "&country=nzl&region=auckland&holidayType=public_holiday"
    )
    try:
        req = _Request(url, headers={"Accept": "application/json"})
        with _urlopen(req, timeout=15) as resp:  # nosec B310 — fixed trusted host
            data = _json.loads(resp.read().decode())
    except Exception:
        return []
    holidays: list[dict[str, Any]] = []
    for h in data:
        d = h.get("date") or {}
        try:
            hdate = date(d["year"], d["month"], d["day"])
        except (KeyError, TypeError, ValueError):
            continue
        name_raw = h.get("localName") or h.get("name") or "Public Holiday"
        if isinstance(name_raw, list):
            name_raw = name_raw[0].get("text") if name_raw else "Public Holiday"
        holidays.append({"date": hdate.isoformat(), "name": str(name_raw)})
    return sorted(holidays, key=lambda x: x["date"])


def fetch_sef_project_plan_timeline(
    adapter: "AtlassianAdapter",
    config: SefProjectPlanReportingConfig,
) -> dict[str, Any]:
    fallback_start = date.fromisoformat(config.chart_window_start)
    fallback_end = date.fromisoformat(config.chart_window_end)
    start_field = START_DATE_FIELD
    fields = [
        "summary",
        "status",
        "issuetype",
        "created",
        "duedate",
        start_field,
        "components",
        WORKSTREAM_FIELD_ID,
        TENANT_FIELD_ID,
        ENVIRONMENT_FIELD_ID,
        PLATFORMS_FIELD_ID,
        PLATFORM_FIELD_ID,
        TEST_TYPES_FIELD_ID,
    ]
    scope_fields = [*fields, "issuelinks"]
    story_points_field = field_aliases()["Story Points"]

    scope_filter_jql = _resolve_scope_filter_jql(adapter, config)
    milestones: list[dict[str, Any]] = []
    if scope_filter_jql:
        # Single flat fetch from Jira filter — hierarchy built from parent fields.
        filter_fields = [*scope_fields, "parent"]
        all_issues = search_all(adapter, scope_filter_jql, filter_fields)
        milestones = [
            _issue_timeline_row(
                issue,
                fallback_start=fallback_start,
                fallback_end=fallback_end,
                milestone_issue_types=config.milestone_issue_types,
            )
            for issue in all_issues
            if _is_milestone_issue_type(_issue_type_name(issue), config.milestone_issue_types)
        ]
        milestones = sorted(
            [row for row in milestones if row.get("key")],
            key=lambda row: (str(row.get("startDate") or ""), str(row.get("key") or "")),
        )
        deduped: dict[str, dict[str, Any]] = {}
        for row in milestones:
            deduped[str(row.get("key") or "")] = row
        milestones = list(deduped.values())
        phases, hub_keys, warnings = _build_hierarchy_from_flat(
            all_issues,
            config,
            fallback_start=fallback_start,
            fallback_end=fallback_end,
        )
        # Build block_issues dict for scope rollup
        block_issues: dict[str, dict[str, Any]] = {
            str(issue.get("key") or ""): issue
            for issue in all_issues
            if issue.get("key")
        }
    else:
        hub_issues, warnings = discover_phase_hub_issues(adapter, config, fields=fields)
        hub_keys = [str(issue.get("key") or "") for issue in hub_issues if issue.get("key")]
        phases = []
        block_issues = {}

        for hub in hub_issues:
            hub_key = str(hub.get("key") or "")
            if not hub_key:
                continue
            hub_row = _issue_timeline_row(
                hub,
                fallback_start=fallback_start,
                fallback_end=fallback_end,
                milestone_issue_types=config.milestone_issue_types,
            )
            chapters_raw = _fetch_children(
                adapter,
                parent_key=hub_key,
                issue_type=config.chapter_issue_type,
                fields=scope_fields,
            )
            test_cycles_raw = _fetch_children(
                adapter,
                parent_key=hub_key,
                issue_type=config.test_cycle_issue_type,
                fields=scope_fields,
            )
            milestone_rows_raw: list[dict[str, Any]] = []
            for milestone_issue_type in _unique_issue_types(list(config.milestone_issue_types)):
                milestone_rows_raw.extend(
                    _fetch_children(
                        adapter,
                        parent_key=hub_key,
                        issue_type=milestone_issue_type,
                        fields=scope_fields,
                    )
                )
            chapters_raw = sorted(
                [*chapters_raw, *test_cycles_raw, *milestone_rows_raw],
                key=_issue_start_sort_key,
            )
            chapters: list[dict[str, Any]] = []
            for chapter_issue in chapters_raw:
                chapter_key = str(chapter_issue["key"])
                block_issues[chapter_key] = chapter_issue
                chapter_row = _issue_timeline_row(
                    chapter_issue,
                    fallback_start=fallback_start,
                    fallback_end=fallback_end,
                    milestone_issue_types=config.milestone_issue_types,
                )
                packages_raw = _fetch_package_children(
                    adapter,
                    parent_key=chapter_key,
                    config=config,
                    fields=scope_fields,
                )
                packages: list[dict[str, Any]] = []
                for package_issue in packages_raw:
                    package_key = str(package_issue["key"])
                    block_issues[package_key] = package_issue
                    package_row = _issue_timeline_row(
                        package_issue,
                        fallback_start=fallback_start,
                        fallback_end=fallback_end,
                        milestone_issue_types=config.milestone_issue_types,
                    )
                    details_raw = _fetch_detail_children(
                        adapter,
                        parent_key=package_key,
                        config=config,
                        fields=scope_fields,
                    )
                    detail_rows: list[dict[str, Any]] = []
                    for detail_issue in details_raw:
                        detail_key = str(detail_issue["key"])
                        block_issues[detail_key] = detail_issue
                        detail_rows.append(
                            _issue_timeline_row(
                                detail_issue,
                                fallback_start=fallback_start,
                                fallback_end=fallback_end,
                                milestone_issue_types=config.milestone_issue_types,
                            )
                        )
                    package_row["details"] = detail_rows
                    packages.append(package_row)
                chapter_row["packages"] = packages
                chapters.append(chapter_row)
            hub_row["chapters"] = chapters
            phases.append(hub_row)

    scope_rollups = build_block_scope_rollups(
        adapter,
        block_issues=block_issues,
        story_points_field=story_points_field,
    )
    for phase in phases:
        for chapter in phase.get("chapters") or []:
            chapter_key = str(chapter.get("key") or "")
            if chapter_key in scope_rollups:
                chapter["scopeRollup"] = scope_rollups[chapter_key]
            for package in chapter.get("packages") or []:
                package_key = str(package.get("key") or "")
                if package_key in scope_rollups:
                    package["scopeRollup"] = scope_rollups[package_key]
                for detail in package.get("details") or []:
                    detail_key = str(detail.get("key") or "")
                    if detail_key in scope_rollups:
                        detail["scopeRollup"] = scope_rollups[detail_key]

    window_start, window_end = resolve_chart_window_for_phases(
        phases,
        fallback_start=config.chart_window_start,
        fallback_end=config.chart_window_end,
    )

    filter_dimensions = _build_filter_dimensions(phases, config.filter_dimensions)

    holidays = _fetch_nz_auckland_holidays(window_start, window_end)

    return {
        "projectKey": config.project_key,
        "chartWindowStart": window_start.isoformat(),
        "chartWindowEnd": window_end.isoformat(),
        "phaseHubKeys": hub_keys,
        "warnings": warnings,
        "filterDimensions": filter_dimensions,
        "milestones": milestones,
        "phases": phases,
        "holidays": holidays,
    }


def _iter_dimension_values(row: dict[str, Any], *, source_field: str) -> list[str]:
    raw = row.get(source_field)
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if raw is None:
        return []
    text = str(raw).strip()
    return [text] if text else []


def _build_filter_dimensions(
    phases: list[dict[str, Any]],
    dimensions: tuple[SefFilterDimensionConfig, ...],
) -> list[dict[str, Any]]:
    rows = _iter_timeline_rows(phases)
    result: list[dict[str, Any]] = []
    for dimension in dimensions:
        values: set[str] = set()
        for row in rows:
            values.update(_iter_dimension_values(row, source_field=dimension.source_field))
        result.append(
            {
                "id": dimension.id,
                "label": dimension.label,
                "sourceField": dimension.source_field,
                "options": sorted(values),
            }
        )
    return result


def filter_payload_by_dimension_value(
    payload: dict[str, Any],
    *,
    dimension_id: str,
    value: str,
) -> dict[str, Any]:
    """Return a filtered payload copy for one dimension/value pair.

    The hierarchy is preserved by keeping ancestors of matching rows.
    """
    dimensions_raw = payload.get("filterDimensions") or []
    dimensions: list[dict[str, Any]] = []
    for dim in dimensions_raw:
        if not isinstance(dim, dict):
            continue
        dim_copy = dict(dim)
        if str(dim_copy.get("id") or "") == "component":
            dim_copy["id"] = "workstream"
        if str(dim_copy.get("label") or "") == "Component":
            dim_copy["label"] = "Workstream"
        if str(dim_copy.get("sourceField") or "") == "components":
            dim_copy["sourceField"] = "workstreams"
        dimensions.append(dim_copy)
    mapping = {
        str(row.get("id") or ""): str(row.get("sourceField") or "")
        for row in dimensions
        if str(row.get("id") or "") and str(row.get("sourceField") or "")
    }
    source_field = mapping.get(dimension_id)
    if not source_field or not value:
        return json.loads(json.dumps(payload))

    def _keep_row(
        row: dict[str, Any],
        *,
        child_key: str,
        parent_included: bool,
    ) -> tuple[dict[str, Any] | None, bool]:
        vals = _iter_dimension_values(row, source_field=source_field)
        row_match = value in vals
        current_parent_included = parent_included or row_match

        row_copy = dict(row)
        children = row.get(child_key) or []
        kept_children: list[dict[str, Any]] = []
        child_match = False

        if child_key == "details":
            for detail in children:
                detail_vals = _iter_dimension_values(detail, source_field=source_field)
                detail_match = value in detail_vals
                include_detail = detail_match or (current_parent_included and not detail_vals)
                if include_detail:
                    kept_children.append(dict(detail))
                child_match = child_match or detail_match
        else:
            next_child_key = {"chapters": "packages", "packages": "details"}[child_key]
            for child in children:
                kept, matched = _keep_row(
                    child,
                    child_key=next_child_key,
                    parent_included=current_parent_included,
                )
                if kept is not None:
                    kept_children.append(kept)
                child_match = child_match or matched

        include_row = row_match or child_match or (parent_included and not vals)
        if not include_row:
            return None, False
        row_copy[child_key] = kept_children
        return row_copy, row_match or child_match

    kept_phases: list[dict[str, Any]] = []
    for phase in payload.get("phases") or []:
        kept, _matched = _keep_row(phase, child_key="chapters", parent_included=False)
        if kept is not None:
            kept_phases.append(kept)

    filtered = json.loads(json.dumps(payload))
    filtered["phases"] = kept_phases
    start, end = resolve_chart_window_for_phases(
        kept_phases,
        fallback_start=str(payload.get("chartWindowStart") or "2026-06-01")[:10],
        fallback_end=str(payload.get("chartWindowEnd") or "2027-12-03")[:10],
    )
    filtered["chartWindowStart"] = start.isoformat()
    filtered["chartWindowEnd"] = end.isoformat()
    return filtered


def _variant_key(filters: dict[str, str]) -> str:
    selected = [f"{dim_id}:{filters[dim_id]}" for dim_id in filters if filters[dim_id]]
    if not selected:
        return "__all__"
    return "|".join(selected)


def build_payload_filter_variants(payload: dict[str, Any], *, max_variants: int = 300) -> list[dict[str, Any]]:
    """Build pre-rendered payload variants for all filter combinations.

    The variant model is generic and supports additional dimensions configured in
    sef-project-plan-reporting.json.
    """
    dimensions = payload.get("filterDimensions") or []
    if not dimensions:
        return [{"key": "__all__", "filters": {}, "payload": json.loads(json.dumps(payload))}]

    dim_ids = [str(d.get("id") or "") for d in dimensions if str(d.get("id") or "")]
    option_sets: list[list[str]] = []
    for dimension in dimensions:
        options = [""] + [str(opt) for opt in (dimension.get("options") or []) if str(opt)]
        option_sets.append(options)

    variants: list[dict[str, Any]] = []
    for picks in itertools.product(*option_sets):
        filters = {dim_id: pick for dim_id, pick in zip(dim_ids, picks)}
        filtered_payload = json.loads(json.dumps(payload))
        for dim_id, selected in filters.items():
            if selected:
                filtered_payload = filter_payload_by_dimension_value(
                    filtered_payload,
                    dimension_id=dim_id,
                    value=selected,
                )
        variants.append(
            {
                "key": _variant_key(filters),
                "filters": filters,
                "payload": filtered_payload,
            }
        )
        if len(variants) >= max_variants:
            break

    if not variants:
        return [{"key": "__all__", "filters": {}, "payload": json.loads(json.dumps(payload))}]
    return variants


def _truncate_label(text: str, max_chars: int = LABEL_MAX_CHARS) -> str:
    cleaned = str(text or "").strip()
    return cleaned


def _label_column_width(phases: list[dict[str, Any]]) -> float:
    labels: list[str] = []
    for phase in phases:
        labels.append(str(phase.get("summary") or phase.get("key") or ""))
        for chapter in phase.get("chapters") or []:
            labels.append(str(chapter.get("summary") or chapter.get("key") or ""))
            for package in chapter.get("packages") or []:
                labels.append(str(package.get("summary") or package.get("key") or ""))
                for detail in package.get("details") or []:
                    labels.append(str(detail.get("summary") or detail.get("key") or ""))
    longest = max((len(item.strip()) for item in labels if str(item).strip()), default=0)
    # Approximate pixel width for UI font and leave padding so the longest heading is fully visible.
    dynamic = 24 + (longest * 6.4)
    return max(float(LABEL_WIDTH), dynamic)


def _working_days_inclusive(start: date, end: date) -> int:
    if end < start:
        start, end = end, start
    total = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            total += 1
        current += timedelta(days=1)
    return total


def _label_with_duration_metrics(label: str, row: dict[str, Any]) -> str:
    start_raw = str(row.get("startDate") or "")[:10]
    end_raw = str(row.get("endDate") or "")[:10]
    try:
        start = date.fromisoformat(start_raw)
        end = date.fromisoformat(end_raw)
    except ValueError:
        return label
    if end < start:
        start, end = end, start
    elapsed_days = (end - start).days + 1
    work_days = _working_days_inclusive(start, end)
    weeks = elapsed_days / 7.0
    weeks_str = f"{weeks:.1f}".rstrip("0").rstrip(".")
    return f"{label} (ED {elapsed_days} | WD {work_days} | W {weeks_str})"


def _append_label_link(
    parts: list[str],
    *,
    text: str,
    x: float,
    y_center: float,
    url: str,
    tooltip: str,
    font_size: int = 10,
    font_weight: str = "600",
    fill: str | None = None,
    indent: float = LABEL_PAD_X,
    row_key: str = "",
    blocked_by_keys: list[str] | None = None,
    blocks_keys: list[str] | None = None,
    rows_by_key: dict[str, dict[str, Any]] | None = None,
    clip_path: str | None = "sef-plan-label-col",
) -> None:
    del indent
    text_fill = fill or ATL["ink"]
    data_key_attr = (
        f' data-sef-key="{html.escape(row_key)}" data-sef-row="1"' if row_key else ""
    )
    clip_attr = f' clip-path="url(#{clip_path})"' if clip_path else ""
    parts.append(
        f"<g{clip_attr}{data_key_attr}>{_svg_embedded_title(tooltip)}"
    )
    parts.append(f'<a href="{url}" target="_blank" rel="noopener">')
    visible_label = html.escape(_truncate_label(text))
    parts.append(
        f'<text x="{x:.1f}" y="{y_center:.1f}" text-anchor="start" dominant-baseline="middle" '
        f'font-family="{SVG_FONT}" font-size="{font_size}" fill="{text_fill}" '
        f'font-weight="{font_weight}">{visible_label}</text>'
    )
    parts.append("</a>")

    payload = _blocked_focus_payload(
        row_key=row_key,
        blocked_by_keys=blocked_by_keys,
        blocks_keys=blocks_keys,
        rows_by_key=rows_by_key,
    )
    if payload:
        linked_csv, link_tooltip, direction = payload
        icon_x = x + (len(_truncate_label(text)) * font_size * 0.58) + 8
        _append_block_link_icon(
            parts,
            row_key=row_key,
            direction=direction,
            linked_csv=html.escape(linked_csv),
            tooltip=link_tooltip,
            cx=icon_x,
            cy=y_center,
            size=10.0,
        )

    parts.append("</g>")


def _append_label_text(
    parts: list[str],
    *,
    text: str,
    x: float,
    y_center: float,
    tooltip: str,
    font_size: int = 10,
    font_weight: str = "600",
    fill: str | None = None,
    row_key: str = "",
    clip_path: str | None = "sef-plan-label-col",
) -> None:
    text_fill = fill or ATL["ink"]
    data_key_attr = (
        f' data-sef-key="{html.escape(row_key)}" data-sef-row="1"' if row_key else ""
    )
    clip_attr = f' clip-path="url(#{clip_path})"' if clip_path else ""
    parts.append(
        f"<g{clip_attr}{data_key_attr}>{_svg_embedded_title(tooltip)}"
    )
    parts.append(
        f'<text x="{x:.1f}" y="{y_center:.1f}" text-anchor="start" dominant-baseline="middle" '
        f'font-family="{SVG_FONT}" font-size="{font_size}" fill="{text_fill}" '
        f'font-weight="{font_weight}">{html.escape(_truncate_label(text))}</text>'
    )
    parts.append("</g>")


def _append_block_link_icon(
    parts: list[str],
    *,
    row_key: str,
    direction: str,
    linked_csv: str,
    tooltip: str,
    cx: float,
    cy: float,
    size: float,
) -> None:
    dir_value = direction if direction in {"blocked-by", "blocks", "both"} else "blocked-by"
    dir_glyph = "←" if dir_value == "blocked-by" else ("→" if dir_value == "blocks" else "↔")
    half = size / 2.0
    radius = max(1.5, size * 0.2)
    glyph_size = max(7.0, size * 0.78)
    dir_size = max(5.8, size * 0.46)
    parts.append(
        f'<g class="sef-block-link-icon" data-sef-key="{html.escape(row_key)}" data-sef-row="1" '
        f'data-sef-dir="{dir_value}" '
        f'onclick="sefToggleBlockedFocus(event,&apos;{html.escape(row_key)}&apos;,&apos;{linked_csv}&apos;)">'
        f'{_svg_embedded_title(tooltip)}'
        f'<rect class="sef-block-link-icon-bg" x="{cx - half:.1f}" y="{cy - half:.1f}" '
        f'width="{size:.1f}" height="{size:.1f}" rx="{radius:.1f}"/>'
        f'<text class="sef-block-link-icon-glyph" x="{cx:.1f}" y="{cy + 0.2:.1f}" '
        f'text-anchor="middle" dominant-baseline="middle" font-family="{SVG_FONT}" '
        f'font-size="{glyph_size:.1f}">&#128279;</text>'
        f'<text class="sef-block-link-icon-dir" x="{cx + (half * 0.58):.1f}" y="{cy + (half * 0.60):.1f}" '
        f'text-anchor="middle" dominant-baseline="middle" font-family="{SVG_FONT}" '
        f'font-size="{dir_size:.1f}">{dir_glyph}</text>'
        "</g>"
    )


def _blocked_focus_payload(
    *,
    row_key: str,
    blocked_by_keys: list[str] | None,
    blocks_keys: list[str] | None,
    rows_by_key: dict[str, dict[str, Any]] | None,
) -> tuple[str, str, str] | None:
    source_key = str(row_key or "").strip()
    if not source_key:
        return None
    blockers = [str(key).strip() for key in (blocked_by_keys or []) if str(key).strip()]
    blockers = list(dict.fromkeys(blockers))
    blocked_rows = [str(key).strip() for key in (blocks_keys or []) if str(key).strip()]
    blocked_rows = list(dict.fromkeys(blocked_rows))
    linked_keys = list(dict.fromkeys([*blockers, *blocked_rows]))
    if not linked_keys:
        return None

    direction = "both" if blockers and blocked_rows else ("blocked-by" if blockers else "blocks")
    blocked_count = len(blockers)
    blocks_count = len(blocked_rows)

    tooltip_lines = [f"{source_key} is blocked by:", f"{source_key} dependency direction:"]
    if direction == "both":
        tooltip_lines.append(f"- Depends on {blocked_count} item(s) and blocks {blocks_count} item(s)")
    elif direction == "blocked-by":
        tooltip_lines.append(f"- Depends on {blocked_count} item(s)")
    else:
        tooltip_lines.append(f"- Blocks {blocks_count} item(s)")
    tooltip_lines.append("Blocked by:")
    linked_rows = rows_by_key or {}
    for blocker in blockers:
        blocker_summary = str((linked_rows.get(blocker) or {}).get("summary") or "").strip()
        if blocker_summary:
            tooltip_lines.append(f"- {blocker}: {blocker_summary}")
        else:
            tooltip_lines.append(f"- {blocker}")
    if blocked_rows:
        tooltip_lines.append("Also links to:")
        for blocked_key in blocked_rows:
            blocked_summary = str((linked_rows.get(blocked_key) or {}).get("summary") or "").strip()
            if blocked_summary:
                tooltip_lines.append(f"- {blocked_key}: {blocked_summary}")
            else:
                tooltip_lines.append(f"- {blocked_key}")
    tooltip_lines.append("Click to focus this item and its linked items.")
    return ",".join(linked_keys), "\n".join(tooltip_lines), direction


def _bar_tooltip(row: dict[str, Any]) -> str:
    lines = [
        f"{row.get('key')}: {row.get('summary')}",
        f"Timeline: {row.get('startDate')} to {row.get('endDate')}",
    ]
    status = row.get("status")
    if status:
        lines.append(f"Status: {status}")
    workstreams = row.get("workstreams") or row.get("components") or []
    if workstreams:
        lines.append(f"Workstream: {', '.join(str(name) for name in workstreams)}")
    scope = row.get("scopeRollup")
    if scope:
        issue_count = int(scope.get("issueCount") or float(scope.get("totalWeight") or 0))
        lines.append(f"Scope: {issue_count} issues (Scope links)")
    return "\n".join(lines)


def _is_milestone_row(row: dict[str, Any]) -> bool:
    if bool(row.get("isMeetingGate")):
        return True
    issue_type = str(row.get("issueType") or "").strip().lower()
    if "milestone" in issue_type:
        return True
    summary = str(row.get("summary") or "").upper()
    return "MILESTONE" in summary


def _milestone_icon_url(row: dict[str, Any]) -> str:
    """Return an absolute Jira icon URL for Meeting Gate milestones, if available."""
    if not bool(row.get("isMeetingGate")):
        return ""
    raw = str(row.get("issueTypeIconUrl") or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if raw.startswith("/"):
        return f"{JIRA_SERVER}{raw}"
    return f"{JIRA_SERVER}/{raw}"


def _append_timeline_bar(
    parts: list[str],
    *,
    row: dict[str, Any],
    x1: float,
    bar_y: float,
    bar_w: float,
    bar_h: float,
    fill: str,
    opacity: float,
    rx: int = 2,
    role: str = "",
    scope_overlay_opacity: float = SCOPE_OVERLAY_OPACITY,
    blocked_by_keys: list[str] | None = None,
    blocks_keys: list[str] | None = None,
    rows_by_key: dict[str, dict[str, Any]] | None = None,
    render_scope_overlay: bool = True,
    render_dependency_icon: bool = True,
) -> None:
    row_key = str(row.get("key") or "").strip()
    focus_payload = _blocked_focus_payload(
        row_key=row_key,
        blocked_by_keys=blocked_by_keys,
        blocks_keys=blocks_keys,
        rows_by_key=rows_by_key,
    )
    role_attr = f' data-sef-role="{html.escape(role)}"' if role else ""
    issue_type = str(row.get("issueType") or "")
    issue_type_attr = f' data-sef-issue-type="{html.escape(issue_type)}"'
    is_gate = bool(row.get("isMeetingGate")) or "gate" in issue_type.casefold()
    special_attr = (
        f' data-sef-special="gate"' if is_gate
        else f' data-sef-special="milestone"' if _is_milestone_row(row)
        else ""
    )
    dependency_attr = ' data-sef-has-dependency="1"' if focus_payload else ""
    data_key_attr = (
        f' data-sef-key="{html.escape(row_key)}" data-sef-row="1"{role_attr}' if row_key else role_attr
    )
    parts.append(
        f'<g{data_key_attr}{issue_type_attr}{special_attr}{dependency_attr}>'
        f'{_svg_embedded_title(_bar_tooltip(row))}'
    )
    if _is_milestone_row(row):
        cx = x1
        icon_url = _milestone_icon_url(row)
        if icon_url:
            size = max(10.0, min(16.0, bar_h + 4.0))
            y = bar_y + max((bar_h - size) / 2.0, 0.0)
            parts.append(
                f'<image href="{html.escape(icon_url)}" x="{cx - size / 2.0:.1f}" y="{y:.1f}" '
                f'width="{size:.1f}" height="{size:.1f}" preserveAspectRatio="xMidYMid meet"/>'
            )
        else:
            tri_h = max(8.0, min(14.0, bar_h + 4.0))
            tri_w = tri_h
            top = bar_y + max((bar_h - tri_h) / 2.0, 0.0)
            points = (
                f"{cx:.1f},{top:.1f} "
                f"{cx - tri_w / 2.0:.1f},{top + tri_h:.1f} "
                f"{cx + tri_w / 2.0:.1f},{top + tri_h:.1f}"
            )
            parts.append(
                f'<polygon points="{points}" fill="{MILESTONE_TRIANGLE_FILL}" opacity="0.95"/>'
            )
        if focus_payload and render_dependency_icon:
            linked_csv, link_tooltip, direction = focus_payload
            _append_block_link_icon(
                parts,
                row_key=row_key,
                direction=direction,
                linked_csv=html.escape(linked_csv),
                tooltip=link_tooltip,
                cx=cx + 9.0,
                cy=bar_y + (bar_h / 2.0),
                size=max(9.0, min(11.0, bar_h)),
            )
        parts.append("</g>")
        return
    parts.append(
        f'<rect x="{x1:.1f}" y="{bar_y:.1f}" width="{bar_w:.1f}" '
        f'height="{bar_h:.1f}" rx="{rx}" fill="{fill}" opacity="{opacity}"/>'
    )
    scope = row.get("scopeRollup")
    if scope and render_scope_overlay:
        segments = lane_bar_segments(scope, segment_order=timeline_bar_segment_order())
        if segments:
            append_scope_composition_overlay(
                parts,
                rollup=scope,
                segments=segments,
                x0=x1,
                y0=bar_y,
                bar_w=bar_w,
                bar_h=bar_h,
                overlay_opacity=scope_overlay_opacity,
                link_class="block-scope-segment",
            )

    if focus_payload and render_dependency_icon:
        linked_csv, link_tooltip, direction = focus_payload
        icon_size = max(9.0, min(12.0, bar_h))
        icon_x = x1 + max(icon_size / 2.0 + 1.0, bar_w - icon_size / 2.0 - 1.0)
        icon_y = bar_y + (bar_h / 2.0)
        _append_block_link_icon(
            parts,
            row_key=row_key,
            direction=direction,
            linked_csv=html.escape(linked_csv),
            tooltip=link_tooltip,
            cx=icon_x,
            cy=icon_y,
            size=icon_size,
        )
    parts.append("</g>")


def _iter_milestone_dependency_edges(phases: list[dict[str, Any]]) -> list[tuple[str, str]]:
    rows_by_key: dict[str, dict[str, Any]] = {}
    edges: list[tuple[str, str]] = []

    for row in _iter_timeline_rows(phases):
        key = str(row.get("key") or "").strip()
        if key:
            rows_by_key[key] = row

    for row in rows_by_key.values():
        blocked_key = str(row.get("key") or "").strip()
        if not blocked_key:
            continue
        for blocker in row.get("blockedByKeys") or []:
            blocker_key = str(blocker or "").strip()
            if blocker_key and blocker_key != blocked_key:
                blocker_row = rows_by_key.get(blocker_key)
                blocked_row = rows_by_key.get(blocked_key)
                if _is_milestone_row(blocked_row or {}) or _is_milestone_row(blocker_row or {}):
                    edges.append((blocker_key, blocked_key))

    return list(dict.fromkeys(edges))


def _timeline_rows_by_key(phases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in _iter_timeline_rows(phases):
        key = str(row.get("key") or "").strip()
        if key:
            rows[key] = row
    return rows


def _build_block_link_maps(phases: list[dict[str, Any]]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    blocked_by: dict[str, list[str]] = {}
    blocks: dict[str, list[str]] = {}
    for row in _iter_timeline_rows(phases):
        blocked_key = str(row.get("key") or "").strip()
        if not blocked_key:
            continue
        for blocker in row.get("blockedByKeys") or []:
            blocker_key = str(blocker or "").strip()
            if not blocker_key or blocker_key == blocked_key:
                continue
            blocked_by.setdefault(blocked_key, []).append(blocker_key)
            blocks.setdefault(blocker_key, []).append(blocked_key)

    for key, values in list(blocked_by.items()):
        blocked_by[key] = list(dict.fromkeys(values))
    for key, values in list(blocks.items()):
        blocks[key] = list(dict.fromkeys(values))
    return blocked_by, blocks


def _append_dependency_connectors(
    parts: list[str],
    *,
    edges: list[tuple[str, str]],
    row_positions: dict[str, tuple[float, float, float]],
) -> None:
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    for blocker_key, blocked_key in edges:
        blocker = row_positions.get(blocker_key)
        blocked = row_positions.get(blocked_key)
        if not blocker or not blocked:
            continue
        blocker_start, blocker_y, blocker_end = blocker
        blocked_start, blocked_y, _blocked_end = blocked

        blocker_is_milestone = abs(blocker_end - blocker_start) < 0.1
        sx = blocker_start if blocker_is_milestone else blocker_end
        ex = blocked_start
        sy = blocker_y
        ey = blocked_y

        dx = ex - sx
        dy = ey - sy
        direction = 1.0 if dx >= 0 else -1.0
        abs_dx = max(6.0, abs(dx))
        # Horizontal runway before/after the curve: fixed minimum travel for visual clarity.
        lead_mag = _clamp(abs_dx * 0.28, DEPENDENCY_MIN_HORIZONTAL_RUN, 64.0)
        lead = lead_mag * direction
        run_start_x = sx + lead
        run_end_x = ex - lead

        # Match sketch intent: horizontal exit -> one easing curve -> straight diagonal -> horizontal entry.
        span = abs(run_end_x - run_start_x)
        tension = _clamp((span * 0.24) + 8.0, 10.0, 30.0)

        join_t = 0.30
        join_x = run_start_x + ((run_end_x - run_start_x) * join_t)
        join_y = sy + (dy * join_t)

        # Make the curve land with a tangent aligned to the straight middle segment.
        seg_dx = run_end_x - join_x
        seg_dy = ey - join_y
        c1x = run_start_x + (direction * tension)
        c1y = sy
        c2x = join_x - (seg_dx * 0.35)
        c2y = join_y - (seg_dy * 0.35)

        path_d = (
            f"M {sx:.1f} {sy:.1f} "
            f"L {run_start_x:.1f} {sy:.1f} "
            f"C {c1x:.1f} {c1y:.1f}, {c2x:.1f} {c2y:.1f}, {join_x:.1f} {join_y:.1f} "
            f"L {run_end_x:.1f} {ey:.1f} "
            f"L {ex:.1f} {ey:.1f}"
        )
        tooltip = f"Dependency: {blocker_key} blocks {blocked_key}"
        parts.append(
            f'<g data-sef-dep-from="{html.escape(blocker_key)}" '
            f'data-sef-dep-to="{html.escape(blocked_key)}">{_svg_embedded_title(tooltip)}'
        )
        parts.append(
            f'<path d="{path_d}" '
            f'stroke="{DEPENDENCY_STROKE}" stroke-width="{DEPENDENCY_STROKE_WIDTH}" '
            f'stroke-linecap="round" stroke-linejoin="round" '
            f'fill="none" marker-end="url(#dep-arrow)"/>'
        )
        parts.append("</g>")


def _package_block_height(package: dict[str, Any]) -> int:
    details = package.get("details") or []
    return STREAM_ROW_HEIGHT + len(details) * DETAIL_ROW_HEIGHT


def _chapter_block_height(chapter: dict[str, Any]) -> int:
    packages = chapter.get("packages") or []
    content = CHAPTER_ROW_HEIGHT + sum(_package_block_height(package) for package in packages)
    return content + 2 * BLOCK_PAD_Y


def _plot_height(phases: list[dict[str, Any]]) -> int:
    if not phases:
        return PHASE_ROW_HEIGHT
    total = 0
    for index, phase in enumerate(phases):
        if index > 0:
            total += PHASE_GAP
        total += PHASE_ROW_HEIGHT
        chapters = phase.get("chapters") or []
        for chapter_index, chapter in enumerate(chapters):
            if chapter_index > 0:
                total += BLOCK_GAP
            total += _chapter_block_height(chapter)
    return total


# Project plan uses a wider per-day scale and is horizontally scrollable.
SEF_PLAN_PX_PER_DAY = 8.0


def _plot_width(span_days: int, *, px_per_day: float = EPIC_CHART_PX_PER_DAY) -> float:
    raw = span_days * px_per_day
    return max(float(QUARTERLY_REPORT_MIN_PLOT_WIDTH), min(float(QUARTERLY_REPORT_MAX_SVG_WIDTH), raw))


def _sef_plan_plot_width(span_days: int, *, px_per_day: float = SEF_PLAN_PX_PER_DAY) -> float:
    """Uncapped plot width for the project plan — container scrolls instead."""
    return max(float(QUARTERLY_REPORT_MIN_PLOT_WIDTH), span_days * px_per_day)


def sef_project_plan_timeline_svg(
    payload: dict[str, Any],
    *,
    px_per_day: float = SEF_PLAN_PX_PER_DAY,
    workstream_colors: SefProjectPlanComponentColors | None = None,
) -> str:
    phases = payload.get("phases") or []
    if not phases:
        return '<p class="footnote">No plan blocks. Run fetch_sef_project_plan_timeline.py --write.</p>'

    colors = workstream_colors or load_sef_project_plan_component_colors()

    def row_fill(row: dict[str, Any]) -> str:
        return colors.fill_for_row(row)

    x_min, x_max = _payload_chart_window(payload)
    span_days = max(1, (x_max - x_min).days)
    plot_h = _plot_height(phases)
    MILESTONE_LABEL_ZONE = 80   # px above plot for stacked milestone labels
    plot_top = CALENDAR_TOP + MILESTONE_LABEL_ZONE
    plot_bottom = plot_top + plot_h
    svg_height = plot_bottom + _svg_x_bottom_margin()
    plot_w = _sef_plan_plot_width(span_days, px_per_day=px_per_day)
    plot_left = _label_column_width(phases)
    plot_right = plot_left + plot_w
    width = plot_right + RIGHT_PAD + MILESTONE_RIGHT_LABEL_PAD

    def x_for(day: date) -> float:
        offset = max(0, min(span_days, (day - x_min).days))
        return plot_left + offset / span_days * plot_w

    def _row_end_x(row: dict[str, Any], x1: float, bar_w: float) -> float:
        return x1 if _is_milestone_row(row) else (x1 + bar_w)

    row_positions: dict[str, tuple[float, float, float]] = {}
    parent_by_key: dict[str, str] = {}
    rows_by_key = _timeline_rows_by_key(phases)
    blocked_by_map, blocks_map = _build_block_link_maps(phases)
    milestone_markers: list[tuple[float, str, date, bool]] = []  # (x, label, day, is_gate)

    for milestone in payload.get("milestones") or []:
        m_start = _parse_day(str(milestone.get("startDate") or "")[:10])
        if m_start is None:
            continue
        m_label = str(milestone.get("summary") or milestone.get("key") or "Milestone")
        m_x = x_for(m_start)
        milestone_markers.append((m_x, m_label, m_start, bool(milestone.get("isMeetingGate"))))

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{svg_height}" '
        f'viewBox="0 0 {width} {svg_height}" preserveAspectRatio="xMinYMin meet" '
        f'role="img" aria-label="SEF integrated project plan timeline">',
        f'<rect x="0" y="0" width="{width}" height="{svg_height}" fill="#ffffff"/>',
        "<defs>"
        f'<clipPath id="sef-plan-label-col">'
        f'<rect x="0" y="{plot_top}" width="{plot_left - 8}" height="{plot_h}"/>'
        f"</clipPath>"
        f'<marker id="dep-arrow" markerWidth="8" markerHeight="8" refX="8" refY="4" orient="auto" markerUnits="userSpaceOnUse">'
        f'<path d="M 0 0 L 8 4 L 0 8 z" fill="{DEPENDENCY_STROKE}"/>'
        f"</marker></defs>",
    ]

    parts.append(
        f'<line x1="{plot_left}" y1="{plot_top}" x2="{plot_left}" y2="{plot_bottom}" '
        f'stroke="{ATL["line"]}" stroke-width="1"/>'
    )
    parts.append('<g id="sef-x-axis-top">')
    parts.append(
        f'<line x1="{plot_left}" y1="{plot_top}" x2="{plot_right}" y2="{plot_top}" '
        f'stroke="{ATL["line"]}" stroke-width="1"/>'
    )

    # Top axis labels: same scale as bottom axis (week starts + month starts).
    top_week_y = plot_top - 8
    top_month_y = plot_top - 24
    for week_start in _week_start_dates(x_min, x_max):
        wx = x_for(week_start)
        parts.append(
            f'<line x1="{wx:.1f}" y1="{plot_top}" x2="{wx:.1f}" y2="{plot_top - 4:.1f}" '
            f'stroke="{ATL["line"]}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{wx:.1f}" y="{top_week_y:.1f}" text-anchor="middle" font-family="{SVG_FONT}" '
            f'font-size="{CHART_AXIS_FONT}" fill="{ATL["text_subtle"]}">'
            f'{html.escape(week_start.strftime("%d"))}</text>'
        )

    top_month = date(x_min.year, x_min.month, 1)
    while top_month <= x_max:
        if top_month >= x_min:
            mx = x_for(top_month)
            parts.append(
                f'<text x="{mx:.0f}" y="{top_month_y:.1f}" text-anchor="middle" font-family="{SVG_FONT}" '
                f'font-size="{CHART_AXIS_FONT}" fill="{ATL["text_subtle"]}" font-weight="600">'
                f'{html.escape(top_month.strftime("%b"))}</text>'
            )
        if top_month.month == 12:
            top_month = date(top_month.year + 1, 1, 1)
        else:
            top_month = date(top_month.year, top_month.month + 1, 1)
    parts.append("</g>")

    parts.append(f'<g id="sef-x-axis" data-sef-orig-bottom="{plot_bottom:.1f}">')
    parts.append(
        f'<line x1="{plot_left}" y1="{plot_bottom}" x2="{plot_right}" y2="{plot_bottom}" '
        f'stroke="{ATL["line"]}" stroke-width="1"/>'
    )

    # Dashed vertical lines at each month start.
    _month = date(x_min.year, x_min.month, 1)
    while _month <= x_max:
        if _month >= x_min:
            _mx = x_for(_month)
            parts.append(
                f'<line x1="{_mx:.1f}" y1="{plot_top}" x2="{_mx:.1f}" y2="{plot_bottom}" '
                f'stroke="#555555" stroke-width="0.6" stroke-dasharray="4 3" opacity="0.5"/>'
            )
        if _month.month == 12:
            _month = date(_month.year + 1, 1, 1)
        else:
            _month = date(_month.year, _month.month + 1, 1)

    _svg_x_axis_labels(
        parts,
        x_min=x_min,
        x_max=x_max,
        plot_bottom=plot_bottom,
        plot_left=plot_left,
        plot_right=plot_right,
        x_for=x_for,
    )
    parts.append("</g>")

    chapter_manifest: list[dict] = []
    holidays = payload.get("holidays") or []
    y_cursor = plot_top

    # Non-working day bands — weekends (grey) and public holidays (slightly
    # darker grey) rendered as a background layer before chart content.
    hol_map = {
        str(h.get("date") or "")[:10]: str(h.get("name") or "Public Holiday")
        for h in holidays
        if str(h.get("date") or "")[:10]
    }
    _cur = x_min
    while _cur <= x_max:
        if _cur.weekday() == 5:  # Saturday — render Sat+Sun as one block
            hx = x_for(_cur)
            end_x = x_for(min(_cur + timedelta(days=2), x_max + timedelta(days=1)))
            band_w = max(end_x - hx, 2.0)
            parts.append(
                f'<rect x="{hx:.1f}" y="{plot_top}" width="{band_w:.1f}" '
                f'height="{plot_h:.1f}" fill="#d4d4d4" opacity="0.45"/>'
            )
        elif _cur.weekday() < 5 and _cur.isoformat() in hol_map:  # weekday PH
            hx = x_for(_cur)
            end_x = x_for(_cur + timedelta(days=1))
            band_w = max(end_x - hx, 3.0)
            hol_name = html.escape(hol_map[_cur.isoformat()])
            parts.append(
                f'<rect x="{hx:.1f}" y="{plot_top}" width="{band_w:.1f}" '
                f'height="{plot_h:.1f}" fill="#b0b0b0" opacity="0.50">'
                f'<title>{hol_name}</title></rect>'
            )
        _cur += timedelta(days=1)

    for phase_index, phase in enumerate(phases):
        if phase_index > 0:
            y_cursor += PHASE_GAP
            parts.append(
                f'<rect class="sef-phase-divider" x="0" y="{y_cursor - PHASE_GAP / 2:.1f}" '
                f'width="{plot_right:.1f}" height="{PHASE_GAP:.1f}" />'
            )

        phase_label = str(phase.get("summary") or phase.get("key") or "")
        phase_key = str(phase.get("key") or "")
        phase_start = date.fromisoformat(str(phase.get("startDate"))[:10])
        phase_end = date.fromisoformat(str(phase.get("endDate"))[:10])

        if phase_key:
            parent_by_key[phase_key] = ""
            phase_start = date.fromisoformat(str(phase.get("startDate"))[:10])
            phase_end = date.fromisoformat(str(phase.get("endDate"))[:10])
            phase_x1 = x_for(phase_start)
            phase_x2 = x_for(phase_end)
            phase_bar_w = max(phase_x2 - phase_x1, 2.0)
            phase_row_cy = y_cursor + PHASE_ROW_HEIGHT / 2
            phase_bar_y = y_cursor + (PHASE_ROW_HEIGHT - PHASE_BAR_HEIGHT) / 2
            phase_fill = row_fill(phase)

            _append_timeline_bar(
                parts,
                row=phase,
                x1=phase_x1,
                bar_y=phase_bar_y,
                bar_w=phase_bar_w,
                bar_h=PHASE_BAR_HEIGHT,
                fill=phase_fill,
                opacity=BAR_OPACITY,
                role="phase-bar",
                scope_overlay_opacity=SCOPE_OVERLAY_OPACITY,
                blocked_by_keys=blocked_by_map.get(phase_key),
                blocks_keys=blocks_map.get(phase_key),
                rows_by_key=rows_by_key,
            )
            row_positions[phase_key] = (phase_x1, phase_row_cy, _row_end_x(phase, phase_x1, phase_bar_w))
            _append_label_link(
                parts,
                text=_label_with_duration_metrics(phase_label, phase),
                x=LABEL_PAD_X,
                y_center=phase_row_cy,
                url=f"{JIRA_SERVER}/browse/{html.escape(phase_key)}",
                tooltip=_bar_tooltip(phase),
                font_size=13,
                font_weight="700",
                row_key=phase_key,
                blocked_by_keys=blocked_by_map.get(phase_key),
                blocks_keys=blocks_map.get(phase_key),
                rows_by_key=rows_by_key,
            )
            y_cursor += PHASE_ROW_HEIGHT

        chapters = phase.get("chapters") or []
        for chapter_index, chapter in enumerate(chapters):
            if chapter_index > 0:
                y_cursor += BLOCK_GAP
            block_h = _chapter_block_height(chapter)
            block_y = y_cursor
            y0 = block_y + BLOCK_PAD_Y
            row_cy = y0 + CHAPTER_ROW_HEIGHT / 2

            key = str(chapter.get("key") or "")
            summary = str(chapter.get("summary") or key)
            has_packages = bool(chapter.get("packages"))
            sub_h = block_h - BLOCK_PAD_Y * 2 - CHAPTER_ROW_HEIGHT
            if key:
                parent_by_key[key] = phase_key

            if key:
                parts.append(
                    f'<g id="sef-ch-{html.escape(key)}" transform="translate(0,0)" '
                    f'data-sub-h="{int(sub_h)}" '
                    f'data-collapsed-h="{BLOCK_PAD_Y * 2 + CHAPTER_ROW_HEIGHT}">'
                )

            start_day = date.fromisoformat(str(chapter.get("startDate"))[:10])
            end_day = date.fromisoformat(str(chapter.get("endDate"))[:10])
            x1 = x_for(start_day)
            x2 = x_for(end_day)
            bar_w = max(x2 - x1, 2.0)
            bar_y = y0 + (CHAPTER_ROW_HEIGHT - CHAPTER_BAR_HEIGHT) / 2
            fill = row_fill(chapter)
            border_id_attr = f'id="sef-bd-{html.escape(key)}" ' if key else ""
            parts.append(
                f'<rect {border_id_attr}'
                f'x="0" y="{block_y:.1f}" width="{plot_right:.1f}" height="{block_h:.1f}" '
                f'data-sef-key="{html.escape(key)}" data-sef-row="1" '
                f'data-sef-role="chapter-border" data-sef-orig-y="{block_y:.1f}" '
                f'data-sef-orig-height="{block_h:.1f}" '
                f'fill="none" stroke="{ATL["ink"]}" stroke-width="{BLOCK_BORDER_WIDTH}"/>'
            )

            same_window_as_phase = (
                str(chapter.get("startDate") or "")[:10] == phase_start.isoformat()
                and str(chapter.get("endDate") or "")[:10] == phase_end.isoformat()
            )
            draw_chapter_bar = bool(key) and not (len(chapters) == 1 and same_window_as_phase)
            if draw_chapter_bar:
                _append_timeline_bar(
                    parts,
                    row=chapter,
                    x1=x1,
                    bar_y=bar_y,
                    bar_w=bar_w,
                    bar_h=CHAPTER_BAR_HEIGHT,
                    fill=fill,
                    opacity=BAR_OPACITY,
                    role="chapter-bar",
                    scope_overlay_opacity=SCOPE_OVERLAY_OPACITY,
                    blocked_by_keys=blocked_by_map.get(key),
                    blocks_keys=blocks_map.get(key),
                    rows_by_key=rows_by_key,
                )
            if key:
                row_positions[key] = (x1, row_cy, _row_end_x(chapter, x1, bar_w))
                _append_label_link(
                    parts,
                    text=_label_with_duration_metrics(summary, chapter),
                    x=LABEL_PAD_X,
                    y_center=row_cy,
                    url=f"{JIRA_SERVER}/browse/{html.escape(key)}",
                    tooltip=_bar_tooltip(chapter),
                    row_key=key,
                    blocked_by_keys=blocked_by_map.get(key),
                    blocks_keys=blocks_map.get(key),
                    rows_by_key=rows_by_key,
                )
            else:
                _append_label_text(
                    parts,
                    text=_label_with_duration_metrics(summary, chapter),
                    x=LABEL_PAD_X,
                    y_center=row_cy,
                    tooltip=_bar_tooltip(chapter),
                )

            if has_packages and key:
                chev_x = max(LABEL_PAD_X - 3, 6)
                parts.append(
                    f'<text id="sef-chev-{html.escape(key)}" '
                    f'data-sef-key="{html.escape(key)}" data-sef-row="1" '
                    f'x="{chev_x:.1f}" y="{row_cy + 4:.1f}" '
                    f'font-family="{SVG_FONT}" font-size="10" fill="{ATL["ink"]}" '
                    f'style="cursor:pointer;user-select:none" text-anchor="end" '
                    f'onclick="sefToggleChapter(event,&apos;{html.escape(key)}&apos;)">&#x25BC;</text>'
                )
                parts.append(f'<g id="sef-sub-{html.escape(key)}">')

            sub_y = y0 + CHAPTER_ROW_HEIGHT
            for pkg_index, package in enumerate(chapter.get("packages") or []):
                p_key = str(package.get("key") or "")
                if p_key:
                    parent_by_key[p_key] = key
                # Alternating swimlane background for this package + its details.
                pkg_lane_h = STREAM_ROW_HEIGHT + len(package.get("details") or []) * DETAIL_ROW_HEIGHT
                lane_fill = SWIMLANE_FILLS[pkg_index % len(SWIMLANE_FILLS)]
                parts.append(
                    f'<rect x="0" y="{sub_y:.1f}" width="{plot_right:.1f}" '
                    f'data-sef-key="{html.escape(p_key)}" data-sef-row="1" '
                    f'data-sef-role="package-lane" data-sef-orig-y="{sub_y:.1f}" '
                    f'data-sef-orig-height="{pkg_lane_h:.1f}" '
                    f'height="{pkg_lane_h:.1f}" fill="{lane_fill}" opacity="0.55"/>'
                )

                sub_cy = sub_y + STREAM_ROW_HEIGHT / 2
                p_start = date.fromisoformat(str(package.get("startDate"))[:10])
                p_end = date.fromisoformat(str(package.get("endDate"))[:10])
                px1 = x_for(p_start)
                px2 = x_for(p_end)
                p_bar_w = max(px2 - px1, 2.0)
                p_bar_y = sub_y + (STREAM_ROW_HEIGHT - STREAM_BAR_HEIGHT) / 2
                p_summary = str(package.get("summary") or p_key)
                p_fill = row_fill(package)
                p_opacity = BAR_OPACITY
                _append_timeline_bar(
                    parts,
                    row=package,
                    x1=px1,
                    bar_y=p_bar_y,
                    bar_w=p_bar_w,
                    bar_h=STREAM_BAR_HEIGHT,
                    fill=p_fill,
                    opacity=p_opacity,
                    rx=1,
                    role="package-bar",
                    scope_overlay_opacity=SUB_SCOPE_OVERLAY_OPACITY,
                    blocked_by_keys=blocked_by_map.get(p_key),
                    blocks_keys=blocks_map.get(p_key),
                    rows_by_key=rows_by_key,
                )
                if p_key:
                    row_positions[p_key] = (px1, sub_cy, _row_end_x(package, px1, p_bar_w))
                if _is_milestone_row(package):
                    milestone_markers.append((px1, p_summary, p_start, bool(package.get("isMeetingGate"))))
                _append_label_link(
                    parts,
                    text=_label_with_duration_metrics(p_summary, package),
                    x=SUB_LABEL_INDENT,
                    y_center=sub_cy,
                    url=f"{JIRA_SERVER}/browse/{html.escape(p_key)}",
                    tooltip=_bar_tooltip(package),
                    font_size=10,
                    font_weight="400",
                    fill=ATL["text_subtle"],
                    row_key=p_key,
                    blocked_by_keys=blocked_by_map.get(p_key),
                    blocks_keys=blocks_map.get(p_key),
                    rows_by_key=rows_by_key,
                )
                sub_y += STREAM_ROW_HEIGHT

                for detail in package.get("details") or []:
                    detail_cy = sub_y + DETAIL_ROW_HEIGHT / 2
                    d_start = date.fromisoformat(str(detail.get("startDate"))[:10])
                    d_end = date.fromisoformat(str(detail.get("endDate"))[:10])
                    dx1 = x_for(d_start)
                    dx2 = x_for(d_end)
                    d_bar_w = max(dx2 - dx1, 2.0)
                    d_bar_y = sub_y + (DETAIL_ROW_HEIGHT - DETAIL_BAR_HEIGHT) / 2
                    d_key = str(detail.get("key") or "")
                    if d_key:
                        parent_by_key[d_key] = p_key
                    d_summary = str(detail.get("summary") or d_key)
                    d_fill = row_fill(detail)
                    d_opacity = BAR_OPACITY
                    _append_timeline_bar(
                        parts,
                        row=detail,
                        x1=dx1,
                        bar_y=d_bar_y,
                        bar_w=d_bar_w,
                        bar_h=DETAIL_BAR_HEIGHT,
                        fill=d_fill,
                        opacity=d_opacity,
                        rx=1,
                        role="detail-bar",
                        scope_overlay_opacity=DETAIL_SCOPE_OVERLAY_OPACITY,
                        blocked_by_keys=blocked_by_map.get(d_key),
                        blocks_keys=blocks_map.get(d_key),
                        rows_by_key=rows_by_key,
                    )
                    if d_key:
                        row_positions[d_key] = (dx1, detail_cy, _row_end_x(detail, dx1, d_bar_w))
                    if _is_milestone_row(detail):
                        milestone_markers.append((dx1, d_summary, d_start, bool(detail.get("isMeetingGate"))))
                    _append_label_link(
                        parts,
                        text=_label_with_duration_metrics(d_summary, detail),
                        x=DETAIL_LABEL_INDENT,
                        y_center=detail_cy,
                        url=f"{JIRA_SERVER}/browse/{html.escape(d_key)}",
                        tooltip=_bar_tooltip(detail),
                        font_size=9,
                        font_weight="400",
                        fill=ATL["text_subtle"],
                        row_key=d_key,
                        blocked_by_keys=blocked_by_map.get(d_key),
                        blocks_keys=blocks_map.get(d_key),
                        rows_by_key=rows_by_key,
                    )
                    sub_y += DETAIL_ROW_HEIGHT
                parts.append('</g>')  # close sub-rows group
            if key:
                chapter_manifest.append({
                    "key": key,
                    "subH": int(sub_h),
                    "collapsedH": BLOCK_PAD_Y * 2 + CHAPTER_ROW_HEIGHT,
                })
                parts.append('</g>')  # close chapter group
            y_cursor += block_h

    # Embed chapter manifest for collapse/expand JS.
    if chapter_manifest:
        import json as _json
        manifest_str = _json.dumps(chapter_manifest).replace('"', '&quot;')
        parts.append(
            f'<text id="sef-cm" data-chapters="{manifest_str}" '
            f'visibility="hidden" fill="none">.</text>'
        )

    if parent_by_key:
        import json as _json
        parent_map_str = _json.dumps(parent_by_key).replace('"', '&quot;')
        parts.append(
            f'<text id="sef-pm" data-parent-map="{parent_map_str}" '
            f'visibility="hidden" fill="none">.</text>'
        )

    # Milestone vertical gridlines and stacked labels.
    if milestone_markers:
        LABEL_FONT = 8
        LABEL_LINE_H = 11
        LABEL_ZONE_TOP = CALENDAR_TOP + 4
        LABEL_BUCKET_PX = 32  # minimum px gap before stacking to next row

        # Sort by x so we can assign stacking rows left-to-right.
        sorted_markers = sorted(dict.fromkeys(  # dedupe same x+label+day+kind
            (round(x, 1), lbl, day, is_gate) for x, lbl, day, is_gate in milestone_markers
        ))
        # Assign each marker a row index (0 = topmost) to avoid label overlap.
        row_for: list[int] = []
        row_max_x: list[float] = []  # rightmost x used per row so far
        for mx, mlabel, mday, _is_gate in sorted_markers:
            assigned = False
            short_label = mlabel.split("|")[-1].strip() if "|" in mlabel else mlabel
            short_label = short_label[:30]
            label_text = f"{short_label} ({mday:%d/%m})"
            for r_idx, rmax in enumerate(row_max_x):
                if mx - rmax >= LABEL_BUCKET_PX:
                    row_for.append(r_idx)
                    row_max_x[r_idx] = mx + len(label_text) * 5
                    assigned = True
                    break
            if not assigned:
                row_for.append(len(row_max_x))
                row_max_x.append(mx + len(label_text) * 5)

        for i, (mx, mlabel, mday, is_gate) in enumerate(sorted_markers):
            label_y = LABEL_ZONE_TOP + row_for[i] * LABEL_LINE_H
            line_stroke = "#000000" if is_gate else "#ff6b6b"
            line_opacity = "0.65" if is_gate else "0.7"
            label_fill = "#000000" if is_gate else "#cc2200"
            label_weight = "600" if is_gate else "500"
            # Vertical dashed light-red line.
            parts.append(
                f'<line x1="{mx:.1f}" y1="{plot_top}" x2="{mx:.1f}" y2="{plot_bottom}" '
                f'stroke="{line_stroke}" stroke-width="0.8" stroke-dasharray="4 3" opacity="{line_opacity}"/>'
            )
            # Small tick from label down to plot top.
            parts.append(
                f'<line x1="{mx:.1f}" y1="{label_y + LABEL_LINE_H:.1f}" '
                f'x2="{mx:.1f}" y2="{plot_top}" '
                f'stroke="{line_stroke}" stroke-width="0.6" opacity="0.4"/>'
            )
            # Label text — clip to plot area so it doesn't overflow left.
            short = mlabel.split("|")[-1].strip() if "|" in mlabel else mlabel
            short = short[:30]
            label_text = f"{short} ({mday:%d/%m})"
            parts.append(
                f'<text x="{mx + 2:.1f}" y="{label_y + LABEL_FONT:.1f}" '
                f'font-family="{SVG_FONT}" font-size="{LABEL_FONT}" '
                f'fill="{label_fill}" font-weight="{label_weight}">'
                f'{html.escape(label_text)}</text>'
            )

    today = _chart_today_in_quarter(x_min, x_max)
    if today is not None:
        _append_today_marker(
            parts,
            today=today,
            x_for=x_for,
            plot_top=plot_top,
            plot_bottom=plot_bottom,
        )

    parts.append("</svg>")
    return "".join(parts)


def build_sef_project_plan_report_html(
    payload: dict[str, Any],
    *,
    generated_on: str,
    page_title: str | None = None,
    breadcrumb_nav: str = "",
) -> str:
    title = page_title or str(payload.get("pageTitle") or "SEF | Integrated Project Plan")

    def _footnote_for(active_payload: dict[str, Any]) -> str:
        chapter_count = sum(len(phase.get("chapters") or []) for phase in active_payload.get("phases") or [])
        package_count = sum(
            len(chapter.get("packages") or [])
            for phase in active_payload.get("phases") or []
            for chapter in phase.get("chapters") or []
        )
        detail_count = sum(
            len(package.get("details") or [])
            for phase in active_payload.get("phases") or []
            for chapter in phase.get("chapters") or []
            for package in chapter.get("packages") or []
        )
        milestone_keys: set[str] = set()
        for row in _iter_timeline_rows(active_payload.get("phases") or []):
            if _is_milestone_row(row) and row.get("key"):
                milestone_keys.add(str(row.get("key")))
        for row in active_payload.get("milestones") or []:
            if row.get("key"):
                milestone_keys.add(str(row.get("key")))
        milestone_count = len(milestone_keys)
        footnote_parts = [
            f"{chapter_count} schedule chapters",
            f"{package_count} stream packages",
        ]
        if detail_count:
            footnote_parts.append(f"{detail_count} detail items")
        if milestone_count:
            footnote_parts.append(f"{milestone_count} milestones")
        window_start, window_end = _payload_chart_window(active_payload)
        return (
            f"{', '.join(footnote_parts)} from PDE Block work items "
            f"({window_start.isoformat()} to {window_end.isoformat()}). "
            "Each bar runs from start date through due date. "
            "Milestones are shown as meeting-gate icons or red triangles. "
            "Bar colours follow Jira Plans Workstream mapping."
        )

    def _workstream_option_label(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        label = text.replace("-", " ").replace("_", " ").strip()
        if label.lower() == "hcm":
            return "HCM"
        return " ".join(part.capitalize() for part in label.split())

    colors = load_sef_project_plan_component_colors()
    legend = sef_project_plan_workstream_legend_html(colors)
    dimensions_raw = payload.get("filterDimensions") or []
    dimensions: list[dict[str, Any]] = []
    for dim in dimensions_raw:
        if not isinstance(dim, dict):
            continue
        dim_copy = dict(dim)
        if str(dim_copy.get("id") or "") == "component":
            dim_copy["id"] = "workstream"
        if str(dim_copy.get("label") or "") == "Component":
            dim_copy["label"] = "Workstream"
        if str(dim_copy.get("sourceField") or "") == "components":
            dim_copy["sourceField"] = "workstreams"
        dim_id = str(dim_copy.get("id") or "")
        options = [str(opt).strip() for opt in (dim_copy.get("options") or []) if str(opt).strip()]
        if dim_id == "workstream":
            options = [opt for opt in options if opt.lower() != "all"]
        dim_copy["options"] = sorted(dict.fromkeys(options))
        dimensions.append(dim_copy)

    if not dimensions:
        dimensions = _build_filter_dimensions(
            payload.get("phases") or [],
            (SefFilterDimensionConfig(id="workstream", label="Workstream", source_field="workstreams"),),
        )
    payload = json.loads(json.dumps(payload))
    payload["filterDimensions"] = dimensions
    chart = sef_project_plan_timeline_svg(payload, workstream_colors=colors)
    footnote = _footnote_for(payload)

    controls_html = ""
    if dimensions:
        controls: list[str] = ['<div class="sef-plan-filters" aria-label="Report filters">']
        for dimension in dimensions:
            dim_id_raw = str(dimension.get("id") or "")
            dim_id = html.escape(dim_id_raw)
            dim_label = html.escape(str(dimension.get("label") or dim_id_raw.title()))
            options = [str(opt) for opt in (dimension.get("options") or []) if str(opt)]
            option_html = [
                (
                    '<label class="sef-plan-option">'
                    f'<input type="checkbox" data-sef-filter-option value="{html.escape(opt)}"/>'
                    f'<span>{html.escape(_workstream_option_label(opt) if dim_id_raw == "workstream" else opt)}</span>'
                    '</label>'
                )
                for opt in options
            ]
            controls.append(
                "<div class=\"sef-plan-filter\">"
                f"<span>{dim_label}</span>"
                f"<details class=\"sef-plan-expander\" data-sef-filter=\"{dim_id}\">"
                "<summary data-sef-filter-summary>All</summary>"
                "<div class=\"sef-plan-options\">"
                f"{''.join(option_html)}"
                "</div>"
                "</details>"
                "</div>"
            )
        controls.append(
            '<div class="sef-plan-filter-actions">'
            '<button type="button" class="sef-plan-clear" data-sef-filter-clear>Clear all filters</button>'
            '</div>'
        )
        controls.append("</div>")
        controls_html = "".join(controls)

    variant_block = (
            '<section class="sef-plan-variant" data-variant-key="__all__">'
            f'<div class="chart-wrap chart-wrap-timeline chart-wrap-sef-plan">{chart}</div>'
            f'<p class="footnote">{html.escape(footnote)}</p>'
            "</section>"
    )

    variant_script = ""
    if dimensions:
            dimension_meta: list[dict[str, str]] = []
            for d in dimensions:
                    dim_id = str(d.get("id") or "").strip()
                    source_field = str(d.get("sourceField") or "").strip()
                    if dim_id and source_field:
                            dimension_meta.append({"id": dim_id, "sourceField": source_field})

            row_filter_values: dict[str, dict[str, list[str]]] = {}
            for row in _iter_timeline_rows(payload.get("phases") or []):
                    key = str(row.get("key") or "").strip()
                    if not key:
                            continue
                    row_entry: dict[str, list[str]] = {}
                    for meta in dimension_meta:
                            vals = _iter_dimension_values(row, source_field=meta["sourceField"])
                            if vals:
                                    row_entry[meta["id"]] = vals
                    row_filter_values[key] = row_entry

            meta_json = json.dumps(dimension_meta)
            values_json = json.dumps(row_filter_values)
            variant_script = f"""
<script>
(() => {{
const dimensionMeta = {meta_json};
const rowFilterValues = {values_json};
const filters = document.querySelectorAll('[data-sef-filter]');
const clearBtn = document.querySelector('[data-sef-filter-clear]');
const svg = document.querySelector('.sef-plan-variant .chart-wrap-sef-plan svg');

function selectedValues(filterEl) {{
    return Array.from(filterEl.querySelectorAll('input[data-sef-filter-option]:checked'))
        .map((opt) => String(opt.value || '').trim())
        .filter(Boolean);
}}

function updateSummary(filterEl) {{
    const summary = filterEl.querySelector('[data-sef-filter-summary]');
    if (!summary) return;
    const selected = selectedValues(filterEl);
    if (!selected.length) {{
        summary.textContent = 'All';
        return;
    }}
    if (selected.length === 1) {{
        const only = filterEl.querySelector('input[data-sef-filter-option]:checked + span');
        summary.textContent = only ? only.textContent : '1 selected';
        return;
    }}
    summary.textContent = `${{selected.length}} selected`;
}}

function closeAllExpanders(exceptEl) {{
    filters.forEach((f) => {{
        if (exceptEl && f === exceptEl) return;
        if (f.open) f.open = false;
    }});
}}

function parentMapFromSvg() {{
    if (!svg) return {{}};
    const pm = svg.querySelector('#sef-pm');
    if (!pm) return {{}};
    try {{
        return JSON.parse((pm.getAttribute('data-parent-map') || '{{}}').replace(/&quot;/g, '"'));
    }} catch (_err) {{
        return {{}};
    }}
}}

function buildChildrenMap(parentMap) {{
    const children = {{}};
    Object.keys(parentMap).forEach((key) => {{
        const parent = String(parentMap[key] || '').trim();
        if (!parent) return;
        if (!children[parent]) children[parent] = [];
        children[parent].push(key);
    }});
    return children;
}}

function addAncestors(set, key, parentMap) {{
    let cur = String(key || '').trim();
    let guard = 0;
    while (cur && guard < 128) {{
        const parent = String(parentMap[cur] || '').trim();
        if (!parent) break;
        set.add(parent);
        cur = parent;
        guard += 1;
    }}
}}

function addDescendants(set, key, childrenMap) {{
    const stack = [String(key || '').trim()].filter(Boolean);
    let guard = 0;
    while (stack.length && guard < 5000) {{
        const cur = stack.pop();
        const kids = childrenMap[cur] || [];
        for (const child of kids) {{
            if (!set.has(child)) {{
                set.add(child);
                stack.push(child);
            }}
        }}
        guard += 1;
    }}
}}

function rowMatchesSelections(rowValues, selectedByDim) {{
    for (const dim of dimensionMeta) {{
        const selected = selectedByDim[dim.id] || [];
        if (!selected.length) continue;
        const rowVals = rowValues[dim.id] || [];
        if (!rowVals.length) return false;
        const hit = selected.some((v) => rowVals.includes(v));
        if (!hit) return false;
    }}
    return true;
}}

function effectiveRowValues(key, dimId, parentMap, cache) {{
    const cacheKey = `${{key}}::${{dimId}}`;
    if (cache[cacheKey]) return cache[cacheKey];

    const values = [];
    const seen = new Set();
    let cur = String(key || '').trim();
    let guard = 0;
    while (cur && guard < 128) {{
        const curValues = (rowFilterValues[cur] && rowFilterValues[cur][dimId]) || [];
        curValues.forEach((v) => {{
            if (!seen.has(v)) {{
                seen.add(v);
                values.push(v);
            }}
        }});
        cur = String(parentMap[cur] || '').trim();
        guard += 1;
    }}

    cache[cacheKey] = values;
    return values;
}}

function rowMatchesSelectionsForKey(key, selectedByDim, parentMap, cache) {{
    for (const dim of dimensionMeta) {{
        const selected = selectedByDim[dim.id] || [];
        if (!selected.length) continue;
        const vals = effectiveRowValues(key, dim.id, parentMap, cache);
        if (!vals.length) return false;
        const hit = selected.some((v) => vals.includes(v));
        if (!hit) return false;
    }}
    return true;
}}

function apply() {{
    if (!svg) return;

    const selectedByDim = {{}};
    let activeCount = 0;
    dimensionMeta.forEach((dim) => {{
        const sel = document.querySelector(`[data-sef-filter="${{dim.id}}"]`);
        const vals = sel ? selectedValues(sel) : [];
        selectedByDim[dim.id] = vals;
        activeCount += vals.length;
    }});

    const allMode = activeCount === 0;
    const parentMap = parentMapFromSvg();
    const childrenMap = buildChildrenMap(parentMap);
    const visibleKeys = new Set();
    const inheritedValueCache = {{}};

    if (allMode) {{
        Object.keys(rowFilterValues).forEach((key) => visibleKeys.add(key));
    }} else {{
        const matched = new Set();
        Object.keys(rowFilterValues).forEach((key) => {{
            if (rowMatchesSelectionsForKey(key, selectedByDim, parentMap, inheritedValueCache)) matched.add(key);
        }});

        matched.forEach((key) => {{
            visibleKeys.add(key);
            addAncestors(visibleKeys, key, parentMap);
            addDescendants(visibleKeys, key, childrenMap);
        }});
    }}

    svg.querySelectorAll('[data-sef-key]').forEach((node) => {{
        const key = String(node.getAttribute('data-sef-key') || '').trim();
        if (!key) return;
        node.style.display = visibleKeys.has(key) ? '' : 'none';
    }});

    svg.querySelectorAll('[data-sef-dep-from][data-sef-dep-to]').forEach((node) => {{
        const from = String(node.getAttribute('data-sef-dep-from') || '').trim();
        const to = String(node.getAttribute('data-sef-dep-to') || '').trim();
        node.style.display = (visibleKeys.has(from) && visibleKeys.has(to)) ? '' : 'none';
    }});

    svg.removeAttribute('data-sef-focus-source');
    svg.querySelectorAll('.sef-block-link-icon.active').forEach((node) => node.classList.remove('active'));
    if (clearBtn) clearBtn.disabled = allMode;
    if (typeof window.sefApplyVisibilityCompaction === 'function') {{
        window.sefApplyVisibilityCompaction(svg);
    }}
}}

filters.forEach((sel) => {{
    updateSummary(sel);
    sel.addEventListener('toggle', () => {{
        if (sel.open) closeAllExpanders(sel);
    }});
    sel.addEventListener('change', (event) => {{
        updateSummary(sel);
        apply();
        const target = event.target;
        if (target instanceof Element && target.matches('input[data-sef-filter-option]')) {{
            closeAllExpanders(null);
        }}
    }});
}});

document.addEventListener('click', (event) => {{
    const target = event.target;
    if (!(target instanceof Element)) return;
    const withinFilter = target.closest('details.sef-plan-expander');
    if (!withinFilter) closeAllExpanders(null);
}});

document.addEventListener('keydown', (event) => {{
    if (event.key === 'Escape') closeAllExpanders(null);
}});

if (clearBtn) {{
    clearBtn.addEventListener('click', () => {{
        filters.forEach((sel) => {{
            Array.from(sel.querySelectorAll('input[data-sef-filter-option]')).forEach((opt) => {{
                opt.checked = false;
            }});
            updateSummary(sel);
        }});
        apply();
    }});
}}
apply();
}})();
</script>
"""

    nav_block = f"\n    {breadcrumb_nav}" if breadcrumb_nav else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html.escape(title)}</title>
  <style>{REPORT_CSS}{BREADCRUMB_CSS}{SEF_PROJECT_PLAN_EXTRA_CSS}</style>
</head>
<body>
  <main class="report-shell">{nav_block}
    <header class="report-header">
      <h1>{html.escape(title)}</h1>
      <p class="report-subtitle">Generated {html.escape(generated_on)}</p>
    </header>
    <section class="chart-section">
      {legend}
            {controls_html}
                        {variant_block}
    </section>
  </main>
    {variant_script}
<script>
(function () {{
  'use strict';
    var chartPans = document.querySelectorAll('.chart-wrap-sef-plan');
    chartPans.forEach(function (wrap) {{
        wrap.addEventListener('wheel', function (evt) {{
            var canScrollX = wrap.scrollWidth > wrap.clientWidth;
            if (!canScrollX) return;

            var canScrollY = wrap.scrollHeight > wrap.clientHeight;
            var atTop = wrap.scrollTop <= 0;
            var atBottom = (wrap.scrollTop + wrap.clientHeight) >= (wrap.scrollHeight - 1);

            var xDelta = evt.deltaX;
            var yDelta = evt.deltaY;
            var useHorizontal = evt.shiftKey || Math.abs(xDelta) > Math.abs(yDelta);

            // If the user hits the vertical edge of the timeline viewport,
            // continue panning horizontally with the wheel instead of no-op.
            if (!useHorizontal && canScrollY) {{
                if ((yDelta < 0 && atTop) || (yDelta > 0 && atBottom)) {{
                    useHorizontal = true;
                }}
            }}

            // If there is no vertical scrollbar, treat wheel motion as horizontal pan.
            if (!useHorizontal && !canScrollY && Math.abs(yDelta) > 0.01) {{
                useHorizontal = true;
            }}

            if (!useHorizontal) return;

            var delta = xDelta;
            if (Math.abs(delta) < 0.01) delta = yDelta;
            if (Math.abs(delta) < 0.01) return;

            wrap.scrollLeft += delta;
            evt.preventDefault();
        }}, {{ passive: false }});
    }});

    function ensureOriginalSvgState(svg) {{
        if (!svg.getAttribute('data-sef-orig-viewbox')) {{
            svg.setAttribute('data-sef-orig-viewbox', svg.getAttribute('viewBox') || '');
        }}
        if (!svg.getAttribute('data-sef-orig-height')) {{
            svg.setAttribute('data-sef-orig-height', svg.getAttribute('height') || '');
        }}
        var wrap = svg.closest('.chart-wrap-sef-plan');
        if (wrap) {{
            if (!wrap.getAttribute('data-sef-orig-min-height')) {{
                wrap.setAttribute('data-sef-orig-min-height', wrap.style.minHeight || '');
            }}
            if (!wrap.getAttribute('data-sef-orig-height')) {{
                wrap.setAttribute('data-sef-orig-height', wrap.style.height || '');
            }}
        }}
    }}

    function restoreOriginalSvgState(svg) {{
        var vb = svg.getAttribute('data-sef-orig-viewbox');
        var h = svg.getAttribute('data-sef-orig-height');
        if (vb) svg.setAttribute('viewBox', vb);
        if (h) svg.setAttribute('height', h);

        var wrap = svg.closest('.chart-wrap-sef-plan');
        if (wrap) {{
            wrap.style.minHeight = wrap.getAttribute('data-sef-orig-min-height') || '';
            wrap.style.height = wrap.getAttribute('data-sef-orig-height') || '';
        }}
    }}

    function _extractTranslate(transform) {{
        var t = String(transform || '').trim();
        if (!t) return {{ x: 0, y: 0 }};
        var m = t.match(/translate\\(([^)]+)\\)/i);
        if (!m) return {{ x: 0, y: 0 }};
        var vals = m[1].split(/[ ,]+/).filter(Boolean).map(parseFloat);
        if (!vals.length || vals.some(function (n) {{ return !isFinite(n); }})) return {{ x: 0, y: 0 }};
        return {{ x: vals[0] || 0, y: vals.length > 1 ? (vals[1] || 0) : 0 }};
    }}

    function _effectiveBox(node) {{
        var box;
        try {{
            var clip = String(node.getAttribute && node.getAttribute('clip-path') || '');
            if (clip.indexOf('sef-plan-label-col') !== -1) {{
                var txt = node.querySelector('text');
                box = txt ? txt.getBBox() : node.getBBox();
            }} else {{
                box = node.getBBox();
            }}
        }} catch (_err) {{ return null; }}
        if (!box || !isFinite(box.x) || !isFinite(box.y) || !isFinite(box.width) || !isFinite(box.height)) {{
            return null;
        }}
        var tx = 0;
        var ty = 0;
        var cur = node;
        while (cur && cur.getAttribute) {{
            var tr = _extractTranslate(cur.getAttribute('transform'));
            tx += tr.x;
            ty += tr.y;
            cur = cur.parentNode;
            if (cur && cur.tagName && String(cur.tagName).toLowerCase() === 'svg') break;
        }}
        return {{ x: box.x + tx, y: box.y + ty, width: box.width, height: box.height }};
    }}

    function _isReasonableRowBox(node, box) {{
        if (!box) return false;
        if (!isFinite(box.height) || box.height <= 0) return false;
        var isRow = (node.getAttribute && node.getAttribute('data-sef-row') === '1');
        if (!isRow) return true;
        var role = (node.getAttribute('data-sef-role') || '').trim();
        if (role === 'chapter-border' || role === 'package-lane') return false;
        // Row-level items should be short; very tall boxes are wrapper artefacts.
        return box.height <= 160;
    }}

    function _isShown(node, stopAt) {{
        var cur = node;
        while (cur && cur !== stopAt) {{
            if (cur.style && cur.style.display === 'none') return false;
            cur = cur.parentNode;
        }}
        return true;
    }}

    function _hasAncestorWithSameKey(node, key, stopAt) {{
        var cur = node ? node.parentNode : null;
        while (cur && cur !== stopAt) {{
            if (cur.getAttribute) {{
                var curKey = (cur.getAttribute('data-sef-key') || '').trim();
                var isRow = cur.getAttribute('data-sef-row') === '1';
                if (isRow && curKey === key) return true;
            }}
            cur = cur.parentNode;
        }}
        return false;
    }}

    function _isInLabelClipRegion(node, stopAt) {{
        var cur = node;
        while (cur && cur !== stopAt) {{
            if (cur.getAttribute) {{
                var clip = String(cur.getAttribute('clip-path') || '');
                if (clip.indexOf('sef-plan-label-col') !== -1) return true;
            }}
            cur = cur.parentNode;
        }}
        return false;
    }}

    function repositionFocusedXAxis(svg, newY, newH, xShift, clampToViewport) {{
        var axis = svg.querySelector('#sef-x-axis');
        if (!axis) return;
        var origBottom = parseFloat(axis.getAttribute('data-sef-orig-bottom') || 'NaN');
        if (!isFinite(origBottom)) return;
        var bottomPad = 74;
        var targetBottom = newY + newH - bottomPad;

        // In focused mode keep axis visible in viewport; in normal filtered mode
        // keep it at the true bottom of filtered content.
        if (clampToViewport) {{
            var wrap = svg.closest('.chart-wrap-sef-plan');
            if (wrap && isFinite(wrap.clientHeight) && wrap.clientHeight > 0) {{
                var visibleBottom = newY + wrap.clientHeight - 40;
                targetBottom = Math.min(targetBottom, visibleBottom);
            }}
        }}

        var dy = targetBottom - origBottom;
        var dx = isFinite(xShift) ? xShift : 0;
        axis.setAttribute('transform', 'translate(' + dx.toFixed(1) + ' ' + dy.toFixed(1) + ')');
    }}

    function resizeFocusedWrap(svg, newH) {{
        var wrap = svg.closest('.chart-wrap-sef-plan');
        if (!wrap) return;
        var focusedH = Math.max(320, Math.ceil(newH) + 14);
        wrap.style.minHeight = focusedH + 'px';
        wrap.style.height = focusedH + 'px';
    }}

    function _parseTranslateY(transform) {{
        var tr = _extractTranslate(transform);
        return isFinite(tr.y) ? tr.y : 0;
    }}

    function applyFocusTimelineShift(svg, dx) {{
        if (!isFinite(dx) || Math.abs(dx) < 0.5) return;

        svg.querySelectorAll('[data-sef-row="1"][data-sef-key]').forEach(function (node) {{
            if (!_isShown(node, svg)) return;
            var role = (node.getAttribute('data-sef-role') || '').trim();
            var clip = String(node.getAttribute('clip-path') || '');
            var id = String(node.getAttribute('id') || '');
            if (clip.indexOf('sef-plan-label-col') !== -1) return;
            if (_isInLabelClipRegion(node, svg)) return;
            if (id.indexOf('sef-chev-') === 0) return;
            var key = (node.getAttribute('data-sef-key') || '').trim();
            if (!key) return;
            if (_hasAncestorWithSameKey(node, key, svg)) return;
            var dy = _parseTranslateY(node.getAttribute('transform'));
            node.setAttribute('transform', 'translate(' + dx.toFixed(1) + ' ' + dy.toFixed(1) + ')');
        }});

        svg.querySelectorAll('[data-sef-dep-from][data-sef-dep-to]').forEach(function (node) {{
            if (!_isShown(node, svg)) return;
            var dy = _parseTranslateY(node.getAttribute('transform'));
            node.setAttribute('transform', 'translate(' + dx.toFixed(1) + ' ' + dy.toFixed(1) + ')');
        }});
    }}

    function restoreXAxisPosition(svg) {{
        var axis = svg.querySelector('#sef-x-axis');
        if (!axis) return;
        axis.removeAttribute('transform');
    }}

    function compactVisibleRows(svg, visibleSet, anchorSet) {{
        var rowNodes = Array.from(svg.querySelectorAll('[data-sef-row="1"][data-sef-key]')).filter(function (node) {{
            var role = (node.getAttribute('data-sef-role') || '').trim();
            return role !== 'chapter-border' && role !== 'package-lane';
        }});
        var byKey = new Map();

        rowNodes.forEach(function (node) {{
            if (!_isShown(node, svg)) return;
            var key = (node.getAttribute('data-sef-key') || '').trim();
            if (!key || !visibleSet.has(key)) return;
            var existing = byKey.get(key);
            if (!existing) {{
                existing = {{ minY: Infinity, maxY: -Infinity, nodes: [], hasBounds: false }};
                byKey.set(key, existing);
            }}
            existing.nodes.push(node);

            var box = _effectiveBox(node);
            if (!_isReasonableRowBox(node, box)) return;
            if (!box || !isFinite(box.y) || !isFinite(box.height)) return;
            existing.minY = Math.min(existing.minY, box.y);
            existing.maxY = Math.max(existing.maxY, box.y + box.height);
            existing.hasBounds = true;
        }});

        var rows = Array.from(byKey.entries()).filter(function (entry) {{ return entry[1].hasBounds; }});
        rows.sort(function (a, b) {{ return a[1].minY - b[1].minY; }});
        if (!rows.length) return;

        var rowGap = 6;
        var cursor = rows[0][1].minY;
        var shifts = new Map();
        rows.forEach(function (entry) {{
            var key = entry[0];
            var rec = entry[1];
            var targetTop = cursor;
            var dy = targetTop - rec.minY;
            shifts.set(key, dy);
            rec.nodes.forEach(function (node) {{
                if (_hasAncestorWithSameKey(node, key, svg)) return;
                node.setAttribute('transform', 'translate(0 ' + dy + ')');
            }});
            cursor = targetTop + (rec.maxY - rec.minY) + rowGap;
        }});

        svg.querySelectorAll('[data-sef-dep-from][data-sef-dep-to]').forEach(function (node) {{
            if (!_isShown(node, svg)) return;
            var from = (node.getAttribute('data-sef-dep-from') || '').trim();
            var to = (node.getAttribute('data-sef-dep-to') || '').trim();
            var fromShift = shifts.get(from) || 0;
            var toShift = shifts.get(to) || 0;
            var depShift = (fromShift + toShift) / 2;
            node.setAttribute('transform', 'translate(0 ' + depShift + ')');
        }});

        var allVisible = Array.from(svg.querySelectorAll('[data-sef-key]')).filter(function (node) {{
            if (!_isShown(node, svg)) return false;
            var role = (node.getAttribute('data-sef-role') || '').trim();
            if (role === 'chapter-border' || role === 'package-lane') return false;
            return true;
        }});
        if (!allVisible.length) return;
        var minY = Infinity;
        var maxY = -Infinity;
        allVisible.forEach(function (node) {{
            var box = _effectiveBox(node);
            if (!_isReasonableRowBox(node, box)) return;
            if (!box || !isFinite(box.y) || !isFinite(box.height)) return;
            minY = Math.min(minY, box.y);
            maxY = Math.max(maxY, box.y + box.height);
        }});
        if (!isFinite(minY) || !isFinite(maxY)) return;

        var originalViewBox = (svg.getAttribute('data-sef-orig-viewbox') || svg.getAttribute('viewBox') || '').split(/\\s+/).map(Number);
        if (originalViewBox.length !== 4 || originalViewBox.some(function (n) {{ return !isFinite(n); }})) return;
        var padTop = 62;
        var padBottom = 90;
        var newY = Math.max(0, minY - padTop);
        var newH = Math.max(260, (maxY - minY) + padTop + padBottom);

        // Collapse the horizontal axis to visible timeline data while preserving the label column.
        var axisLeft = 0;
        var labelClip = svg.querySelector('#sef-plan-label-col rect');
        if (labelClip) {{
            axisLeft = (parseFloat(labelClip.getAttribute('x')) || 0) + (parseFloat(labelClip.getAttribute('width')) || 0) + 8;
        }}

        var minDataX = Infinity;
        var maxDataX = -Infinity;
        var timelineNodes = Array.from(svg.querySelectorAll('[data-sef-row="1"][data-sef-key],[data-sef-dep-from][data-sef-dep-to]'));
        timelineNodes.forEach(function (node) {{
            if (!_isShown(node, svg)) return;
            var nodeId = String(node.getAttribute('id') || '');
            if (nodeId.indexOf('sef-chev-') === 0) return;
            var rowKey = (node.getAttribute('data-sef-key') || '').trim();
            if (rowKey && !visibleSet.has(rowKey)) return;
            if (rowKey && anchorSet && anchorSet.size && !anchorSet.has(rowKey)) return;
            if (_isInLabelClipRegion(node, svg)) return;
            var role = (node.getAttribute('data-sef-role') || '').trim();
            if (role === 'chapter-border' || role === 'package-lane' || role === 'phase-bar') return;
            if ((node.getAttribute('clip-path') || '').indexOf('sef-plan-label-col') !== -1) return;

            var box = _effectiveBox(node);
            if (!_isReasonableRowBox(node, box)) return;
            if (!box || !isFinite(box.x) || !isFinite(box.width)) return;

            var left = Math.max(axisLeft, box.x);
            var right = box.x + box.width;
            if (right <= axisLeft + 1) return;
            minDataX = Math.min(minDataX, left);
            maxDataX = Math.max(maxDataX, right);
        }});

        var xPadLeft = 24;
        var xPadRight = 80;
        var newX = originalViewBox[0];
        var newW = originalViewBox[2];
        var xShift = 0;
        if (isFinite(minDataX) && isFinite(maxDataX) && maxDataX > minDataX) {{
            var desiredDataLeft = axisLeft + 18;
            if (minDataX > desiredDataLeft) {{
                xShift = desiredDataLeft - minDataX;
            }}
            applyFocusTimelineShift(svg, xShift);

            // Keep the left origin so the label column remains visible.
            newX = originalViewBox[0];
            var shiftedMaxDataX = maxDataX + xShift;
            var shiftedMinDataX = minDataX + xShift;
            var desiredRight = Math.min(originalViewBox[0] + originalViewBox[2], shiftedMaxDataX + xPadRight);
            var minRight = Math.max(axisLeft + 140, shiftedMinDataX - xPadLeft);
            desiredRight = Math.max(minRight, desiredRight);
            newW = Math.max(420, desiredRight - newX);
        }}

        repositionFocusedXAxis(svg, newY, newH, xShift, !!(anchorSet && anchorSet.size));
        svg.setAttribute('viewBox', newX + ' ' + newY + ' ' + newW + ' ' + newH);
        svg.setAttribute('height', Math.ceil(newH));
        resizeFocusedWrap(svg, newH);
    }}

    function restoreLaneGeometry(svg) {{
        svg.querySelectorAll('[data-sef-orig-y]').forEach(function (node) {{
            node.setAttribute('y', node.getAttribute('data-sef-orig-y'));
        }});
        svg.querySelectorAll('[data-sef-orig-height]').forEach(function (node) {{
            node.setAttribute('height', node.getAttribute('data-sef-orig-height'));
        }});
    }}

    function isDescendantOrSelf(candidate, ancestor, parentMap) {{
        var cur = (candidate || '').trim();
        var guard = 0;
        while (cur && guard < 64) {{
            if (cur === ancestor) return true;
            cur = (parentMap[cur] || '').trim();
            guard += 1;
        }}
        return false;
    }}

    function collectVisibleBoundsForAncestor(svg, ancestorKey, visibleSet, parentMap) {{
        var minY = Infinity;
        var maxY = -Infinity;
        visibleSet.forEach(function (key) {{
            if (!isDescendantOrSelf(key, ancestorKey, parentMap)) return;
            svg.querySelectorAll('[data-sef-row="1"][data-sef-key="' + key + '"]').forEach(function (node) {{
                if (!_isShown(node, svg)) return;
                var role = (node.getAttribute('data-sef-role') || '').trim();
                if (role === 'chapter-border' || role === 'package-lane') return;
                var box = _effectiveBox(node);
                if (!_isReasonableRowBox(node, box)) return;
                if (!box || !isFinite(box.y) || !isFinite(box.height)) return;
                minY = Math.min(minY, box.y);
                maxY = Math.max(maxY, box.y + box.height);
            }});
        }});
        if (!isFinite(minY) || !isFinite(maxY)) return null;
        return {{ minY: minY, maxY: maxY }};
    }}

    function compactParentLaneHeights(svg, visibleSet, parentMap) {{
        svg.querySelectorAll('rect[data-sef-role="package-lane"][data-sef-key]').forEach(function (lane) {{
            if (!_isShown(lane, svg)) return;
            var key = (lane.getAttribute('data-sef-key') || '').trim();
            if (!key || !visibleSet.has(key)) return;
            var bounds = collectVisibleBoundsForAncestor(svg, key, visibleSet, parentMap);
            if (!bounds) return;
            var padTop = 2;
            var padBottom = 2;
            lane.setAttribute('y', Math.max(0, bounds.minY - padTop).toFixed(1));
            lane.setAttribute('height', Math.max(12, (bounds.maxY - bounds.minY) + padTop + padBottom).toFixed(1));
        }});

        svg.querySelectorAll('rect[data-sef-role="chapter-border"][data-sef-key]').forEach(function (border) {{
            if (!_isShown(border, svg)) return;
            var key = (border.getAttribute('data-sef-key') || '').trim();
            if (!key || !visibleSet.has(key)) return;
            var bounds = collectVisibleBoundsForAncestor(svg, key, visibleSet, parentMap);
            if (!bounds) return;
            var padTop = 6;
            var padBottom = 6;
            border.setAttribute('y', Math.max(0, bounds.minY - padTop).toFixed(1));
            border.setAttribute('height', Math.max(24, (bounds.maxY - bounds.minY) + padTop + padBottom).toFixed(1));
        }});
    }}

    function updateExpandersForVisibility(svg, focusedMode) {{
        svg.querySelectorAll('text[id^="sef-chev-"][data-sef-key]').forEach(function (chev) {{
            var key = (chev.getAttribute('data-sef-key') || '').trim();
            if (!key) return;
            if (!focusedMode) {{
                chev.style.display = '';
                return;
            }}
            var sub = document.getElementById('sef-sub-' + key);
            if (!sub) {{
                chev.style.display = 'none';
                return;
            }}
            var hasVisibleChildren = Array.from(sub.querySelectorAll('[data-sef-row="1"][data-sef-key]')).some(function (node) {{
                return _isShown(node, svg);
            }});
            chev.style.display = hasVisibleChildren ? '' : 'none';
        }});
    }}

    function clearFocus(targetSvg) {{
        targetSvg.querySelectorAll('[data-sef-key]').forEach(function (node) {{
            node.style.display = '';
        }});
        targetSvg.querySelectorAll('[data-sef-dep-from][data-sef-dep-to]').forEach(function (node) {{
            node.style.display = '';
        }});
        restoreLaneGeometry(targetSvg);
        restoreXAxisPosition(targetSvg);
        targetSvg.querySelectorAll('[data-sef-row="1"][data-sef-key],[data-sef-dep-from][data-sef-dep-to]').forEach(function (node) {{
            node.removeAttribute('transform');
        }});
        targetSvg.querySelectorAll('.sef-block-link-icon.active').forEach(function (node) {{
            node.classList.remove('active');
        }});
        updateExpandersForVisibility(targetSvg, false);
        targetSvg.removeAttribute('data-sef-focus-source');
        restoreOriginalSvgState(targetSvg);
    }}

    window.sefApplyVisibilityCompaction = function (targetSvg) {{
        if (!targetSvg) return;
        ensureOriginalSvgState(targetSvg);

        // Always start compaction from original geometry so axis/viewBox are
        // recalculated from current filter state, not from prior compacted state.
        restoreOriginalSvgState(targetSvg);

        restoreLaneGeometry(targetSvg);
        restoreXAxisPosition(targetSvg);
        targetSvg.querySelectorAll('[data-sef-row="1"][data-sef-key],[data-sef-dep-from][data-sef-dep-to]').forEach(function (node) {{
            node.removeAttribute('transform');
        }});

        var visibleSet = new Set();
        var hiddenFound = false;
        targetSvg.querySelectorAll('[data-sef-row="1"][data-sef-key]').forEach(function (node) {{
            var key = (node.getAttribute('data-sef-key') || '').trim();
            if (!key) return;
            if (_isShown(node, targetSvg)) {{
                visibleSet.add(key);
            }} else {{
                hiddenFound = true;
            }}
        }});

        if (!hiddenFound || !visibleSet.size) {{
            updateExpandersForVisibility(targetSvg, false);
            restoreOriginalSvgState(targetSvg);
            return;
        }}

        var parentMap = {{}};
        var pm = targetSvg.querySelector('#sef-pm');
        if (pm) {{
            try {{
                parentMap = JSON.parse((pm.getAttribute('data-parent-map') || '{{}}').replace(/&quot;/g, '"'));
            }} catch (_err) {{
                parentMap = {{}};
            }}
        }}

        compactVisibleRows(targetSvg, visibleSet, null);
        compactParentLaneHeights(targetSvg, visibleSet, parentMap);
        updateExpandersForVisibility(targetSvg, true);
    }};

    window.sefToggleBlockedFocus = function (evt, sourceKey, linkedCsv) {{
        if (evt && typeof evt.stopPropagation === 'function') evt.stopPropagation();
        if (evt && typeof evt.preventDefault === 'function') evt.preventDefault();
        var source = (sourceKey || '').trim();
        if (!source) return;

        var icon = evt && evt.currentTarget ? evt.currentTarget : null;
        var svg = icon ? icon.closest('svg') : null;
        if (!svg) return;
        ensureOriginalSvgState(svg);

        var focused = (svg.getAttribute('data-sef-focus-source') || '').trim();
        if (focused === source) {{
            clearFocus(svg);
            return;
        }}

        var linked = (linkedCsv || '').split(',').map(function (item) {{ return item.trim(); }}).filter(Boolean);
        var visible = new Set([source]);
        linked.forEach(function (key) {{ visible.add(key); }});
        var anchor = new Set(visible);

        var parentMap = {{}};
        var pmEl = document.getElementById('sef-pm');
        if (pmEl) {{
            try {{
                parentMap = JSON.parse((pmEl.getAttribute('data-parent-map') || '{{}}').replace(/&quot;/g, '"'));
            }} catch (_err) {{
                parentMap = {{}};
            }}
        }}
        var queue = Array.from(visible);
        while (queue.length) {{
            var child = queue.pop();
            var parent = (parentMap[child] || '').trim();
            if (parent && !visible.has(parent)) {{
                visible.add(parent);
                queue.push(parent);
            }}
        }}

        svg.querySelectorAll('[data-sef-key]').forEach(function (node) {{
            var key = (node.getAttribute('data-sef-key') || '').trim();
            node.style.display = visible.has(key) ? '' : 'none';
        }});

        svg.querySelectorAll('[data-sef-dep-from][data-sef-dep-to]').forEach(function (node) {{
            var from = (node.getAttribute('data-sef-dep-from') || '').trim();
            var to = (node.getAttribute('data-sef-dep-to') || '').trim();
            node.style.display = (visible.has(from) && visible.has(to)) ? '' : 'none';
        }});

        svg.querySelectorAll('[data-sef-row="1"][data-sef-key],[data-sef-dep-from][data-sef-dep-to]').forEach(function (node) {{
            node.removeAttribute('transform');
        }});
        restoreLaneGeometry(svg);
        compactVisibleRows(svg, visible, anchor);
        compactParentLaneHeights(svg, visible, parentMap);
        updateExpandersForVisibility(svg, true);

        svg.querySelectorAll('.sef-block-link-icon.active').forEach(function (node) {{
            node.classList.remove('active');
        }});
        if (icon && icon.classList) icon.classList.add('active');
        svg.setAttribute('data-sef-focus-source', source);
    }};

  window.sefToggleChapter = function (evt, key) {{
    evt.stopPropagation();
    var sub = document.getElementById('sef-sub-' + key);
    var border = document.getElementById('sef-bd-' + key);
    var chev = document.getElementById('sef-chev-' + key);
    var chGroup = document.getElementById('sef-ch-' + key);
    if (!sub || !chGroup) return;

    var isOpen = sub.getAttribute('visibility') !== 'hidden' && sub.style.display !== 'none';
    var subH = parseInt(chGroup.getAttribute('data-sub-h'), 10) || 0;

    if (isOpen) {{
      sub.setAttribute('visibility', 'hidden');
      if (chev) chev.textContent = '\u25B6';
      var collH = parseInt(chGroup.getAttribute('data-collapsed-h'), 10) || 0;
      if (border) border.setAttribute('height', collH);
    }} else {{
      sub.setAttribute('visibility', 'visible');
      if (chev) chev.textContent = '\u25BC';
      if (border) {{
        var ch = parseInt(chGroup.getAttribute('data-collapsed-h'), 10) || 0;
        border.setAttribute('height', ch + subH);
      }}
    }}

    var cmEl = document.getElementById('sef-cm');
    if (!cmEl) return;
    var chapters;
    try {{ chapters = JSON.parse(cmEl.getAttribute('data-chapters').replace(/&quot;/g, '"')); }}
    catch (e) {{ return; }}

    var cumulativeShift = 0;
    chapters.forEach(function (ch) {{
      var g = document.getElementById('sef-ch-' + ch.key);
      if (!g) return;
      if (cumulativeShift !== 0) {{
        g.setAttribute('transform', 'translate(0,' + cumulativeShift + ')');
      }} else {{
        g.setAttribute('transform', 'translate(0,0)');
      }}
      var s = document.getElementById('sef-sub-' + ch.key);
      var collapsed = s && (s.getAttribute('visibility') === 'hidden' || s.style.display === 'none');
      if (collapsed) cumulativeShift -= ch.subH;
    }});

    var svg = chGroup.closest('svg');
    if (svg) {{
      var vb = svg.getAttribute('viewBox').split(' ').map(Number);
      var delta = isOpen ? -subH : subH;
      vb[3] = Math.max(100, vb[3] + delta);
      svg.setAttribute('viewBox', vb.join(' '));
      svg.setAttribute('height', Math.max(100, parseFloat(svg.getAttribute('height')) + delta));
    }}
  }};
}})();
</script>
</body>
</html>
"""
