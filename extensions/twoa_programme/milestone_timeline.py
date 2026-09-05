"""Milestone delivery timeline — sprint/release calendar with start-to-due bars (Epic Timeline basis)."""

from __future__ import annotations

import html
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from artifact.atlassian import AtlassianAdapter

from extensions.twoa_programme.delivery_milestones import (
    MILESTONE_LINK_TYPE,
    find_milestone_hub_key,
    milestone_hub_children_jql,
    milestone_linked_issues,
    milestone_notes_heading,
    milestone_work_item_description,
    milestone_work_item_notes,
    notes_field_last_updated,
)
from extensions.twoa_programme.epic_timeline import (
    EPIC_CHART_PX_PER_DAY,
    EPIC_ROW_HEIGHT,
    epic_bar_fill,
)
from extensions.twoa_programme.jira_binding_loader import load_jira_binding
from extensions.twoa_programme.jira_search import search_all
from extensions.twoa_programme.milestone_scope_chart import (
    aggregate_milestone_scope,
    append_scope_composition_overlay,
    epic_scope_tooltip,
    lane_bar_segments,
    rollup_milestone_epic_phases,
    rollup_milestone_lane_phases,
    timeline_bar_segment_order,
    _wrap_text_lines,
)
from extensions.twoa_programme.milestone_scope_history import (
    build_milestone_scope_daily,
    build_milestone_scope_phase_daily,
    phase_stack_order,
)
from extensions.twoa_programme.quarter_scope import (
    issue_excluded_from_analysis,
    milestone_linked_epic_scope_jql,
)
from extensions.twoa_programme.quarterly_dashboard_constants import ATL, JIRA_SERVER, SVG_FONT
from extensions.twoa_programme.quarterly_dashboard_markup import REPORT_CSS, _svg_embedded_title
from extensions.twoa_programme.quarterly_dashboard_svg_core import (
    QUARTERLY_REPORT_MAX_SVG_WIDTH,
    QUARTERLY_REPORT_MIN_PLOT_WIDTH,
    _resolve_chart_calendar,
    report_plot_width,
    _svg_chart_vertical_markers,
    _svg_sprint_calendar_underlay,
    _svg_x_axis_labels,
    _svg_x_bottom_margin,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ARTIFACT_NAME = "milestone-timeline.json"

MILESTONE_CALENDAR_TOP = 56
MILESTONE_SPRINT_LABEL_BAND = 24
MILESTONE_BAR_OPACITY = 0.85
SCOPE_OVERLAY_OPACITY = 0.92
MILESTONE_ROW_HEIGHT = EPIC_ROW_HEIGHT * 2
MILESTONE_BAR_HEIGHT = MILESTONE_ROW_HEIGHT - 6.0
MILESTONE_LABEL_WIDTH = 240
MILESTONE_TIMELINE_RIGHT_PAD = 24
MILESTONE_TIMELINE_MAX_SVG_WIDTH = QUARTERLY_REPORT_MAX_SVG_WIDTH
MILESTONE_TIMELINE_MIN_PLOT_WIDTH = QUARTERLY_REPORT_MIN_PLOT_WIDTH
MILESTONE_BLOCK_GAP = 12
MILESTONE_BLOCK_PAD_Y = 8
LABEL_PAD_X = 8
SUB_ROW_HEIGHT = 16
SUB_BAR_BASE_OPACITY = 0.45
SUB_SCOPE_OVERLAY_OPACITY = 0.55
SUB_LABEL_INDENT = 20
LABEL_MAX_CHARS = 38
EPIC_LABEL_MAX_CHARS = 34

MILESTONE_TIMELINE_EXTRA_CSS = """
.chart-wrap-milestone.chart-wrap-timeline {
  max-height: none;
  overflow-x: hidden;
  overflow-y: visible;
}
.chart-wrap-milestone svg {
  display: block;
  width: 100%;
  height: auto;
  min-width: 0;
  max-width: 100%;
}
.chart-wrap-milestone svg a text {
  text-decoration: none;
}
.chart-wrap-milestone svg a:hover text {
  text-decoration: underline;
}
.chart-wrap-milestone svg a.milestone-scope-segment {
  cursor: pointer;
}
"""
MILESTONE_LABEL_FILL_EVEN = "#fafbfc"
MILESTONE_LABEL_FILL_ODD = "#eef1f4"
MILESTONE_BLOCK_BORDER_WIDTH = 0.75


MILESTONE_BLOCK_BORDER_WIDTH = 0.75
_SCOPE_CHANGELOG_CACHE = "milestone_scope_changelog_cache.json"


def _get_json_retry(
    adapter: AtlassianAdapter,
    path: str,
    *,
    params: dict | None = None,
    attempts: int = 5,
):
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return adapter.http.get_json(path, params=params)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def fetch_issue_changelog_histories(adapter: AtlassianAdapter, issue_key: str) -> list[dict[str, Any]]:
    histories: list[dict[str, Any]] = []
    start = 0
    while True:
        page = _get_json_retry(
            adapter,
            f"/rest/api/3/issue/{issue_key}/changelog",
            params={"startAt": start, "maxResults": 100},
        )
        histories.extend(page.get("values") or [])
        if page.get("isLast", True):
            break
        start += len(page.get("values") or [])
        if not page.get("values"):
            break
    return histories


def load_scope_changelog_cache(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_scope_changelog_cache(path: Path, cache: dict[str, list[dict[str, Any]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")


def fetch_scope_changelogs(
    adapter: AtlassianAdapter,
    issue_keys: list[str],
    *,
    cache_path: Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    cache = load_scope_changelog_cache(cache_path) if cache_path else {}
    result = dict(cache)
    missing = [key for key in issue_keys if key not in result]
    for index, key in enumerate(missing, start=1):
        print(f"scope changelog {index}/{len(missing)} {key}...", flush=True)
        result[key] = fetch_issue_changelog_histories(adapter, key)
        if cache_path:
            cache[key] = result[key]
            save_scope_changelog_cache(cache_path, cache)
    return {key: result[key] for key in issue_keys if key in result}


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def resolve_milestone_window(
    *,
    start_date: str | None,
    created: str | None,
    due_date: str | None,
    quarter_start: date,
    quarter_end: date,
) -> tuple[date, date]:
    """Bar from milestone start (or created) through due date.

    Quarter dates are fallbacks only when start/due are missing. Ends are not clipped to
    the delivery quarter — the milestone report is filter-driven and commonly includes
    due dates past quarter.endDate.
    """
    end = _parse_day(due_date) or quarter_end
    start = _parse_day(start_date) or _parse_day(created) or quarter_start
    if end < start:
        end = start
    return start, end


def milestone_report_plot_width(
    span_days: int,
    *,
    px_per_day: float,
    plot_left: float,
    plot_right_pad: float,
    max_svg_width: int = MILESTONE_TIMELINE_MAX_SVG_WIDTH,
    min_plot_width: int = MILESTONE_TIMELINE_MIN_PLOT_WIDTH,
) -> int:
    return report_plot_width(
        span_days,
        px_per_day=px_per_day,
        plot_left=plot_left,
        plot_right_pad=plot_right_pad,
        max_svg_width=max_svg_width,
        min_plot_width=min_plot_width,
    )


def milestone_timeline_plot_width(
    span_days: int,
    *,
    px_per_day: float = EPIC_CHART_PX_PER_DAY,
    max_svg_width: int = MILESTONE_TIMELINE_MAX_SVG_WIDTH,
) -> int:
    return report_plot_width(
        span_days,
        px_per_day=px_per_day,
        plot_left=MILESTONE_LABEL_WIDTH,
        plot_right_pad=MILESTONE_TIMELINE_RIGHT_PAD,
        max_svg_width=max_svg_width,
    )


def milestone_timeline_chart_bounds(
    milestones: list[dict[str, Any]],
    *,
    quarter_start: date,
    quarter_end: date,
) -> tuple[date, date]:
    """X-axis from earliest milestone start through latest milestone end/due."""
    starts = [_parse_day(str(milestone.get("startDate") or "")[:10]) for milestone in milestones]
    starts = [day for day in starts if day is not None]
    ends: list[date] = []
    for milestone in milestones:
        end = _parse_day(str(milestone.get("endDate") or "")[:10])
        due = _parse_day(str(milestone.get("dueDate") or "")[:10])
        if end is not None:
            ends.append(end)
        if due is not None:
            ends.append(due)
    x_min = min(starts) if starts else quarter_start
    x_max = max([quarter_end, *ends]) if ends else quarter_end
    if x_min > x_max:
        x_min = x_max
    return x_min, x_max


def milestone_report_window_from_rows(
    milestones: list[dict[str, Any]],
    *,
    fallback_start: date,
    fallback_end: date,
) -> tuple[date, date]:
    """Report title/footnote window from milestone start and due/end dates."""
    return milestone_timeline_chart_bounds(
        milestones,
        quarter_start=fallback_start,
        quarter_end=fallback_end,
    )


def _milestone_start_field_id(adapter: AtlassianAdapter) -> str:
    aliases = adapter._resolve_field_aliases()
    for name in ("Start date", "Start Date", "Target start", "Target Start"):
        field_id = aliases.get(name)
        if field_id:
            return field_id
    return "customfield_10015"


def _milestone_notes_field_id(adapter: AtlassianAdapter) -> str:
    aliases = adapter._resolve_field_aliases()
    return aliases.get("Notes") or "customfield_10475"


def _milestone_goal_target_field_id(adapter: AtlassianAdapter) -> str | None:
    aliases = adapter._resolve_field_aliases()
    for name in ("Goal Target", "Goal target", "Target date", "Target Date"):
        field_id = aliases.get(name)
        if field_id:
            return field_id
    return None


def fetch_milestone_timeline(
    adapter: AtlassianAdapter,
    *,
    initiative_key: str,
    quarter_start: date,
    quarter_end: date,
    quarter_filter: str | None = None,
    in_scope_filter: str | None = None,
    milestone_report_project: str = "PDE",
    delivery_squad_field: str = "customfield_11102",
    change_types_field: str = "customfield_10079",
    platform_field: str = "customfield_10120",
    story_points_field: str = "customfield_10026",
    skip_issue_types: frozenset[str] = frozenset(),
    changelog_cache_path: Path | None = None,
) -> dict[str, Any]:
    jira_binding = load_jira_binding() if quarter_filter else None

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
    start_field = _milestone_start_field_id(adapter)
    notes_field = _milestone_notes_field_id(adapter)
    goal_target_field = _milestone_goal_target_field_id(adapter)
    fields = [
        "summary",
        "description",
        "duedate",
        "status",
        "issuetype",
        "created",
        start_field,
        notes_field,
    ]
    if goal_target_field:
        fields.append(goal_target_field)
    if quarter_filter:
        fields.append("issuelinks")

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
        fields,
    )

    milestones: list[dict[str, Any]] = []
    scope_issues_by_key: dict[str, dict[str, Any]] = {}
    for issue in children:
        key = issue["key"]
        issue_fields = issue.get("fields") or {}
        created = (issue_fields.get("created") or "")[:10]
        due_raw = issue_fields.get("duedate")
        start_raw = issue_fields.get(start_field)
        goal_target_raw = issue_fields.get(goal_target_field) if goal_target_field else None
        if isinstance(start_raw, str):
            start_s = start_raw[:10]
        else:
            start_s = None
        start, end = resolve_milestone_window(
            start_date=start_s,
            created=created,
            due_date=str(due_raw)[:10] if due_raw else None,
            quarter_start=quarter_start,
            quarter_end=quarter_end,
        )
        status = (issue_fields.get("status") or {}).get("name") or ""
        description = milestone_work_item_description(issue_fields)
        notes = milestone_work_item_notes(issue_fields, notes_field=notes_field)
        row: dict[str, Any] = {
            "key": key,
            "label": str(issue_fields.get("summary") or "").strip(),
            "summary": str(issue_fields.get("summary") or "").strip(),
            "status": status,
            "created": created,
            "startDate": start.isoformat(),
            "dueDate": str(due_raw)[:10] if due_raw else None,
            "endDate": end.isoformat(),
            "startDateSource": (
                "start_field"
                if start_s
                else "created"
                if _parse_day(created)
                else "quarter_start"
            ),
        }
        if goal_target_raw:
            row["goalTargetDate"] = str(goal_target_raw)[:10]
        if description:
            row["description"] = description
        if notes:
            row["notes"] = notes

        if quarter_filter and jira_binding is not None:
            linked = milestone_linked_issues(issue)
            epic_keys = [str(item["key"]) for item in linked if item.get("key")]
            epic_summaries = {
                str(item["key"]): str(((item.get("fields") or {}).get("summary") or "")).strip()
                for item in linked
                if item.get("key")
            }
            lane_buckets: dict[str, dict[str, Any]] = {}
            if epic_keys:
                keys_csv = ", ".join(epic_keys)
                child_jql = milestone_linked_epic_scope_jql(parent_keys_csv=keys_csv)
                child_fields = [
                    "parent",
                    "issuetype",
                    "status",
                    "created",
                    story_points_field,
                    change_types_field,
                    delivery_squad_field,
                    platform_field,
                    "issuelinks",
                ]
                scope_children = search_all(adapter, child_jql, child_fields)
                for child in scope_children:
                    child_key = str(child.get("key") or "")
                    if child_key and not skip_issue(child):
                        scope_issues_by_key[child_key] = child
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
                if scope_issue_keys:
                    row["scopeIssueKeys"] = scope_issue_keys
                epic_rollups = rollup_milestone_epic_phases(
                    scope_children,
                    epic_keys=epic_keys,
                    delivery_squad_field=delivery_squad_field,
                    change_types_field=change_types_field,
                    platform_field=platform_field,
                    story_points_field=story_points_field,
                    binding=jira_binding,
                    skip_issue=skip_issue,
                )
                scope_epics = [
                    {
                        "key": epic_key,
                        "summary": epic_summaries.get(epic_key, ""),
                        "rollup": epic_rollups[epic_key],
                    }
                    for epic_key in epic_keys
                    if float((epic_rollups.get(epic_key) or {}).get("totalWeight") or 0) > 0
                ]
                if scope_epics:
                    row["scopeEpics"] = scope_epics
            scope_rollup = aggregate_milestone_scope(lane_buckets)
            if float(scope_rollup.get("totalWeight") or 0) > 0:
                row["scopeRollup"] = scope_rollup

        milestones.append(row)

    notes_keys = [str(row.get("key") or "") for row in milestones if row.get("notes")]
    if notes_keys:
        milestones_by_key = {str(row.get("key") or ""): row for row in milestones}
        for index, key in enumerate(notes_keys, start=1):
            print(f"notes changelog {index}/{len(notes_keys)} {key}...", flush=True)
            histories = fetch_issue_changelog_histories(adapter, key)
            updated = notes_field_last_updated(histories, notes_field_id=notes_field)
            if updated is not None:
                milestones_by_key[key]["notesUpdatedAt"] = updated.astimezone(timezone.utc).isoformat()

    if scope_issues_by_key and quarter_filter:
        changelogs = fetch_scope_changelogs(
            adapter,
            sorted(scope_issues_by_key.keys()),
            cache_path=changelog_cache_path,
        )
        for milestone in milestones:
            scope_keys = milestone.get("scopeIssueKeys") or []
            scope_issues = [scope_issues_by_key[key] for key in scope_keys if key in scope_issues_by_key]
            milestone_end = (
                _parse_day(str(milestone.get("endDate") or "")[:10])
                or _parse_day(str(milestone.get("dueDate") or "")[:10])
                or quarter_end
            )
            scope_window_end = max(quarter_end, milestone_end)
            if jira_binding is not None:
                scope_phases, scope_daily, scope_total = build_milestone_scope_phase_daily(
                    scope_issues,
                    changelogs,
                    binding=jira_binding,
                    quarter_start=quarter_start,
                    quarter_end=scope_window_end,
                    sp_field=story_points_field,
                )
            else:
                scope_daily, scope_total = build_milestone_scope_daily(
                    scope_issues,
                    changelogs,
                    quarter_start=quarter_start,
                    quarter_end=scope_window_end,
                    sp_field=story_points_field,
                )
                scope_phases = {}
            if scope_daily:
                milestone["scopeDaily"] = scope_daily
                milestone["totalScopeStoryPoints"] = round(scope_total, 2)
            if scope_phases:
                milestone["scopePhases"] = scope_phases
                milestone["phaseOrder"] = list(phase_stack_order())

    milestones.sort(key=lambda row: (row.get("dueDate") or "9999-12-31", row.get("key") or ""))

    window_start, window_end = milestone_report_window_from_rows(
        milestones,
        fallback_start=quarter_start,
        fallback_end=quarter_end,
    )

    return {
        "initiativeKey": initiative_key,
        "hubKey": hub_key,
        "hubSummary": hub_fields.get("summary") or "",
        "quarterStart": window_start.isoformat(),
        "quarterEnd": window_end.isoformat(),
        "reportWindowStart": window_start.isoformat(),
        "reportWindowEnd": window_end.isoformat(),
        "inScopeFilter": in_scope_filter,
        "milestoneReportProject": milestone_report_project,
        "milestoneCount": len(milestones),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "milestones": milestones,
    }


def default_milestone_timeline_path(repo_root: Path | None = None) -> Path:
    from extensions.twoa_programme.quarterly_reporting import load_quarterly_reporting_config

    root = repo_root or _REPO_ROOT
    config_path = root / "config" / "quarterly-reporting.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    name = (payload.get("milestoneScopeChart") or {}).get("timelineArtifactFile") or _ARTIFACT_NAME
    config = load_quarterly_reporting_config(config_path)
    return config.output_root(root) / name


def load_milestone_timeline_payload(path: Path | None = None) -> dict[str, Any] | None:
    artifact = path or default_milestone_timeline_path()
    if not artifact.is_file():
        return None
    return json.loads(artifact.read_text(encoding="utf-8"))


def load_milestone_timeline_calendar(
    output_dir: Path,
    *,
    quarter_start: date,
    quarter_end: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], date, date]:
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


def milestone_timeline_tooltip(milestone: dict[str, Any]) -> str:
    summary = str(milestone.get("summary") or milestone.get("label") or "")
    status = str(milestone.get("status") or "")
    lines = [
        summary,
        f"Status: {status}",
        f"Timeline: {milestone.get('startDate')} to {milestone.get('endDate')}",
    ]
    if milestone.get("dueDate"):
        lines.append(f"Due date: {milestone.get('dueDate')}")
    notes = str(milestone.get("notes") or "").strip()
    if notes:
        lines.append("")
        lines.append(milestone_notes_heading(notes_updated_at=milestone.get("notesUpdatedAt")))
        lines.extend(f"  {line}" if line else "" for line in notes.splitlines())
    scope = milestone.get("scopeRollup")
    if scope and float(scope.get("totalWeight") or 0) > 0:
        sp = float(scope.get("storyPoints") or 0)
        unpointed = int(scope.get("unpointedCount") or 0)
        total = float(scope.get("totalWeight") or 0)
        lines.append("")
        lines.append(f"Scope: {total:g} weight ({sp:g} SP + {unpointed} unpointed)")
        for segment in lane_bar_segments(scope, segment_order=timeline_bar_segment_order()):
            pct = segment["fraction"] * 100
            lines.append(f"  {segment['key']}: {segment['weight']:g} ({pct:.0f}%)")
    return "\n".join(lines)


def _active_scope_epics(milestone: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        epic
        for epic in milestone.get("scopeEpics") or []
        if float((epic.get("rollup") or {}).get("totalWeight") or 0) > 0
    ]


def milestone_block_height(milestone: dict[str, Any]) -> int:
    content = MILESTONE_ROW_HEIGHT + len(_active_scope_epics(milestone)) * SUB_ROW_HEIGHT
    return content + 2 * MILESTONE_BLOCK_PAD_Y


def _append_sub_scope_bar(
    parts: list[str],
    *,
    rollup: dict[str, Any],
    x0: float,
    y0: float,
    bar_w: float,
    bar_h: float,
    tooltip: str,
    base_fill: str = ATL["grid"],
) -> None:
    if bar_w <= 0:
        return
    parts.append(f'<g>{_svg_embedded_title(tooltip)}')
    parts.append(
        f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
        f'rx="1" fill="{base_fill}" opacity="{SUB_BAR_BASE_OPACITY}"/>'
    )
    segments = lane_bar_segments(rollup, segment_order=timeline_bar_segment_order())
    if segments:
        append_scope_composition_overlay(
            parts,
            rollup=rollup,
            segments=segments,
            x0=x0,
            y0=y0,
            bar_w=bar_w,
            bar_h=bar_h,
            overlay_opacity=SUB_SCOPE_OVERLAY_OPACITY,
        )
    parts.append("</g>")


def _truncate_label(text: str, max_chars: int = 42) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[: max_chars - 1]}…"


def _append_clickable_summary_label(
    parts: list[str],
    *,
    text: str,
    x: float,
    y_center: float,
    url: str,
    tooltip: str,
    font_size: int = 10,
    max_chars: int = LABEL_MAX_CHARS,
    max_lines: int = 1,
    link_class: str = "milestone-parent",
    fill: str | None = None,
    font_weight: str = "600",
) -> None:
    if max_lines > 1:
        lines = _wrap_text_lines(text, max_chars=max_chars, max_lines=max_lines)
    else:
        lines = [_truncate_label(text, max_chars)]
    line_height = font_size + 3
    block_h = len(lines) * line_height
    start_y = y_center - block_h / 2 + line_height - 2
    text_fill = fill or ATL["ink"]
    parts.append(f'<g clip-path="url(#milestone-label-col)">{_svg_embedded_title(tooltip)}')
    parts.append(f'<a href="{url}" class="{link_class}" target="_blank" rel="noopener">')
    for index, line in enumerate(lines):
        y = start_y + index * line_height
        parts.append(
            f'<text x="{x}" y="{y:.1f}" text-anchor="start" dominant-baseline="middle" '
            f'font-family="{SVG_FONT}" font-size="{font_size}" fill="{text_fill}" '
            f'font-weight="{font_weight}">{html.escape(line)}</text>'
        )
    parts.append("</a></g>")


def _append_sub_row_label(
    parts: list[str],
    *,
    text: str,
    y_center: float,
    tooltip: str,
    link_url: str,
    font_size: int = 9,
    max_chars: int = EPIC_LABEL_MAX_CHARS,
) -> None:
    _append_clickable_summary_label(
        parts,
        text=text,
        x=SUB_LABEL_INDENT,
        y_center=y_center,
        url=link_url,
        tooltip=tooltip,
        font_size=font_size,
        max_chars=max_chars,
        max_lines=1,
        link_class="milestone-epic",
        fill=ATL["blue"],
        font_weight="500",
    )


def milestone_timeline_plot_height(milestones: list[dict[str, Any]]) -> int:
    if not milestones:
        return MILESTONE_ROW_HEIGHT
    height = sum(milestone_block_height(milestone) for milestone in milestones)
    height += MILESTONE_BLOCK_GAP * max(0, len(milestones) - 1)
    return height


def _milestone_block_layout(
    milestones: list[dict[str, Any]],
    *,
    plot_top: float,
) -> list[dict[str, Any]]:
    layouts: list[dict[str, Any]] = []
    y_cursor = plot_top
    for index, milestone in enumerate(milestones):
        if index > 0:
            y_cursor += MILESTONE_BLOCK_GAP
        block_h = milestone_block_height(milestone)
        layouts.append(
            {
                "index": index,
                "milestone": milestone,
                "y": y_cursor,
                "height": block_h,
            }
        )
        y_cursor += block_h
    return layouts


def _append_milestone_block_label_background(
    parts: list[str],
    *,
    index: int,
    y: float,
    height: float,
    plot_left: float,
) -> None:
    label_fill = MILESTONE_LABEL_FILL_ODD if index % 2 else MILESTONE_LABEL_FILL_EVEN
    parts.append(
        f'<rect x="0" y="{y:.1f}" width="{plot_left}" height="{height:.1f}" fill="{label_fill}"/>'
    )


def _append_milestone_block_frame(
    parts: list[str],
    *,
    y: float,
    height: float,
    plot_right: float,
) -> None:
    parts.append(
        f'<rect x="0" y="{y:.1f}" width="{plot_right:.1f}" height="{height:.1f}" '
        f'fill="none" stroke="{ATL["ink"]}" stroke-width="{MILESTONE_BLOCK_BORDER_WIDTH}"/>'
    )


def milestone_timeline_key_html(*, include_out_of_cycle_releases: bool = True) -> str:
    ooc_row = (
        '<div class="chart-key-row">'
        '<span class="legend-swatch release-out"></span> Out-of-cycle / other release (hover line)'
        "</div>"
        if include_out_of_cycle_releases
        else ""
    )
    return (
        '<div class="chart-key">'
        '<p class="chart-key-title"><strong>Key</strong></p>'
        '<div class="chart-key-row">'
        '<span class="legend-swatch sprint-a"></span>'
        '<span class="legend-swatch sprint-b"></span> Sprint labels (S#)'
        "</div>"
        '<div class="chart-key-row">'
        '<span class="legend-swatch release-in"></span> In-cycle engine release (hover line)'
        "</div>"
        f"{ooc_row}"
        '<div class="chart-key-row">'
        '<span class="legend-swatch" style="background:#0052cc;opacity:0.85"></span> '
        "Milestone window (start to due date)"
        "</div>"
        '<div class="chart-key-row">'
        "Scope bars: D-Train phases left to right with "
        '<span class="legend-swatch" style="background:#00875a"></span> Drive '
        "through "
        '<span class="legend-swatch" style="background:#de350b"></span> Dream '
        "(inverted from lifecycle order; matches burn-up stack)"
        "</div>"
        "</div>"
    )


def milestone_timeline_svg(
    payload: dict[str, Any],
    *,
    sprint_bands: list[dict[str, Any]] | None = None,
    releases: list[dict[str, Any]] | None = None,
    quarter_start: date | str | None = None,
    quarter_end: date | str | None = None,
    px_per_day: float = EPIC_CHART_PX_PER_DAY,
) -> str:
    milestones = payload.get("milestones") or []
    if not milestones:
        return '<p class="footnote">No milestones. Run fetch_milestone_timeline.py --write.</p>'

    x_min_default = date.fromisoformat(str(quarter_start or payload.get("quarterStart") or "2026-04-01")[:10])
    x_max = date.fromisoformat(str(quarter_end or payload.get("quarterEnd") or "2026-08-20")[:10])
    x_min, x_max = milestone_timeline_chart_bounds(
        milestones,
        quarter_start=x_min_default,
        quarter_end=x_max,
    )
    span_days = (x_max - x_min).days or 1
    milestone_rows_height = milestone_timeline_plot_height(milestones)
    calendar_top = MILESTONE_CALENDAR_TOP
    milestone_plot_top = calendar_top + MILESTONE_SPRINT_LABEL_BAND
    plot_h = milestone_rows_height + MILESTONE_SPRINT_LABEL_BAND
    release_label_anchor = calendar_top - 6
    plot_bottom = milestone_plot_top + milestone_rows_height
    svg_height = plot_bottom + _svg_x_bottom_margin()
    plot_w = milestone_timeline_plot_width(span_days, px_per_day=px_per_day)
    plot_left = MILESTONE_LABEL_WIDTH
    plot_right = plot_left + plot_w
    width = plot_right + MILESTONE_TIMELINE_RIGHT_PAD

    def x_for(day: date) -> float:
        offset = max(0, min(span_days, (day - x_min).days))
        return plot_left + offset / span_days * plot_w

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="{svg_height}" '
        f'viewBox="0 0 {width} {svg_height}" preserveAspectRatio="xMinYMin meet" '
        f'role="img" aria-label="Milestone delivery timeline">',
        f'<rect x="0" y="0" width="{width}" height="{svg_height}" fill="#ffffff"/>',
        "<defs>"
        f'<clipPath id="milestone-label-col">'
        f'<rect x="0" y="{milestone_plot_top}" width="{plot_left - 8}" '
        f'height="{milestone_rows_height}"/>'
        f"</clipPath></defs>",
    ]

    _svg_sprint_calendar_underlay(
        parts,
        sprint_bands=sprint_bands,
        plot_top=calendar_top,
        plot_bottom=plot_bottom,
        plot_h=plot_h,
        x_for=x_for,
        x_min=x_min,
        x_max=x_max,
        show_sprint_shading=False,
    )

    parts.append(
        f'<line x1="{plot_left}" y1="{calendar_top}" x2="{plot_left}" y2="{plot_bottom}" '
        f'stroke="{ATL["line"]}" stroke-width="1"/>'
    )
    parts.append(
        f'<line x1="{plot_left}" y1="{plot_bottom}" x2="{plot_right}" y2="{plot_bottom}" '
        f'stroke="{ATL["line"]}" stroke-width="1"/>'
    )
    parts.append(
        f'<line x1="{plot_left}" y1="{milestone_plot_top:.1f}" x2="{plot_right:.1f}" '
        f'y2="{milestone_plot_top:.1f}" stroke="{ATL["grid"]}" stroke-width="1"/>'
    )

    block_layouts = _milestone_block_layout(milestones, plot_top=milestone_plot_top)
    for block in block_layouts:
        _append_milestone_block_label_background(
            parts,
            index=block["index"],
            y=block["y"],
            height=block["height"],
            plot_left=plot_left,
        )

    y_cursor = milestone_plot_top
    for block in block_layouts:
        milestone = block["milestone"]
        block_y = block["y"]
        y0 = block_y + MILESTONE_BLOCK_PAD_Y
        row_cy = y0 + MILESTONE_ROW_HEIGHT / 2
        key = str(milestone.get("key") or "")
        summary = str(milestone.get("summary") or milestone.get("label") or key)
        start_s = str(milestone.get("startDate") or x_min.isoformat())[:10]
        end_s = str(milestone.get("endDate") or x_max.isoformat())[:10]
        start_day = date.fromisoformat(start_s)
        end_day = date.fromisoformat(end_s)
        x1 = x_for(start_day)
        x2 = x_for(end_day)
        bar_w = max(x2 - x1, 2.0)
        bar_h = MILESTONE_BAR_HEIGHT
        bar_y = y0 + (MILESTONE_ROW_HEIGHT - bar_h) / 2
        fill = epic_bar_fill(str(milestone.get("status") or ""))
        tip = milestone_timeline_tooltip(milestone)

        parts.append(f'<g>{_svg_embedded_title(tip)}')
        parts.append(
            f'<rect x="{x1:.1f}" y="{bar_y:.1f}" width="{bar_w:.1f}" '
            f'height="{bar_h:.1f}" rx="2" fill="{fill}" opacity="{MILESTONE_BAR_OPACITY}"/>'
        )
        scope = milestone.get("scopeRollup")
        if scope:
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
                    overlay_opacity=SCOPE_OVERLAY_OPACITY,
                )
        parts.append("</g>")

        browse_url = f"{JIRA_SERVER}/browse/{html.escape(key)}"
        _append_clickable_summary_label(
            parts,
            text=summary,
            x=LABEL_PAD_X,
            y_center=row_cy,
            url=browse_url,
            tooltip=tip,
            max_chars=LABEL_MAX_CHARS,
            max_lines=2,
        )
        y_cursor = y0 + MILESTONE_ROW_HEIGHT

        sub_bar_h = SUB_ROW_HEIGHT - 6.0
        for epic in _active_scope_epics(milestone):
            sub_y0 = y_cursor
            sub_cy = sub_y0 + SUB_ROW_HEIGHT / 2
            sub_bar_y = sub_y0 + (SUB_ROW_HEIGHT - sub_bar_h) / 2
            epic_key = str(epic.get("key") or "")
            epic_summary = str(epic.get("summary") or epic_key)
            epic_tip = epic_scope_tooltip(
                epic=epic,
                segment_order=timeline_bar_segment_order(),
            )
            _append_sub_scope_bar(
                parts,
                rollup=epic.get("rollup") or {},
                x0=x1,
                y0=sub_bar_y,
                bar_w=bar_w,
                bar_h=sub_bar_h,
                tooltip=epic_tip,
            )
            epic_url = f"{JIRA_SERVER}/browse/{html.escape(epic_key)}"
            _append_sub_row_label(
                parts,
                text=epic_summary,
                y_center=sub_cy,
                tooltip=epic_tip,
                link_url=epic_url,
            )
            y_cursor += SUB_ROW_HEIGHT

    for block in block_layouts:
        _append_milestone_block_frame(
            parts,
            y=block["y"],
            height=block["height"],
            plot_right=plot_right,
        )

    _svg_chart_vertical_markers(
        parts,
        releases=releases,
        milestones=None,
        plot_top=calendar_top,
        plot_bottom=plot_bottom,
        x_for=x_for,
        x_min=x_min,
        x_max=x_max,
    )

    _svg_x_axis_labels(
        parts,
        x_min=x_min,
        x_max=x_max,
        plot_bottom=plot_bottom,
        plot_left=plot_left,
        plot_right=plot_right,
        x_for=x_for,
    )
    parts.append("</svg>")
    return "".join(parts)


def build_milestone_timeline_html(
    payload: dict[str, Any],
    *,
    generated_on: str,
    page_title: str,
    sprint_bands: list[dict[str, Any]] | None = None,
    releases: list[dict[str, Any]] | None = None,
    quarter_start: date | str | None = None,
    quarter_end: date | str | None = None,
) -> str:
    from extensions.twoa_programme.milestone_report_scope import milestone_report_timeline_footnote

    chart = milestone_timeline_svg(
        payload,
        sprint_bands=sprint_bands,
        releases=releases,
        quarter_start=quarter_start,
        quarter_end=quarter_end,
    )
    footnote = milestone_report_timeline_footnote(
        payload,
        detail=(
            "Each bar runs from milestone start date (Jira Start date when set, else created) "
            "through due date. Scope colours run Drive (left) to Dream (right). "
            "Epic sub-bars show linked scope composition."
        ),
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html.escape(page_title)}</title>
  <style>{REPORT_CSS}{MILESTONE_TIMELINE_EXTRA_CSS}</style>
</head>
<body>
  <main class="report">
    <header class="report-header">
      <h1>{html.escape(page_title)}</h1>
      <p class="report-meta">Generated {html.escape(generated_on)}</p>
      <p class="footnote">{footnote}</p>
    </header>
    <section class="chart-section">
      <div class="chart-wrap chart-wrap-timeline chart-wrap-milestone">{chart}</div>
      {milestone_timeline_key_html()}
    </section>
  </main>
</body>
</html>
"""
