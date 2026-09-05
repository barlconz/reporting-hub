"""SVG chart primitives for quarterly dashboard."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from extensions.twoa_programme.pde_engine_releases import carriage_type_code
from extensions.twoa_programme.quarterly_dashboard_calendar import (
    _layout_release_labels,
    _parse_release_date,
    _release_line_stroke,
    _sprint_band_label,
    _week_start_dates,
    collect_sprint_bands,
    normalize_engine_releases,
    releases_from_release_plan,
    short_release_label,
    sprint_bands_from_release_plan,
)
from extensions.twoa_programme.quarterly_dashboard_constants import (
    ATL,
    CHART_AXIS_FONT,
    JIRA_SERVER,
    LANE_DEFAULT_LABELS,
    LANE_ORDER,
    LANE_PLOT_HEIGHT,
    LANE_STACK_FILL,
    LANE_STACK_OPACITY,
    PLOT_BOTTOM_MARGIN,
    PLOT_HEIGHT,
    REF_PLOT_HEIGHT,
    SPRINT_FILL,
    SVG_FONT,
    Y_AXIS_LEFT,
)
from extensions.twoa_programme.quarterly_reporting import NZ_TZ
from extensions.twoa_programme.quarterly_dashboard_data import (
    _lane_planned_goals,
    _parse_report_date,
    _release_code_tooltip,
    _total_scope_planned,
)
from extensions.twoa_programme.quarterly_dashboard_links import _fmt_num
from extensions.twoa_programme.quarterly_dashboard_markup import (
    _chart_key_box,
    _chart_key_wrap,
    _goal_pace_tip,
    _legend_tip_row,
    _sprint_band_tooltip,
    _svg_embedded_title,
)

import html
from datetime import datetime

# Matches .report-shell / main.report max-width (1280) minus horizontal body padding (32 * 2).
QUARTERLY_REPORT_MAX_SVG_WIDTH = 1216
QUARTERLY_REPORT_MIN_PLOT_WIDTH = 320
QUARTERLY_REPORT_DEFAULT_RIGHT_PAD = 24
# Matches prior .chart-wrap-timeline max-height — epic timeline scales rows to fit.
QUARTERLY_REPORT_MAX_EPIC_TIMELINE_SVG_HEIGHT = 720


def report_plot_width(
    span_days: int,
    *,
    px_per_day: float,
    plot_left: float,
    plot_right_pad: float = QUARTERLY_REPORT_DEFAULT_RIGHT_PAD,
    max_svg_width: int = QUARTERLY_REPORT_MAX_SVG_WIDTH,
    min_plot_width: int = QUARTERLY_REPORT_MIN_PLOT_WIDTH,
) -> int:
    """Plot area width capped so the full SVG fits the report page without horizontal scroll."""
    natural = int(span_days * px_per_day)
    max_plot = int(max_svg_width - plot_left - plot_right_pad)
    floor = min(min_plot_width, max(max_plot, 0))
    return max(min(natural, max_plot), floor)


def _svg_x_axis_labels(
    parts: list[str],
    *,
    x_min: date,
    x_max: date,
    plot_bottom: float,
    plot_left: float,
    plot_right: float,
    x_for,
    include_title: bool = True,
) -> None:
    """Week-start dd, month names, and optional Date title (same size as y-axis)."""
    week_y = plot_bottom + 16
    month_y = plot_bottom + 32
    for week_start in _week_start_dates(x_min, x_max):
        x = x_for(week_start)
        week_tip = f"Week start: {week_start.strftime('%a %d %b %Y')}"
        parts.append(
            f'<line x1="{x:.1f}" y1="{plot_bottom}" x2="{x:.1f}" y2="{plot_bottom + 4:.1f}" '
            f'stroke="{ATL["line"]}" stroke-width="1"/>'
        )
        parts.append(
            f'<g class="chart-x-week-label">{_svg_embedded_title(week_tip)}'
            f'<text x="{x:.1f}" y="{week_y:.1f}" text-anchor="middle" font-family="{SVG_FONT}" '
            f'font-size="{CHART_AXIS_FONT}" fill="{ATL["text_subtle"]}">'
            f'{html.escape(week_start.strftime("%d"))}</text></g>'
        )

    month = date(x_min.year, x_min.month, 1)
    while month <= x_max:
        if month >= x_min:
            x = x_for(month)
            month_tip = f"Month start: {month.strftime('%B %Y')}"
            parts.append(
                f'<g class="chart-x-month-label">{_svg_embedded_title(month_tip)}'
                f'<text x="{x:.0f}" y="{month_y:.1f}" text-anchor="middle" font-family="{SVG_FONT}" '
                f'font-size="{CHART_AXIS_FONT}" fill="{ATL["text_subtle"]}" font-weight="600">'
                f"{html.escape(month.strftime('%b'))}</text></g>"
            )
        if month.month == 12:
            month = date(month.year + 1, 1, 1)
        else:
            month = date(month.year, month.month + 1, 1)

    if include_title:
        title_y = plot_bottom + 48
        cx = (plot_left + plot_right) / 2
        parts.append(
            f'<text x="{cx:.0f}" y="{title_y:.1f}" text-anchor="middle" font-family="{SVG_FONT}" '
            f'font-size="{CHART_AXIS_FONT}" fill="{ATL["text_subtle"]}" font-weight="600">Date</text>'
        )


MILESTONE_LINE_STROKE = 2.5
MILESTONE_HIT_HALF_WIDTH = 8
MILESTONE_LINE_CLASS = "chart-milestone-line"
TODAY_LINE_STROKE = 2.5
TODAY_LINE_CLASS = "chart-today-line"
TODAY_LINE_COLOUR = "#000000"


def _week_month_grid_line_specs(
    *,
    x_min: date,
    x_max: date,
    x_for,
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for idx, week_start in enumerate(_week_start_dates(x_min, x_max)):
        specs.append(
            {
                "kind": "week",
                "idx": idx,
                "x": round(float(x_for(week_start)), 1),
                "tip": f"Week start: {week_start.strftime('%a %d %b %Y')}",
            }
        )

    month_idx = 0
    month = date(x_min.year, x_min.month, 1)
    while month <= x_max:
        if month >= x_min:
            specs.append(
                {
                    "kind": "month",
                    "idx": month_idx,
                    "x": round(float(x_for(month)), 1),
                    "tip": f"Month start: {month.strftime('%B %Y')}",
                }
            )
            month_idx += 1
        if month.month == 12:
            month = date(month.year + 1, 1, 1)
        else:
            month = date(month.year, month.month + 1, 1)
    return specs


def _svg_week_month_grid_lines(
    parts: list[str],
    *,
    specs: list[dict[str, Any]],
    plot_top: float,
    plot_bottom: float,
    element_id_prefix: str = "sefk-grid",
) -> None:
    """Full-height week/month grid lines (visual; hover handled client-side)."""
    parts.append('<g class="chart-week-month-grid" pointer-events="none">')
    for spec in specs:
        kind = str(spec["kind"])
        idx = int(spec["idx"])
        x = float(spec["x"])
        line_id = f"{element_id_prefix}-{kind}-{idx}"
        if kind == "week":
            parts.append(
                f'<line id="{line_id}" class="chart-week-grid-line" '
                f'x1="{x:.1f}" y1="{plot_top:.1f}" x2="{x:.1f}" y2="{plot_bottom:.1f}" '
                f'stroke="#cccccc" stroke-width="0.5" opacity="0.65"/>'
            )
        else:
            parts.append(
                f'<line id="{line_id}" class="chart-month-grid-line" '
                f'x1="{x:.1f}" y1="{plot_top:.1f}" x2="{x:.1f}" y2="{plot_bottom:.1f}" '
                f'stroke="#555555" stroke-width="0.6" stroke-dasharray="4 3" opacity="0.5"/>'
            )
    parts.append("</g>")


def _svg_week_month_grid_config_element(
    parts: list[str],
    *,
    specs: list[dict[str, Any]],
    plot_top: float,
    plot_bottom: float,
    plot_left: float,
    plot_right: float,
    element_id: str = "sefk-grid-lines",
) -> None:
    """Embed grid geometry for full-height hover tooltips (see SEFK chart script)."""
    payload = {
        "plotTop": round(plot_top, 1),
        "plotBottom": round(plot_bottom, 1),
        "plotLeft": round(plot_left, 1),
        "plotRight": round(plot_right, 1),
        "hitHalfWidth": MILESTONE_HIT_HALF_WIDTH,
        "lines": specs,
    }
    raw = json.dumps(payload, separators=(",", ":")).replace('"', "&quot;")
    parts.append(
        f'<text id="{html.escape(element_id)}" data-grid="{raw}" '
        f'visibility="hidden" fill="none">.</text>'
    )


def _svg_x_bottom_margin(*, include_title: bool = True, milestones: bool = False) -> int:
    """Space below plot for x-axis labels and optional Date title."""
    del milestones  # milestone letters use in-chart space only; no extra margin
    base = 58 if include_title else 40
    return max(PLOT_BOTTOM_MARGIN, base)


def _load_delivery_milestones(artifacts_path: Path | None = None) -> list[dict[str, Any]]:
    """Delivery milestone chart rows from output/delivery-milestones.json (Jira fetch)."""
    from extensions.twoa_programme.delivery_milestones import (
        chart_milestone_rows,
        load_delivery_milestones_payload,
    )

    payload = load_delivery_milestones_payload(artifacts_path)
    return chart_milestone_rows(payload)


def _milestone_tooltip_text(marker: dict[str, Any]) -> str:
    """Plain multi-line tooltip for chart SVG markers."""
    from extensions.twoa_programme.delivery_milestones import milestone_tooltip_plain

    ms = marker.get("ms") or marker
    return milestone_tooltip_plain(ms, pinned=bool(marker.get("pinned")))


def _milestone_issue_key(marker: dict[str, Any]) -> str | None:
    ms = marker.get("ms") or marker
    key = str(ms.get("key") or "").strip()
    return key or None


def _visible_chart_milestones(
    milestones: list[dict[str, Any]],
    *,
    x_min: date,
    x_max: date,
    x_for=None,
) -> list[dict[str, Any]]:
    """Quarter-visible milestones on the chart calendar."""
    ordered = sorted(milestones, key=lambda row: str(row.get("date") or ""))
    visible: list[dict[str, Any]] = []
    for ms in ordered:
        rd = date.fromisoformat(str(ms["date"])[:10])
        if rd < x_min:
            continue
        pinned = False
        if rd > x_max:
            if (rd - x_max).days > 3:
                continue
            pinned = True
        entry: dict[str, Any] = {
            "ms": ms,
            "label": str(ms.get("label") or ""),
            "date": str(ms["date"])[:10],
            "pinned": pinned,
        }
        if ms.get("key"):
            entry["key"] = str(ms["key"])
        if x_for is not None:
            entry["x"] = x_for(x_max if pinned else rd)
        visible.append(entry)
    return visible


def _append_milestone_markers(
    parts: list[str],
    markers: list[dict[str, Any]],
    *,
    plot_top: float,
    plot_bottom: float,
) -> None:
    """Solid red vertical lines on milestone due dates; hover for details, click for Jira."""
    stroke = ATL["red"]
    half_w = MILESTONE_HIT_HALF_WIDTH
    for marker in markers:
        x = float(marker["x"])
        tip = _milestone_tooltip_text(marker)
        issue_key = _milestone_issue_key(marker)
        hit_x = x - half_w
        hit_w = half_w * 2
        hit_h = plot_bottom - plot_top
        line_el = (
            f'<line class="{MILESTONE_LINE_CLASS}" x1="{x:.1f}" y1="{plot_top:.1f}" '
            f'x2="{x:.1f}" y2="{plot_bottom:.1f}" stroke="{stroke}" '
            f'stroke-width="{MILESTONE_LINE_STROKE}" opacity="0.92"/>'
        )
        hit_el = (
            f'<rect x="{hit_x:.1f}" y="{plot_top:.1f}" width="{hit_w:.1f}" height="{hit_h:.1f}" '
            f'fill="transparent" pointer-events="all"/>'
        )
        if issue_key:
            browse_url = f"{JIRA_SERVER}/browse/{html.escape(issue_key)}"
            parts.append(
                f'<g><a href="{browse_url}" target="_blank" rel="noopener" '
                f'class="chart-milestone-link">{_svg_embedded_title(tip)}{hit_el}{line_el}</a></g>'
            )
        else:
            parts.append(f"<g>{_svg_embedded_title(tip)}{hit_el}{line_el}</g>")


def _milestone_legend_swatch() -> str:
    red = ATL["red"]
    return (
        '<span class="legend-swatch milestone" aria-hidden="true">'
        f'<svg width="14" height="14" viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg">'
        f'<line x1="7" y1="1" x2="7" y2="13" stroke="{red}" stroke-width="2.5"/>'
        f"</svg></span>"
    )


def _chart_today_in_quarter(x_min: date, x_max: date) -> date | None:
    today = datetime.now(NZ_TZ).date()
    if x_min <= today <= x_max:
        return today
    return None


def _today_tooltip(today: date) -> str:
    return f"Today: {today.isoformat()} (Pacific/Auckland)"


def _append_today_marker(
    parts: list[str],
    *,
    today: date,
    x_for,
    plot_top: float,
    plot_bottom: float,
) -> None:
    """Solid black vertical line at today's date (NZ)."""
    x = float(x_for(today))
    tip = _today_tooltip(today)
    half_w = MILESTONE_HIT_HALF_WIDTH
    parts.append(
        f'<g class="chart-today-marker">{_svg_embedded_title(tip)}'
        f'<rect x="{x - half_w:.1f}" y="{plot_top:.1f}" width="{half_w * 2:.1f}" '
        f'height="{plot_bottom - plot_top:.1f}" fill="transparent" pointer-events="all"/>'
        f'<line class="{TODAY_LINE_CLASS}" x1="{x:.1f}" y1="{plot_top:.1f}" '
        f'x2="{x:.1f}" y2="{plot_bottom:.1f}" stroke="{TODAY_LINE_COLOUR}" '
        f'stroke-width="{TODAY_LINE_STROKE}" opacity="0.95"/>'
        f"</g>"
    )


