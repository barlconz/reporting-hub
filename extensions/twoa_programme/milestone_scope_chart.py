"""Milestone scope composition chart — D-Train phase and lane breakdown by milestone."""

from __future__ import annotations

import html
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from artifact.atlassian import AtlassianAdapter
from artifact.jira_binding import DTRAIN_PHASES, JiraBinding

from extensions.twoa_programme.delivery_milestones import (
    MILESTONE_LINK_TYPE,
    find_milestone_hub_key,
    milestone_hub_children_jql,
    milestone_linked_issues,
    milestone_tooltip_plain,
)
from extensions.twoa_programme.epic_timeline import EPIC_CHILD_ISSUE_TYPES, LANE_DISPLAY_ORDER
from extensions.twoa_programme.jira_binding_loader import load_jira_binding
from extensions.twoa_programme.jira_search import search_all
from extensions.twoa_programme.quarter_scope import (
    classify_exclusive_lane,
    issue_excluded_from_analysis,
    milestone_linked_epic_scope_jql,
)
from extensions.twoa_programme.quarterly_dashboard_constants import (
    ATL,
    JIRA_SERVER,
    LANE_DEFAULT_LABELS,
    LANE_STACK_FILL,
    SVG_FONT,
)
from extensions.twoa_programme.quarterly_dashboard_links import _jira_search_url
from extensions.twoa_programme.quarterly_dashboard_markup import REPORT_CSS, _svg_embedded_title
from extensions.twoa_programme.quarterly_dashboard_svg_core import (
    _resolve_chart_calendar,
    _svg_chart_vertical_markers,
    _svg_sprint_calendar_underlay,
    _svg_x_axis_labels,
    _svg_x_bottom_margin,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ARTIFACT_NAME = "milestone-scope-chart.json"
_EXTRA_DEPLOY_STATUSES = frozenset({"PRD"})
_UNKNOWN_PHASE = "Unknown"
_UNPOINTED_SEGMENT = "Unpointed"

MILESTONE_KEY_WIDTH = 76
MILESTONE_TITLE_WIDTH = 228
LANE_LABEL_WIDTH = 148
LANE_BAR_HEIGHT = 22
MILESTONE_GAP = 12
MILESTONE_MIN_BLOCK_HEIGHT = 28
COMPOSITION_PLOT_WIDTH = 560
METRIC_LABEL_WIDTH = 118
CALENDAR_GAP = 16
CALENDAR_PX_PER_DAY = 11.0
CALENDAR_PLOT_TOP = 56
TITLE_LINE_HEIGHT = 13
TITLE_MAX_CHARS = 34
TITLE_MAX_LINES = 2


def _hex_lerp(start: str, end: str, t: float) -> str:
    sr, sg, sb = int(start[1:3], 16), int(start[3:5], 16), int(start[5:7], 16)
    er, eg, eb = int(end[1:3], 16), int(end[3:5], 16), int(end[5:7], 16)
    r = round(sr + (er - sr) * t)
    g = round(sg + (eg - sg) * t)
    b = round(sb + (eb - sb) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _build_dtrain_phase_fill() -> dict[str, str]:
    """Red (early D-Train) through green (late D-Train); unpointed neutral grey."""
    phases = [phase for phase in DTRAIN_PHASES if phase != "Decide"]
    count = len(phases)
    fills: dict[str, str] = {}
    for index, phase in enumerate(phases):
        t = index / (count - 1) if count > 1 else 0.0
        fills[phase] = _hex_lerp("#de350b", "#00875a", t)
    fills[_UNKNOWN_PHASE] = "#6b778c"
    fills[_UNPOINTED_SEGMENT] = "#c1c7d0"
    return fills


DTRAIN_PHASE_FILL: dict[str, str] = _build_dtrain_phase_fill()

MILESTONE_SCOPE_EXTRA_CSS = """
.chart-key--compact .chart-key-phase-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin: 8px 0 4px;
}
.chart-key--compact .chart-key-phase-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
}
.chart-key--compact .chart-key-note {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--muted);
}
"""


def chart_dtrain_phases() -> list[str]:
    """D-Train phases shown on composition bars (Decide omitted — not mapped from Jira)."""
    return [phase for phase in DTRAIN_PHASES if phase != "Decide"]


def chart_segment_order() -> list[str]:
    return [*chart_dtrain_phases(), _UNKNOWN_PHASE, _UNPOINTED_SEGMENT]


def timeline_bar_segment_order() -> list[str]:
    """Drive on the left, Dream on the right — inverted from lifecycle order on timeline bars."""
    return [*reversed(chart_dtrain_phases()), _UNKNOWN_PHASE, _UNPOINTED_SEGMENT]


def resolve_issue_dtrain_phase(status: str | None, binding: JiraBinding) -> str:
    name = (status or "").strip()
    if not name:
        return _UNKNOWN_PHASE
    if name in _EXTRA_DEPLOY_STATUSES:
        return "Deploy"
    phase = binding.dtrain_phase(name)
    if not phase or phase == "Decide":
        return _UNKNOWN_PHASE
    if phase not in chart_dtrain_phases():
        return _UNKNOWN_PHASE
    return phase


def _chart_phase_keys() -> list[str]:
    return [*chart_dtrain_phases(), _UNKNOWN_PHASE]


def _empty_scope_rollup_bucket() -> dict[str, Any]:
    phase_keys = _chart_phase_keys()
    return {
        "phases": {phase: 0.0 for phase in phase_keys},
        "phaseIssueKeys": {phase: [] for phase in phase_keys},
        "unpointedCount": 0,
        "unpointedIssueKeys": [],
        "storyPoints": 0.0,
        "totalWeight": 0.0,
    }


def _merge_sorted_issue_keys(*key_lists: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for keys in key_lists:
        for key in keys:
            cleaned = str(key or "").strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                merged.append(cleaned)
    return sorted(merged)


def _scope_segment_keys(rollup: dict[str, Any], segment_key: str) -> list[str]:
    """Raw scoped issue keys for one D-Train phase or unpointed segment."""
    if segment_key == _UNPOINTED_SEGMENT:
        return [str(key) for key in rollup.get("unpointedIssueKeys") or [] if key]
    return [
        str(key)
        for key in (rollup.get("phaseIssueKeys") or {}).get(segment_key) or []
        if key
    ]


def milestone_scope_segment_jql(rollup: dict[str, Any], segment_key: str) -> str | None:
    """JQL opening scoped issues for one D-Train phase or unpointed segment."""
    keys = _scope_segment_keys(rollup, segment_key)
    if not keys:
        return None
    return f"key in ({', '.join(sorted(set(keys)))}) AND status != Rejected"


def _empty_lane_buckets() -> dict[str, dict[str, Any]]:
    return {lane: _empty_scope_rollup_bucket() for lane in LANE_DISPLAY_ORDER}


def rollup_milestone_lane_phases(
    children: list[dict],
    *,
    delivery_squad_field: str,
    change_types_field: str,
    platform_field: str,
    story_points_field: str,
    binding: JiraBinding,
    skip_issue,
) -> dict[str, dict[str, Any]]:
    """Per-lane D-Train phase SP plus unpointed count (weight 1 each)."""
    lanes = _empty_lane_buckets()
    for issue in children:
        fields = issue.get("fields") or {}
        itype = str((fields.get("issuetype") or {}).get("name") or "")
        if itype not in EPIC_CHILD_ISSUE_TYPES:
            continue
        if skip_issue(issue):
            continue

        lane = classify_exclusive_lane(
            issue,
            delivery_squad_field=delivery_squad_field,
            change_types_field=change_types_field,
            platform_field=platform_field,
        )
        if lane not in lanes:
            lane = "unassigned"

        issue_key = str(issue.get("key") or "")
        sp_raw = fields.get(story_points_field)
        if sp_raw is None or float(sp_raw) <= 0:
            lanes[lane]["unpointedCount"] += 1
            if issue_key:
                lanes[lane]["unpointedIssueKeys"].append(issue_key)
            continue

        status = str((fields.get("status") or {}).get("name") or "")
        phase = resolve_issue_dtrain_phase(status, binding)
        lanes[lane]["phases"][phase] += float(sp_raw)
        if issue_key:
            lanes[lane]["phaseIssueKeys"][phase].append(issue_key)

    for lane_data in lanes.values():
        sp_total = sum(lane_data["phases"].values())
        unpointed = int(lane_data["unpointedCount"])
        lane_data["storyPoints"] = round(sp_total, 2)
        lane_data["totalWeight"] = round(sp_total + unpointed, 2)
    return lanes


def rollup_milestone_epic_phases(
    children: list[dict],
    *,
    epic_keys: list[str],
    delivery_squad_field: str,
    change_types_field: str,
    platform_field: str,
    story_points_field: str,
    binding: JiraBinding,
    skip_issue,
) -> dict[str, dict[str, Any]]:
    """Per-epic D-Train phase SP plus unpointed count (weight 1 each)."""
    buckets: dict[str, dict[str, Any]] = {
        epic_key: _empty_scope_rollup_bucket() for epic_key in epic_keys
    }
    for issue in children:
        fields = issue.get("fields") or {}
        itype = str((fields.get("issuetype") or {}).get("name") or "")
        if itype not in EPIC_CHILD_ISSUE_TYPES:
            continue
        if skip_issue(issue):
            continue

        parent = fields.get("parent") or {}
        epic_key = str(parent.get("key") or "")
        if epic_key not in buckets:
            continue

        issue_key = str(issue.get("key") or "")
        sp_raw = fields.get(story_points_field)
        if sp_raw is None or float(sp_raw) <= 0:
            buckets[epic_key]["unpointedCount"] += 1
            if issue_key:
                buckets[epic_key]["unpointedIssueKeys"].append(issue_key)
            continue

        status = str((fields.get("status") or {}).get("name") or "")
        phase = resolve_issue_dtrain_phase(status, binding)
        buckets[epic_key]["phases"][phase] += float(sp_raw)
        if issue_key:
            buckets[epic_key]["phaseIssueKeys"][phase].append(issue_key)

    for epic_data in buckets.values():
        sp_total = sum(epic_data["phases"].values())
        unpointed = int(epic_data["unpointedCount"])
        epic_data["storyPoints"] = round(sp_total, 2)
        epic_data["totalWeight"] = round(sp_total + unpointed, 2)
    return buckets


def aggregate_milestone_scope(lanes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Merge per-lane buckets into one milestone-wide scope composition."""
    phase_keys = _chart_phase_keys()
    phases = {phase: 0.0 for phase in phase_keys}
    phase_issue_keys: dict[str, list[str]] = {phase: [] for phase in phase_keys}
    unpointed = 0
    unpointed_issue_keys: list[str] = []
    for lane_data in lanes.values():
        for phase, value in (lane_data.get("phases") or {}).items():
            if phase in phases:
                phases[phase] += float(value)
        for phase, keys in (lane_data.get("phaseIssueKeys") or {}).items():
            if phase in phase_issue_keys:
                phase_issue_keys[phase].extend(str(key) for key in keys if key)
        unpointed += int(lane_data.get("unpointedCount") or 0)
        unpointed_issue_keys.extend(
            str(key) for key in lane_data.get("unpointedIssueKeys") or [] if key
        )
    sp_total = sum(phases.values())
    return {
        "phases": {phase: round(phases[phase], 2) for phase in phase_keys},
        "phaseIssueKeys": {
            phase: _merge_sorted_issue_keys(phase_issue_keys[phase]) for phase in phase_keys
        },
        "unpointedCount": unpointed,
        "unpointedIssueKeys": _merge_sorted_issue_keys(unpointed_issue_keys),
        "storyPoints": round(sp_total, 2),
        "totalWeight": round(sp_total + unpointed, 2),
    }


def fetch_milestone_scope_chart(
    adapter: AtlassianAdapter,
    *,
    initiative_key: str,
    quarter_filter: str,
    in_scope_filter: str | None = None,
    milestone_report_project: str = "PDE",
    delivery_squad_field: str,
    change_types_field: str,
    platform_field: str,
    story_points_field: str,
    skip_issue_types: frozenset[str],
    binding: JiraBinding | None = None,
) -> dict[str, Any]:
    jira_binding = binding or load_jira_binding()

    initiative = adapter.http.get_json(
        f"/rest/api/3/issue/{initiative_key}",
        params={"fields": "summary,issuelinks"},
    )
    hub_key = find_milestone_hub_key(initiative)
    if not hub_key:
        raise ValueError(
            f"No {MILESTONE_LINK_TYPE!r} link on initiative {initiative_key}; "
            "expected a Milestone Level One hub work item."
        )

    hub = adapter.http.get_json(
        f"/rest/api/3/issue/{hub_key}",
        params={"fields": "summary,issuetype"},
    )
    hub_fields = hub.get("fields") or {}

    def skip_issue(issue: dict) -> bool:
        itype = ((issue.get("fields") or {}).get("issuetype") or {}).get("name") or ""
        return itype in skip_issue_types or issue_excluded_from_analysis(issue)

    children = search_all(
        adapter,
        milestone_hub_children_jql(
            hub_key,
            project_key=milestone_report_project,
            in_scope_filter=in_scope_filter,
        ),
        ["summary", "description", "duedate", "status", "issuetype", "issuelinks"],
    )

    milestones: list[dict[str, Any]] = []
    for issue in children:
        key = issue["key"]
        fields = issue.get("fields") or {}
        linked = milestone_linked_issues(issue)
        epic_keys = [str(row["key"]) for row in linked if row.get("key")]
        scope_epics = [
            {
                "key": str(row["key"]),
                "summary": ((row.get("fields") or {}).get("summary") or ""),
                "issueType": ((row.get("fields") or {}).get("issuetype") or {}).get("name") or "",
            }
            for row in linked
        ]

        lane_buckets = _empty_lane_buckets()
        scope_issue_keys: list[str] = []
        if epic_keys:
            keys_csv = ", ".join(epic_keys)
            child_jql = milestone_linked_epic_scope_jql(parent_keys_csv=keys_csv)
            child_fields = [
                "parent",
                "issuetype",
                "status",
                story_points_field,
                change_types_field,
                delivery_squad_field,
                platform_field,
                "issuelinks",
            ]
            scope_children = search_all(adapter, child_jql, child_fields)
            lane_buckets = rollup_milestone_lane_phases(
                scope_children,
                delivery_squad_field=delivery_squad_field,
                change_types_field=change_types_field,
                platform_field=platform_field,
                story_points_field=story_points_field,
                binding=jira_binding,
                skip_issue=skip_issue,
            )
            scope_issue_keys = sorted(
                {
                    str(row.get("key"))
                    for row in scope_children
                    if row.get("key") and not skip_issue(row)
                }
            )

        due = fields.get("duedate")
        milestones.append(
            {
                "key": key,
                "label": str(fields.get("summary") or "").strip(),
                "summary": str(fields.get("summary") or "").strip(),
                "dueDate": str(due)[:10] if due else None,
                "status": (fields.get("status") or {}).get("name") or "",
                "issueType": (fields.get("issuetype") or {}).get("name") or "",
                "scopeEpics": scope_epics,
                "scopeIssueKeys": scope_issue_keys,
                "lanes": lane_buckets,
            }
        )

    milestones.sort(key=lambda row: (row.get("dueDate") or "9999-12-31", row.get("key") or ""))

    return {
        "initiativeKey": initiative_key,
        "hubKey": hub_key,
        "hubSummary": hub_fields.get("summary") or "",
        "hubIssueType": (hub_fields.get("issuetype") or {}).get("name") or "",
        "quarterFilter": quarter_filter,
        "inScopeFilter": in_scope_filter,
        "milestoneReportProject": milestone_report_project,
        "dtrainPhases": chart_dtrain_phases(),
        "segmentOrder": chart_segment_order(),
        "milestoneCount": len(milestones),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "milestones": milestones,
    }


def default_milestone_scope_chart_path(repo_root: Path | None = None) -> Path:
    from extensions.twoa_programme.quarterly_reporting import load_quarterly_reporting_config

    root = repo_root or _REPO_ROOT
    config_path = root / "config" / "quarterly-reporting.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    name = (payload.get("milestoneScopeChart") or {}).get("artifactFile") or _ARTIFACT_NAME
    config = load_quarterly_reporting_config(config_path)
    return config.output_root(root) / name


def load_milestone_scope_chart_payload(path: Path | None = None) -> dict[str, Any] | None:
    artifact = path or default_milestone_scope_chart_path()
    if not artifact.is_file():
        return None
    return json.loads(artifact.read_text(encoding="utf-8"))


def lane_bar_segments(
    lane_data: dict[str, Any],
    *,
    segment_order: list[str] | None = None,
) -> list[dict[str, Any]]:
    total = float(lane_data.get("totalWeight") or 0)
    if total <= 0:
        return []
    segments: list[dict[str, Any]] = []
    for key in segment_order or chart_segment_order():
        if key == _UNPOINTED_SEGMENT:
            weight = float(lane_data.get("unpointedCount") or 0)
        elif key == _UNKNOWN_PHASE:
            weight = float((lane_data.get("phases") or {}).get(_UNKNOWN_PHASE) or 0)
        else:
            weight = float((lane_data.get("phases") or {}).get(key) or 0)
        if weight <= 0:
            continue
        segments.append(
            {
                "key": key,
                "weight": weight,
                "fraction": weight / total,
            }
        )
    return segments


def scope_segment_tooltip(segment: dict[str, Any]) -> str:
    pct = segment["fraction"] * 100
    return f"{segment['key']}: {segment['weight']:g} ({pct:.0f}%)"


def append_scope_composition_overlay(
    parts: list[str],
    *,
    rollup: dict[str, Any],
    segments: list[dict[str, Any]],
    x0: float,
    y0: float,
    bar_w: float,
    bar_h: float,
    overlay_opacity: float = 0.92,
    link_class: str = "milestone-scope-segment",
    kpmg_reference_by_key: dict[str, str] | None = None,
    kpmg_search_url_builder: Callable[[str], str] | None = None,
) -> None:
    """D-Train phase segments on a scope bar; each segment links to scoped Jira issues.

    When ``kpmg_reference_by_key`` (scoped issue key -> KPMG source issue key) and
    ``kpmg_search_url_builder`` are both provided, each segment splits into a link to the
    referenced KPMG source issues and a link to the remaining un-referenced issues, instead
    of a single combined link.
    """
    cursor = x0
    for segment in segments:
        width = bar_w * segment["fraction"]
        if width <= 0:
            continue
        fill = DTRAIN_PHASE_FILL.get(segment["key"], ATL["neutral"])
        seg_tip = scope_segment_tooltip(segment)
        parts.append(f'<g>{_svg_embedded_title(seg_tip)}')

        sub_links: list[tuple[float, str]] = []
        if kpmg_reference_by_key and kpmg_search_url_builder:
            kpmg_keys: list[str] = []
            plain_keys: list[str] = []
            for key in _scope_segment_keys(rollup, segment["key"]):
                kpmg_key = kpmg_reference_by_key.get(key)
                if kpmg_key:
                    kpmg_keys.append(kpmg_key)
                else:
                    plain_keys.append(key)
            total = len(kpmg_keys) + len(plain_keys)
            if total:
                if kpmg_keys:
                    jql = f"key in ({', '.join(sorted(set(kpmg_keys)))})"
                    sub_links.append((len(kpmg_keys) / total, kpmg_search_url_builder(jql)))
                if plain_keys:
                    jql = f"key in ({', '.join(sorted(set(plain_keys)))}) AND status != Rejected"
                    sub_links.append((len(plain_keys) / total, _jira_search_url(jql)))

        if not sub_links:
            jql = milestone_scope_segment_jql(rollup, segment["key"])
            sub_links = [(1.0, _jira_search_url(jql))] if jql else []

        if not sub_links:
            parts.append(
                f'<rect x="{cursor:.1f}" y="{y0:.1f}" width="{width:.1f}" height="{bar_h:.1f}" '
                f'fill="{fill}" opacity="{overlay_opacity}" stroke="#ffffff" stroke-width="0.5"/>'
            )
        else:
            sub_cursor = cursor
            remaining = width
            for index, (fraction, href) in enumerate(sub_links):
                is_last = index == len(sub_links) - 1
                sub_width = remaining if is_last else min(width * fraction, remaining)
                rect = (
                    f'<rect x="{sub_cursor:.1f}" y="{y0:.1f}" width="{sub_width:.1f}" height="{bar_h:.1f}" '
                    f'fill="{fill}" opacity="{overlay_opacity}" stroke="#ffffff" stroke-width="0.5"/>'
                )
                parts.append(
                    f'<a href="{html.escape(href, quote=True)}" class="{html.escape(link_class)}" '
                    f'target="_blank" rel="noopener">'
                )
                parts.append(rect)
                parts.append("</a>")
                sub_cursor += sub_width
                remaining -= sub_width
        parts.append("</g>")
        cursor += width


def epic_scope_tooltip(*, epic: dict[str, Any], segment_order: list[str] | None = None) -> str:
    rollup = epic.get("rollup") or {}
    lines = [
        str(epic.get("summary") or ""),
        f"Total weight: {float(rollup.get('totalWeight') or 0):g} "
        f"({float(rollup.get('storyPoints') or 0):g} SP + "
        f"{int(rollup.get('unpointedCount') or 0)} unpointed)",
    ]
    for segment in lane_bar_segments(rollup, segment_order=segment_order):
        pct = segment["fraction"] * 100
        lines.append(f"  {segment['key']}: {segment['weight']:g} ({pct:.1f}%)")
    return "\n".join(lines)


def lane_bar_tooltip(
    *,
    milestone: dict[str, Any],
    lane_key: str,
    lane_data: dict[str, Any],
    lane_label: str,
) -> str:
    lines = [
        f"{milestone.get('label') or milestone.get('key')} | {lane_label}",
        f"Total weight: {float(lane_data.get('totalWeight') or 0):g} "
        f"({float(lane_data.get('storyPoints') or 0):g} SP + "
        f"{int(lane_data.get('unpointedCount') or 0)} unpointed)",
    ]
    for segment in lane_bar_segments(lane_data):
        pct = segment["fraction"] * 100
        lines.append(f"  {segment['key']}: {segment['weight']:g} ({pct:.1f}%)")
    return "\n".join(lines)


def _format_lane_total(lane_data: dict[str, Any]) -> str:
    total = float(lane_data.get("totalWeight") or 0)
    sp = float(lane_data.get("storyPoints") or 0)
    unpt = int(lane_data.get("unpointedCount") or 0)
    if unpt:
        return f"{total:g} ({sp:g} SP + {unpt} unpt)"
    return f"{total:g} SP"


def chart_max_lane_weight(payload: dict[str, Any]) -> float:
    best = 0.0
    for milestone in payload.get("milestones") or []:
        for lane_data in (milestone.get("lanes") or {}).values():
            best = max(best, float(lane_data.get("totalWeight") or 0))
    return best or 1.0


def load_milestone_scope_calendar(
    output_dir: Path,
    *,
    quarter_start: date,
    quarter_end: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], date, date]:
    """Sprint bands and engine releases from quarterly dashboard artifacts."""
    output_dir = Path(output_dir)
    status_path = output_dir / "quarter-status.json"
    if status_path.is_file():
        status = json.loads(status_path.read_text(encoding="utf-8"))
    else:
        status = {
            "quarterStart": quarter_start.isoformat(),
            "quarterEnd": quarter_end.isoformat(),
        }

    artifact_payload: dict[str, Any] = {}
    for key, name in (
        ("burnAllocation", "burn-allocation.json"),
        ("releasePlan", "release-plan-metadata.json"),
        ("releases", "engine-releases.json"),
    ):
        path = output_dir / name
        if path.is_file():
            artifact_payload[key] = json.loads(path.read_text(encoding="utf-8"))

    sprint_bands, releases = _resolve_chart_calendar(artifact_payload, status, {})
    x_min = date.fromisoformat(str(status.get("quarterStart", quarter_start.isoformat()))[:10])
    x_max = date.fromisoformat(str(status.get("quarterEnd", quarter_end.isoformat()))[:10])
    return sprint_bands, releases, x_min, x_max


def _calendar_plot_width(x_min: date, x_max: date) -> int:
    span_days = (x_max - x_min).days or 1
    return max(int(span_days * CALENDAR_PX_PER_DAY), 320)


def _calendar_left() -> float:
    return float(
        MILESTONE_KEY_WIDTH
        + MILESTONE_TITLE_WIDTH
        + LANE_LABEL_WIDTH
        + COMPOSITION_PLOT_WIDTH
        + METRIC_LABEL_WIDTH
        + CALENDAR_GAP
    )


def _append_block_due_marker(
    parts: list[str],
    *,
    milestone: dict[str, Any],
    block_y: float,
    block_h: float,
    x_min: date,
    x_max: date,
    x_for,
) -> None:
    due_raw = milestone.get("dueDate")
    if not due_raw:
        return
    rd = date.fromisoformat(str(due_raw)[:10])
    if rd < x_min:
        return
    pinned = False
    plot_day = rd
    if rd > x_max:
        if (rd - x_max).days > 3:
            return
        plot_day = x_max
        pinned = True
    x = x_for(plot_day)
    tip = milestone_tooltip_plain(milestone, pinned=pinned)
    key = str(milestone.get("key") or "")
    y1 = block_y + 2.0
    y2 = block_y + block_h - 2.0
    stroke = ATL["red"]
    line_el = (
        f'<line x1="{x:.1f}" y1="{y1:.1f}" x2="{x:.1f}" y2="{y2:.1f}" '
        f'stroke="{stroke}" stroke-width="2.5" opacity="0.92"/>'
    )
    hit_el = (
        f'<rect x="{x - 8:.1f}" y="{y1:.1f}" width="16.0" height="{y2 - y1:.1f}" '
        f'fill="transparent" pointer-events="all"/>'
    )
    if key:
        browse_url = f"{JIRA_SERVER}/browse/{html.escape(key)}"
        parts.append(
            f'<g><a href="{browse_url}" target="_blank" rel="noopener">'
            f"{_svg_title(tip)}{hit_el}{line_el}</a></g>"
        )
    else:
        parts.append(f"<g>{_svg_title(tip)}{hit_el}{line_el}</g>")


def _wrap_text_lines(text: str, *, max_chars: int, max_lines: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    consumed = 0
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            consumed += 1
            continue
        if current:
            lines.append(current)
        current = word
        consumed += 1
        if len(lines) >= max_lines - 1:
            break
    if len(lines) < max_lines and current:
        lines.append(current)
    if consumed < len(words) and lines:
        trimmed = lines[-1]
        if len(trimmed) > max_chars - 1:
            trimmed = trimmed[: max_chars - 1]
        if not trimmed.endswith("…"):
            trimmed = f"{trimmed}…"
        lines[-1] = trimmed
    return lines or [text[:max_chars]]


def build_milestone_scope_blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for milestone in payload.get("milestones") or []:
        lanes = milestone.get("lanes") or {}
        active = [
            (lane_key, lanes[lane_key])
            for lane_key in LANE_DISPLAY_ORDER
            if float((lanes.get(lane_key) or {}).get("totalWeight") or 0) > 0
        ]
        blocks.append({"milestone": milestone, "lanes": active})
    return blocks


def build_milestone_scope_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Legacy flat row list — prefer build_milestone_scope_blocks for rendering."""
    rows: list[dict[str, Any]] = []
    for block in build_milestone_scope_blocks(payload):
        milestone = block["milestone"]
        rows.append({"kind": "milestone_header", "milestone": milestone})
        if block["lanes"]:
            for lane_key, lane_data in block["lanes"]:
                rows.append(
                    {
                        "kind": "lane_bar",
                        "milestone": milestone,
                        "lane_key": lane_key,
                        "lane_data": lane_data,
                    }
                )
        else:
            rows.append({"kind": "milestone_empty", "milestone": milestone})
        rows.append({"kind": "gap"})
    if rows and rows[-1]["kind"] == "gap":
        rows.pop()
    return rows


def milestone_block_height(block: dict[str, Any]) -> int:
    lane_count = len(block.get("lanes") or []) or 1
    return max(lane_count * LANE_BAR_HEIGHT, MILESTONE_MIN_BLOCK_HEIGHT)


def milestone_scope_plot_height(blocks: list[dict[str, Any]]) -> int:
    if not blocks:
        return 0
    total = sum(milestone_block_height(block) for block in blocks)
    return total + MILESTONE_GAP * max(0, len(blocks) - 1)


def _plot_left() -> float:
    return float(MILESTONE_KEY_WIDTH + MILESTONE_TITLE_WIDTH + LANE_LABEL_WIDTH)


def _append_lane_bar(
    parts: list[str],
    *,
    segments: list[dict[str, Any]],
    x0: float,
    y0: float,
    bar_w: float,
    bar_h: float,
    tooltip: str,
) -> None:
    if bar_w <= 0:
        return
    parts.append(f'<g>{_svg_title(tooltip)}')
    cursor = x0
    for index, segment in enumerate(segments):
        width = bar_w * segment["fraction"]
        if width <= 0:
            continue
        if index == len(segments) - 1:
            width = max(x0 + bar_w - cursor, width)
        fill = DTRAIN_PHASE_FILL.get(segment["key"], ATL["neutral"])
        label = segment["key"]
        seg_tip = f"{label}: {segment['weight']:g} ({segment['fraction'] * 100:.1f}%)"
        parts.append(f'<g>{_svg_title(seg_tip)}')
        parts.append(
            f'<rect x="{cursor:.1f}" y="{y0:.1f}" width="{width:.1f}" height="{bar_h:.1f}" '
            f'fill="{fill}" stroke="#ffffff" stroke-width="1"/>'
        )
        parts.append("</g>")
        cursor += width
    parts.append("</g>")


def _svg_title(text: str) -> str:
    safe = html.escape(text, quote=False).replace("\n", "&#10;")
    return f"<title>{safe}</title>"


def _append_milestone_label(
    parts: list[str],
    *,
    milestone: dict[str, Any],
    block_y: float,
    block_h: float,
    tooltip: str,
) -> None:
    ms_key = str(milestone.get("key") or "")
    ms_label = str(milestone.get("label") or ms_key)
    due = str(milestone.get("dueDate") or "")[:10]
    title_lines = _wrap_text_lines(
        ms_label,
        max_chars=TITLE_MAX_CHARS,
        max_lines=TITLE_MAX_LINES,
    )
    label_lines: list[tuple[str, str, str]] = [(ms_key, ATL["blue"], "700")]
    label_lines.extend((line, ATL["ink"], "600") for line in title_lines)
    if due:
        label_lines.append((due, ATL["text_subtle"], "500"))

    text_block_h = len(label_lines) * TITLE_LINE_HEIGHT
    start_y = block_y + (block_h - text_block_h) / 2 + TITLE_LINE_HEIGHT - 2
    browse_url = f"{JIRA_SERVER}/browse/{html.escape(ms_key)}"

    parts.append(f'<g>{_svg_title(tooltip)}')
    for index, (line, fill, weight) in enumerate(label_lines):
        y = start_y + index * TITLE_LINE_HEIGHT
        if index == 0:
            parts.append(
                f'<a href="{browse_url}" target="_blank" rel="noopener">'
                f'<text x="8" y="{y:.1f}" font-family="{SVG_FONT}" font-size="11" '
                f'fill="{fill}" font-weight="{weight}">{html.escape(line)}</text></a>'
            )
            continue
        parts.append(
            f'<text x="{MILESTONE_KEY_WIDTH + 8}" y="{y:.1f}" font-family="{SVG_FONT}" font-size="10" '
            f'fill="{fill}" font-weight="{weight}">{html.escape(line)}</text>'
        )
    parts.append("</g>")


def milestone_scope_key_html() -> str:
    from extensions.twoa_programme.quarterly_dashboard_svg_core import (
        _milestone_legend_key_row,
        _today_legend_key_row,
    )

    phase_items = [
        (
            f'<span class="chart-key-phase-item">'
            f'<span class="legend-swatch" style="background:{DTRAIN_PHASE_FILL[phase]}"></span>'
            f"{html.escape(phase)}</span>"
        )
        for phase in chart_dtrain_phases()
    ]
    phase_items.extend(
        [
            (
                f'<span class="chart-key-phase-item">'
                f'<span class="legend-swatch" style="background:{DTRAIN_PHASE_FILL[_UNKNOWN_PHASE]}"></span>'
                f"Unknown</span>"
            ),
            (
                f'<span class="chart-key-phase-item">'
                f'<span class="legend-swatch" style="background:{DTRAIN_PHASE_FILL[_UNPOINTED_SEGMENT]}"></span>'
                f"Unpointed (1 each)</span>"
            ),
        ]
    )
    strip = "".join(phase_items)
    calendar_rows = (
        '<div class="chart-key-row">'
        '<span class="legend-swatch sprint-a"></span>'
        '<span class="legend-swatch sprint-b"></span> Sprint labels (S#)'
        "</div>"
        '<div class="chart-key-row">'
        '<span class="legend-swatch release-in"></span> In-cycle engine release (hover line)'
        "</div>"
        '<div class="chart-key-row">'
        '<span class="legend-swatch release-out"></span> Out-of-cycle / other release (hover line)'
        "</div>"
        f'<div class="chart-key-row">{_milestone_legend_key_row()}</div>'
        f'<div class="chart-key-row">{_today_legend_key_row()}</div>'
    )
    return (
        '<div class="chart-key chart-key--compact">'
        '<p class="chart-key-title"><strong>Key — scope composition</strong></p>'
        f'<div class="chart-key-phase-strip">{strip}</div>'
        '<p class="chart-key-note">Bar length = lane scope relative to the largest lane in the chart; '
        "segments = D-Train phase (Story Points) plus unpointed count.</p>"
        '<p class="chart-key-title"><strong>Key — quarter calendar</strong></p>'
        f"{calendar_rows}"
        '<p class="chart-key-note">Calendar column uses the same sprint, release, and today underlay as the '
        "Epic Timeline. Red line = milestone due date within each milestone block.</p>"
        "</div>"
    )


def milestone_scope_svg(
    payload: dict[str, Any],
    *,
    lane_labels: dict[str, str] | None = None,
    sprint_bands: list[dict[str, Any]] | None = None,
    releases: list[dict[str, Any]] | None = None,
    quarter_start: date | str | None = None,
    quarter_end: date | str | None = None,
) -> str:
    labels = lane_labels or LANE_DEFAULT_LABELS
    blocks = build_milestone_scope_blocks(payload)
    if not blocks:
        return '<p class="footnote">No milestones. Run fetch_milestone_scope_chart.py --write.</p>'

    x_min = date.fromisoformat(str(quarter_start or "2026-04-01")[:10])
    x_max = date.fromisoformat(str(quarter_end or "2026-08-20")[:10])
    span_days = (x_max - x_min).days or 1
    calendar_w = _calendar_plot_width(x_min, x_max)
    calendar_left = _calendar_left()
    calendar_right = calendar_left + calendar_w

    def calendar_x_for(day: date) -> float:
        offset = max(0, min(span_days, (day - x_min).days))
        return calendar_left + offset / span_days * calendar_w

    max_weight = chart_max_lane_weight(payload)
    plot_h = milestone_scope_plot_height(blocks)
    plot_top = CALENDAR_PLOT_TOP
    plot_bottom = plot_top + plot_h
    composition_right = _plot_left() + COMPOSITION_PLOT_WIDTH + METRIC_LABEL_WIDTH
    svg_height = plot_bottom + _svg_x_bottom_margin()
    width = int(calendar_right + 16)
    plot_left = _plot_left()
    title_x = MILESTONE_KEY_WIDTH + MILESTONE_TITLE_WIDTH / 2
    lane_x = MILESTONE_KEY_WIDTH + MILESTONE_TITLE_WIDTH + 10
    lane_area_right = calendar_left - CALENDAR_GAP
    header_y = plot_top - 14

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{svg_height}" '
        f'role="img" aria-label="Milestone scope composition by lane and D-Train phase">',
        f'<rect x="0" y="0" width="{width}" height="{svg_height}" fill="#ffffff"/>',
        f'<text x="{title_x:.1f}" y="{header_y:.1f}" text-anchor="middle" '
        f'font-family="{SVG_FONT}" font-size="10" fill="{ATL["text_subtle"]}" font-weight="600">'
        f"Milestone</text>",
        f'<text x="{lane_x + LANE_LABEL_WIDTH / 2:.1f}" y="{header_y:.1f}" text-anchor="middle" '
        f'font-family="{SVG_FONT}" font-size="10" fill="{ATL["text_subtle"]}" font-weight="600">'
        f"Lane</text>",
        f'<text x="{plot_left + COMPOSITION_PLOT_WIDTH / 2:.1f}" y="{header_y:.1f}" '
        f'text-anchor="middle" font-family="{SVG_FONT}" font-size="10" fill="{ATL["text_subtle"]}" '
        f'font-weight="600">Scope composition</text>',
        f'<text x="{calendar_left + calendar_w / 2:.1f}" y="{header_y:.1f}" text-anchor="middle" '
        f'font-family="{SVG_FONT}" font-size="10" fill="{ATL["text_subtle"]}" font-weight="600">'
        f"Quarter calendar</text>",
        f'<rect x="{calendar_left:.1f}" y="{plot_top:.1f}" width="{calendar_w:.1f}" height="{plot_h:.1f}" '
        f'fill="#fafbfc"/>',
    ]

    _svg_sprint_calendar_underlay(
        parts,
        sprint_bands=sprint_bands,
        plot_top=plot_top,
        plot_bottom=plot_bottom,
        plot_h=plot_h,
        x_for=calendar_x_for,
        x_min=x_min,
        x_max=x_max,
        show_sprint_shading=False,
    )

    y_cursor = plot_top
    for block_index, block in enumerate(blocks):
        milestone = block["milestone"]
        block_h = milestone_block_height(block)
        block_y = y_cursor
        header_tip = milestone_tooltip_plain(milestone)

        parts.append(
            f'<line x1="0" y1="{block_y:.1f}" x2="{width}" y2="{block_y:.1f}" '
            f'stroke="{ATL["line"]}" stroke-width="1"/>'
        )
        parts.append(
            f'<rect x="0" y="{block_y:.1f}" width="{MILESTONE_KEY_WIDTH + MILESTONE_TITLE_WIDTH}" '
            f'height="{block_h:.1f}" fill="#fafbfc"/>'
        )
        _append_milestone_label(
            parts,
            milestone=milestone,
            block_y=block_y,
            block_h=block_h,
            tooltip=header_tip,
        )

        lanes = block.get("lanes") or []
        if not lanes:
            row_y = block_y + (block_h - LANE_BAR_HEIGHT) / 2
            parts.append(f'<g>{_svg_title(header_tip)}')
            parts.append(
                f'<rect x="{plot_left:.1f}" y="{row_y + 4:.1f}" width="{COMPOSITION_PLOT_WIDTH * 0.35:.1f}" '
                f'height="{LANE_BAR_HEIGHT - 8:.1f}" rx="2" fill="{ATL["grid"]}" '
                f'stroke="{ATL["line"]}" stroke-dasharray="4 3"/>'
            )
            parts.append(
                f'<text x="{plot_left + 8:.1f}" y="{row_y + LANE_BAR_HEIGHT / 2 + 4:.1f}" '
                f'font-family="{SVG_FONT}" font-size="10" fill="{ATL["text_subtle"]}">'
                f"No quarter scope linked</text>"
            )
            parts.append("</g>")
        else:
            for lane_index, (lane_key, lane_data) in enumerate(lanes):
                row_y = block_y + lane_index * LANE_BAR_HEIGHT
                lane_label = labels.get(lane_key, lane_key)
                lane_fill = LANE_STACK_FILL.get(lane_key, ATL["neutral"])
                bar_h = LANE_BAR_HEIGHT - 8
                bar_y = row_y + (LANE_BAR_HEIGHT - bar_h) / 2
                total_weight = float(lane_data.get("totalWeight") or 0)
                bar_w = COMPOSITION_PLOT_WIDTH * (total_weight / max_weight)
                segments = lane_bar_segments(lane_data)
                tip = lane_bar_tooltip(
                    milestone=milestone,
                    lane_key=lane_key,
                    lane_data=lane_data,
                    lane_label=lane_label,
                )
                parts.append(
                    f'<rect x="{MILESTONE_KEY_WIDTH + MILESTONE_TITLE_WIDTH}" y="{row_y:.1f}" '
                    f'width="{lane_area_right - (MILESTONE_KEY_WIDTH + MILESTONE_TITLE_WIDTH):.1f}" '
                    f'height="{LANE_BAR_HEIGHT:.1f}" fill="{lane_fill}" opacity="0.06"/>'
                )
                parts.append(
                    f'<text x="{lane_x:.1f}" y="{row_y + LANE_BAR_HEIGHT / 2 + 4:.1f}" '
                    f'font-family="{SVG_FONT}" font-size="10" fill="{ATL["text_subtle"]}" '
                    f'font-weight="600">{html.escape(lane_label)}</text>'
                )
                _append_lane_bar(
                    parts,
                    segments=segments,
                    x0=plot_left,
                    y0=bar_y,
                    bar_w=bar_w,
                    bar_h=bar_h,
                    tooltip=tip,
                )
                metric = _format_lane_total(lane_data)
                parts.append(
                    f'<text x="{plot_left + COMPOSITION_PLOT_WIDTH + 8:.1f}" '
                    f'y="{row_y + LANE_BAR_HEIGHT / 2 + 4:.1f}" font-family="{SVG_FONT}" font-size="10" '
                    f'fill="{ATL["ink"]}">{html.escape(metric)}</text>'
                )
                if lane_index > 0:
                    parts.append(
                        f'<line x1="{MILESTONE_KEY_WIDTH + MILESTONE_TITLE_WIDTH}" y1="{row_y:.1f}" '
                        f'x2="{lane_area_right:.1f}" y2="{row_y:.1f}" stroke="{ATL["grid"]}" '
                        f'stroke-width="1" opacity="0.8"/>'
                    )

        _append_block_due_marker(
            parts,
            milestone=milestone,
            block_y=block_y,
            block_h=block_h,
            x_min=x_min,
            x_max=x_max,
            x_for=calendar_x_for,
        )

        block_bottom = block_y + block_h
        parts.append(
            f'<line x1="0" y1="{block_bottom:.1f}" x2="{width}" y2="{block_bottom:.1f}" '
            f'stroke="{ATL["line"]}" stroke-width="1"/>'
        )
        y_cursor = block_bottom
        if block_index < len(blocks) - 1:
            y_cursor += MILESTONE_GAP

    parts.append(
        f'<line x1="{plot_left}" y1="{plot_top}" x2="{plot_left}" y2="{plot_bottom}" '
        f'stroke="{ATL["line"]}" stroke-width="1"/>'
    )
    parts.append(
        f'<line x1="{plot_left + COMPOSITION_PLOT_WIDTH}" y1="{plot_top}" '
        f'x2="{plot_left + COMPOSITION_PLOT_WIDTH}" y2="{plot_bottom}" '
        f'stroke="{ATL["grid"]}" stroke-width="1" stroke-dasharray="4 3"/>'
    )
    parts.append(
        f'<line x1="{composition_right}" y1="{plot_top}" x2="{composition_right}" y2="{plot_bottom}" '
        f'stroke="{ATL["line"]}" stroke-width="1"/>'
    )
    parts.append(
        f'<line x1="{calendar_left}" y1="{plot_top}" x2="{calendar_left}" y2="{plot_bottom}" '
        f'stroke="{ATL["line"]}" stroke-width="1"/>'
    )
    parts.append(
        f'<line x1="{plot_left}" y1="{plot_bottom}" x2="{composition_right}" y2="{plot_bottom}" '
        f'stroke="{ATL["line"]}" stroke-width="1"/>'
    )
    parts.append(
        f'<line x1="{calendar_left}" y1="{plot_bottom}" x2="{calendar_right}" y2="{plot_bottom}" '
        f'stroke="{ATL["line"]}" stroke-width="1"/>'
    )
    _svg_chart_vertical_markers(
        parts,
        releases=releases,
        milestones=None,
        plot_top=plot_top,
        plot_bottom=plot_bottom,
        x_for=calendar_x_for,
        x_min=x_min,
        x_max=x_max,
    )
    _svg_x_axis_labels(
        parts,
        x_min=x_min,
        x_max=x_max,
        plot_bottom=plot_bottom,
        plot_left=calendar_left,
        plot_right=calendar_right,
        x_for=calendar_x_for,
    )
    parts.append("</svg>")
    return "".join(parts)


def build_milestone_scope_html(
    payload: dict[str, Any],
    *,
    generated_on: str,
    page_title: str,
    sprint_bands: list[dict[str, Any]] | None = None,
    releases: list[dict[str, Any]] | None = None,
    quarter_start: date | str | None = None,
    quarter_end: date | str | None = None,
) -> str:
    chart = milestone_scope_svg(
        payload,
        sprint_bands=sprint_bands,
        releases=releases,
        quarter_start=quarter_start,
        quarter_end=quarter_end,
    )
    hub = html.escape(str(payload.get("hubKey") or ""))
    hub_summary = html.escape(str(payload.get("hubSummary") or ""))
    initiative = html.escape(str(payload.get("initiativeKey") or ""))
    count = int(payload.get("milestoneCount") or 0)
    footnote = (
        f"Initiative {initiative}. Milestone hub {hub} ({hub_summary}). "
        f"{count} milestones. Scope = Story/Bug in quarter filter rolled up from milestone-linked epics. "
        "Each lane bar is split by D-Train phase (Story Points) plus unpointed issues (weight 1 each)."
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html.escape(page_title)}</title>
  <style>{REPORT_CSS}{MILESTONE_SCOPE_EXTRA_CSS}</style>
</head>
<body>
  <main class="report">
    <header class="report-header">
      <h1>{html.escape(page_title)}</h1>
      <p class="report-meta">Generated {html.escape(generated_on)}</p>
      <p class="footnote">{footnote}</p>
    </header>
    <section class="chart-section">
      {milestone_scope_key_html()}
      <div class="chart-wrap">{chart}</div>
    </section>
  </main>
</body>
</html>
"""