def _today_legend_swatch() -> str:
    return (
        '<span class="legend-swatch today" aria-hidden="true">'
        f'<svg width="14" height="14" viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg">'
        f'<line x1="7" y1="1" x2="7" y2="13" stroke="{TODAY_LINE_COLOUR}" stroke-width="2.5"/>'
        f"</svg></span>"
    )


def _today_legend_key_row() -> str:
    return _legend_tip_row(
        f"{_today_legend_swatch()} Today (NZ)",
        "Solid black vertical line at today's date in Pacific/Auckland",
    )


def _milestone_legend_key_row() -> str:
    return _legend_tip_row(
        f"{_milestone_legend_swatch()} Delivery milestone",
        "Solid red vertical line on milestone due date; hover for details, click to open in Jira",
    )


def _linear_goal_polyline_points(
    *,
    x_min: date,
    x_max: date,
    goal_target: date,
    planned: float,
    x_for,
    y_pos,
) -> list[str]:
    """Rise linearly to full SP by goal_target; flat through quarter end if target is earlier."""
    rise_end = min(max(goal_target, x_min), x_max)
    pts = [
        f"{x_for(x_min):.1f},{y_pos(0.0):.1f}",
        f"{x_for(rise_end):.1f},{y_pos(planned):.1f}",
    ]
    if rise_end < x_max:
        pts.append(f"{x_for(x_max):.1f},{y_pos(planned):.1f}")
    return pts


def _quarter_goal_dates(x_min: date, x_max: date) -> list[date]:
    """Quarter endpoints for linear goal lines (through quarter end)."""
    return [x_min, x_max]


def _lane_goal_polylines(
    parts: list[str],
    *,
    x_min: date,
    x_max: date,
    lane_goals: dict[str, float],
    span_days: int,
    x_for,
    y_pos,
) -> None:
    """Linear scope goals through quarter end (dashed, slice colour)."""
    if not lane_goals:
        return
    goal_dates = _quarter_goal_dates(x_min, x_max)
    total_days = span_days + 1
    for lane_key in LANE_ORDER:
        planned = lane_goals.get(lane_key)
        if not planned or planned <= 0:
            continue
        pts: list[str] = []
        for day in goal_dates:
            frac = min(1.0, max(0.0, ((day - x_min).days + 1) / total_days))
            base = 0.0
            for below in LANE_ORDER:
                if below == lane_key:
                    break
                base += lane_goals.get(below, 0.0) * frac
            pts.append(f"{x_for(day):.1f},{y_pos(base + planned * frac):.1f}")
        stroke = LANE_STACK_FILL[lane_key]
        lane_label = LANE_DEFAULT_LABELS.get(lane_key, lane_key)
        tip = TIP_CHART_LANE_GOAL.format(lane=lane_label)
        parts.append(
            f'<g>{_svg_embedded_title(tip)}'
            f'<polyline fill="none" stroke="{stroke}" stroke-width="1.5" '
            f'stroke-dasharray="5 4" opacity="0.95" points="{" ".join(pts)}"/>'
            f"</g>"
        )


def _lane_daily_rows(lane: dict[str, Any]) -> list[dict]:
    daily = lane.get("daily") or []
    if daily:
        return daily
    events = lane.get("events") or []
    if not events:
        return []
    rows, _ = aggregate_daily_burn(events)
    return rows


def _aligned_lane_cumulative(
    lanes: dict[str, Any],
    global_daily: list[dict],
    lane_order: tuple[str, ...] = LANE_ORDER,
) -> tuple[list[date], dict[str, list[float]]]:
    """Forward-fill lane cumulative series on global daily dates."""
    if not global_daily:
        return [], {}
    dates = [date.fromisoformat(str(row["date"])[:10]) for row in global_daily]
    series: dict[str, list[float]] = {}
    for key in lane_order:
        lane = lanes.get(key) or {}
        by_date = {
            date.fromisoformat(str(row["date"])[:10]): float(row["cumulative_story_points"])
            for row in _lane_daily_rows(lane)
        }
        values: list[float] = []
        last = 0.0
        for day in dates:
            if day in by_date:
                last = by_date[day]
            values.append(last)
        series[key] = values
    return dates, series


def _release_line_tooltip(rel: dict[str, Any]) -> str:
    name = str(rel.get("name") or "").strip()
    if not name:
        name = short_release_label(str(rel.get("name", "")), rel)
    return f"{name} · {_release_code_tooltip(rel)}"


def _svg_sprint_calendar_underlay(
    parts: list[str],
    *,
    sprint_bands: list[dict[str, Any]] | None,
    plot_top: float,
    plot_bottom: float,
    plot_h: float,
    x_for,
    x_min: date,
    x_max: date,
    show_sprint_shading: bool = True,
    release_label_anchor: float | None = None,
) -> None:
    """Sprint shading/labels and plot top border (drawn behind chart series)."""
    del release_label_anchor
    for band in sprint_bands or []:
        x1 = x_for(band["start"])
        x2 = x_for(band["end"])
        w = max(x2 - x1, 1.0)
        if show_sprint_shading:
            parts.append(
                f'<rect x="{x1:.1f}" y="{plot_top}" width="{w:.1f}" height="{plot_h}" '
                f'fill="{band["fill"]}" opacity="0.65"/>'
            )
        sprint_label = _sprint_band_label(band)
        if sprint_label and w >= 28:
            cx = x1 + w / 2
            tip = _sprint_band_tooltip(band)
            parts.append(
                f'<text x="{cx:.1f}" y="{plot_top + 14:.1f}" text-anchor="middle" '
                f'font-family="{SVG_FONT}" font-size="11" fill="{ATL["text_subtle"]}" '
                f'font-weight="700" opacity="0.9">'
                f"{_svg_embedded_title(tip)}{html.escape(sprint_label)}</text>"
            )

    parts.append(
        f'<line x1="{x_for(x_min):.1f}" y1="{plot_top}" x2="{x_for(x_max):.1f}" y2="{plot_top}" '
        f'stroke="{ATL["line"]}" stroke-width="1"/>'
    )


def _svg_chart_vertical_markers(
    parts: list[str],
    *,
    releases: list[dict[str, Any]] | None,
    milestones: list[dict[str, Any]] | None = None,
    plot_top: float,
    plot_bottom: float,
    x_for,
    x_min: date,
    x_max: date,
) -> None:
    """Release, milestone due-date, and today lines (drawn on top of chart series)."""
    parts.append('<g class="chart-vertical-markers">')
    release_labels = _layout_release_labels(
        releases or [],
        x_for=x_for,
        x_min=x_min,
        x_max=x_max,
    )
    half_w = MILESTONE_HIT_HALF_WIDTH
    hit_h = plot_bottom - plot_top
    for x, _label, rel in release_labels:
        stroke = _release_line_stroke(rel)
        tip = _release_line_tooltip(rel)
        parts.append(
            f'<g>{_svg_embedded_title(tip)}'
            f'<rect x="{x - half_w:.1f}" y="{plot_top:.1f}" width="{half_w * 2:.1f}" '
            f'height="{hit_h:.1f}" fill="transparent" pointer-events="all"/>'
            f'<line x1="{x:.1f}" y1="{plot_top:.1f}" x2="{x:.1f}" y2="{plot_bottom:.1f}" '
            f'stroke="{stroke}" stroke-width="1.5" stroke-dasharray="5 4" opacity="0.65" '
            f'pointer-events="none"/>'
            f"</g>"
        )

    milestone_markers = _visible_chart_milestones(
        milestones or [],
        x_min=x_min,
        x_max=x_max,
        x_for=x_for,
    )
    _append_milestone_markers(
        parts,
        milestone_markers,
        plot_top=plot_top,
        plot_bottom=plot_bottom,
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
    parts.append("</g>")


def _svg_sprint_release_overlay(
    parts: list[str],
    *,
    sprint_bands: list[dict[str, Any]] | None,
    releases: list[dict[str, Any]] | None,
    milestones: list[dict[str, Any]] | None = None,
    plot_top: float,
    plot_bottom: float,
    plot_h: float,
    release_label_anchor: float,
    x_for,
    x_min: date,
    x_max: date,
    show_sprint_shading: bool = True,
) -> None:
    """Sprint calendar underlay plus vertical markers (legacy combined call)."""
    _svg_sprint_calendar_underlay(
        parts,
        sprint_bands=sprint_bands,
        plot_top=plot_top,
        plot_bottom=plot_bottom,
        plot_h=plot_h,
        x_for=x_for,
        x_min=x_min,
        x_max=x_max,
        show_sprint_shading=show_sprint_shading,
        release_label_anchor=release_label_anchor,
    )
    _svg_chart_vertical_markers(
        parts,
        releases=releases,
        milestones=milestones,
        plot_top=plot_top,
        plot_bottom=plot_bottom,
        x_for=x_for,
        x_min=x_min,
        x_max=x_max,
    )


def _resolve_chart_calendar(
    payload: dict,
    status: dict,
    squad: dict,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Sprint bands and engine releases for chart overlays (headline + lane charts)."""
    q_start = date.fromisoformat(status.get("quarterStart", "2026-04-01"))
    q_end = date.fromisoformat(status.get("quarterEnd", "2026-08-20"))
    allocation = payload.get("burnAllocation")
    plan = payload.get("releasePlan")
    if allocation:
        sprint_bands = sprint_bands_from_release_plan({"sprints": allocation.get("sprints") or []})
        if plan:
            releases = releases_from_release_plan(plan)
        else:
            releases = releases_from_release_plan(
                {"inCycleReleases": allocation.get("inCycleReleases") or []}
            )
    elif plan:
        sprint_bands = sprint_bands_from_release_plan(plan)
        releases = releases_from_release_plan(plan)
        jira_releases = normalize_engine_releases(payload.get("releases") or [], q_start, q_end)
        if not releases and jira_releases:
            releases = jira_releases
    else:
        sprint_bands = collect_sprint_bands(squad, q_start, q_end)
        releases = normalize_engine_releases(payload.get("releases") or [], q_start, q_end)
    return sprint_bands, releases


def _lane_chart_key_html() -> str:
    rows = [
        _legend_tip_row(
            (
                '<span class="legend-swatch sprint-a"></span>'
                '<span class="legend-swatch sprint-b"></span> Sprint bands (S# label)'
            ),
            "Alternating sprint shading from Release Plan; S# label when band is wide enough",
        ),
        _legend_tip_row(
            '<span class="legend-swatch release-in"></span> In-cycle engine release',
            "Vertical dashed line on engine release date (in-cycle carriage); hover for release name",
        ),
        _legend_tip_row(
            '<span class="legend-swatch release-out"></span> Out-of-cycle / other release',
            "Vertical dashed line on out-of-cycle or other engine release date; hover for release name",
        ),
        _legend_tip_row(
            f'<span class="legend-swatch lane-ec"></span> {html.escape(LANE_DEFAULT_LABELS["educationCloud"])}',
            "Cumulative deploy-earned SP stacked area for Education Cloud lane",
        ),
        _legend_tip_row(
            f'<span class="legend-swatch lane-int"></span> {html.escape(LANE_DEFAULT_LABELS["integration"])}',
            "Cumulative deploy-earned SP stacked area for Integration lane",
        ),
        _legend_tip_row(
            f'<span class="legend-swatch lane-data"></span> {html.escape(LANE_DEFAULT_LABELS["dataMigration"])}',
            "Cumulative Done-earned SP stacked area for Data Migration lane",
        ),
        _legend_tip_row(
            f'<span class="legend-swatch lane-unassigned"></span> {html.escape(LANE_DEFAULT_LABELS["unassigned"])}',
            "Cumulative deploy-earned SP for unassigned quarter scope",
        ),
        _legend_tip_row(
            f'<span class="legend-swatch global-line"></span> Global earned SP',
            "Combined deploy/done-earned SP across all lanes",
        ),
        _legend_tip_row(
            f'<span class="legend-swatch goal"></span> Scope goal total (linear)',
            "Linear pace to total planned SP in quarter scope by goal target date",
        ),
        _milestone_legend_key_row(),
        _today_legend_key_row(),
    ]
    return _chart_key_box("Key", rows)


