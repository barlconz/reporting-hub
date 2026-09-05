"""SEFK integrated project plan Gantt — Phase → Sub-Phase → Work Stream → Epic."""

from __future__ import annotations

import html
import json
from datetime import date
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from artifact.atlassian import AtlassianAdapter

from extensions.twoa_programme.epic_timeline import EPIC_CHART_PX_PER_DAY
from extensions.twoa_programme.field_maps import field_aliases
from extensions.twoa_programme.github_pages_nav import BREADCRUMB_CSS
from extensions.twoa_programme.milestone_scope_chart import (
    DTRAIN_PHASE_FILL,
    aggregate_milestone_scope,
    chart_dtrain_phases,
)
from extensions.twoa_programme.sefk_scope import (
    issue_excluded_from_sefk_project_plan,
    issue_has_kpmg_deleted_label,
    resolve_sefk_issue_dtrain_phase,
    rollup_sefk_epic_phases,
    sefk_epic_scope_jql,
    sefk_scope_exclusion_jql,
)
from extensions.twoa_programme.milestone_timeline import MILESTONE_TIMELINE_EXTRA_CSS
from extensions.twoa_programme.quarterly_dashboard_constants import ATL, JIRA_SERVER, SVG_FONT
from extensions.twoa_programme.quarterly_dashboard_markup import REPORT_CSS, _svg_embedded_title
from extensions.twoa_programme.quarterly_dashboard_svg_core import (
    QUARTERLY_REPORT_MAX_SVG_WIDTH,
    QUARTERLY_REPORT_MIN_PLOT_WIDTH,
    _append_today_marker,
    _chart_today_in_quarter,
    _svg_week_month_grid_config_element,
    _svg_week_month_grid_lines,
    _week_month_grid_line_specs,
    _svg_x_axis_labels,
    _svg_x_bottom_margin,
)
from extensions.twoa_programme.sef_block_scope import (
    build_block_scope_rollups,
    linked_scope_targets,
)
from extensions.twoa_programme.sef_project_plan_timeline import (
    BAR_OPACITY,
    BLOCK_BORDER_WIDTH,
    BLOCK_GAP,
    BLOCK_PAD_Y,
    CALENDAR_TOP,
    CHAPTER_BAR_HEIGHT,
    CHAPTER_ROW_HEIGHT,
    LABEL_MAX_CHARS,
    LABEL_PAD_X,
    LABEL_WIDTH,
    PHASE_BAR_HEIGHT,
    PHASE_GAP,
    PHASE_ROW_HEIGHT,
    RIGHT_PAD,
    SCOPE_OVERLAY_OPACITY,
    START_DATE_FIELD,
    STREAM_BAR_HEIGHT,
    STREAM_ROW_HEIGHT,
    SUB_LABEL_INDENT,
    _append_label_link,
    _append_label_text,
    _append_timeline_bar,
    _bar_tooltip,
    _child_keys_for_types,
    _fetch_children,
    _is_milestone_row,
    _issue_start_sort_key,
    _issue_timeline_row,
    _issue_type_name,
    _sort_sibling_keys,
    _label_with_duration_metrics,
    _parse_day,
    _truncate_label,
)
from extensions.twoa_programme.sefk_project_plan_reporting import (
    SefkProjectPlanReportingConfig,
    discover_phase_hub_issues,
    resolve_scope_filter_jql,
)
from extensions.twoa_programme.jira_search import search_all

_REPO_ROOT = Path(__file__).resolve().parents[2]
EPIC_ROW_HEIGHT = 22
EPIC_BAR_HEIGHT = EPIC_ROW_HEIGHT - 4
LEVEL_ZERO_ROW_HEIGHT = 20
LEVEL_ZERO_BAR_HEIGHT = LEVEL_ZERO_ROW_HEIGHT - 4
EPIC_LABEL_INDENT = 52
DTRAIN_BASE_FILL = ATL["grid"]
SUB_PHASE_BAR_HEIGHT = CHAPTER_BAR_HEIGHT
SUB_PHASE_ROW_HEIGHT = CHAPTER_ROW_HEIGHT
WORK_STREAM_ROW_HEIGHT = STREAM_ROW_HEIGHT
WORK_STREAM_BAR_HEIGHT = STREAM_BAR_HEIGHT
SEFK_LABEL_WIDTH_CAP = 420
SEFK_WORK_STREAM_LABEL_MAX_CHARS = 32
SEFK_EPIC_LABEL_MAX_CHARS = 36
SEFK_PHASE_LABEL_X = LABEL_PAD_X + 18
SEFK_SUB_PHASE_LABEL_X = LABEL_PAD_X + 42
SEFK_WORK_STREAM_LABEL_X = LABEL_PAD_X + 70
SEFK_EPIC_LABEL_X = LABEL_PAD_X + 102
SEFK_LEVEL_ZERO_LABEL_X = LABEL_PAD_X + 126
RUN_ORDER_FIELD = "customfield_10541"


def _sefk_issue_type_icon_url(row: dict[str, Any]) -> str:
    raw = str(row.get("issueTypeIconUrl") or "").strip()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        return raw
    if raw.startswith("/"):
        return f"{JIRA_SERVER}{raw}"
    return f"{JIRA_SERVER}/{raw}"


def _append_sefk_issue_type_icon(
    parts: list[str],
    *,
    row: dict[str, Any],
    x: float,
    y_center: float,
    size: float = 14.0,
) -> None:
    issue_type = str(row.get("issueType") or "").strip()
    issue_type_folded = issue_type.casefold()
    row_key = str(row.get("key") or "").strip()
    data_key_attr = f' data-sef-key="{html.escape(row_key)}" data-sef-row="1"' if row_key else ""
    if "milestone" in issue_type_folded:
        half = size / 2
        points = f"{x:.1f},{y_center - half:.1f} {x + half:.1f},{y_center:.1f} {x:.1f},{y_center + half:.1f} {x - half:.1f},{y_center:.1f}"
        parts.append(
            f'<polygon points="{points}" fill="#de350b" stroke="#a12d10" stroke-width="0.8" '
            f'data-sefk-icon="1"{data_key_attr} role="img"><title>{html.escape(issue_type)}</title></polygon>'
        )
        return
    if "gate" in issue_type_folded:
        icon_url = _sefk_issue_type_icon_url(row)
        if icon_url:
            parts.append(
                f'<image href="{html.escape(icon_url)}" x="{x - size / 2:.1f}" '
                f'y="{y_center - size / 2:.1f}" width="{size:.1f}" height="{size:.1f}" '
                f'preserveAspectRatio="xMidYMid meet" data-sefk-icon="1"{data_key_attr} role="img">'
                f'<title>{html.escape(issue_type)}</title></image>'
            )
            return
        half = size / 2
        parts.append(
            f'<rect x="{x - half:.1f}" y="{y_center - half:.1f}" width="{size:.1f}" height="{size:.1f}" '
            f'rx="1.5" fill="#6554c0" stroke="#403294" stroke-width="0.8" '
            f'data-sefk-icon="1"{data_key_attr} role="img"><title>{html.escape(issue_type)}</title></rect>'
        )
        return
    icon_url = _sefk_issue_type_icon_url(row)
    if not icon_url:
        return
    parts.append(
        f'<image href="{html.escape(icon_url)}" x="{x - size / 2:.1f}" '
        f'y="{y_center - size / 2:.1f}" width="{size:.1f}" height="{size:.1f}" '
        f'preserveAspectRatio="xMidYMid meet" data-sefk-icon="1"{data_key_attr} role="img">'
        f'<title>{html.escape(str(row.get("issueType") or "Issue type"))}</title></image>'
    )


def _sub_phase_order_tokens(token: str) -> tuple[str, ...]:
    folded = token.strip().casefold()
    if folded == "architecture":
        return ("architecture", "architect")
    return (folded,) if folded else ()


def sub_phase_order_index(issue: dict[str, Any], order: tuple[str, ...]) -> int:
    """Return sort index for a Sub-Phase issue summary against configured order."""
    if not order:
        return 0
    summary = str(((issue.get("fields") or {}).get("summary") or "")).strip().casefold()
    for index, entry in enumerate(order):
        for part in _sub_phase_order_tokens(entry):
            if entry.strip().casefold() == "test":
                if summary == "test":
                    return index
                continue
            if summary.startswith(part) or part in summary:
                return index
    return len(order)


def _sort_sub_phase_sibling_keys(
    keys: list[str],
    by_key: dict[str, dict[str, Any]],
    order: tuple[str, ...],
) -> list[str]:
    if not order:
        return _sort_sibling_keys(keys, by_key)

    def sort_key(key: str) -> tuple[int, float, int, date, str]:
        issue = by_key[key]
        start, issue_key = _issue_start_sort_key(issue)
        run_order = _run_order_sort_value(issue)
        return (*run_order, sub_phase_order_index(issue, order), start, issue_key)

    return sorted(keys, key=sort_key)


def _sort_sub_phase_issues(
    issues: list[dict[str, Any]],
    order: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not order:
        return sorted(issues, key=_issue_start_sort_key)

    def sort_key(issue: dict[str, Any]) -> tuple[int, float, int, date, str]:
        start, issue_key = _issue_start_sort_key(issue)
        run_order = _run_order_sort_value(issue)
        return (*run_order, sub_phase_order_index(issue, order), start, issue_key)

    return sorted(issues, key=sort_key)


def _run_order_sort_value(issue: dict[str, Any]) -> tuple[int, float]:
    raw = (issue.get("fields") or {}).get(RUN_ORDER_FIELD)
    if raw is None or str(raw).strip() == "":
        return 1, 0.0
    try:
        return 0, float(raw)
    except (TypeError, ValueError):
        return 1, 0.0


SEFK_EXTRA_CSS = """
.chart-wrap-sefk.chart-wrap-timeline {
  position: relative;
  max-height: none;
  overflow-x: auto;
  overflow-y: visible;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #f4f7fb;
  padding: 12px;
}
.chart-wrap-sefk svg {
  display: block;
  width: 100%;
  height: auto;
  min-width: 0;
}
.chart-wrap-sefk svg a text { text-decoration: none; }
.chart-wrap-sefk svg a:hover text { text-decoration: underline; }
.chart-grid-tooltip {
  position: absolute;
  z-index: 4;
  display: none;
  pointer-events: none;
  max-width: 240px;
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--card-bg);
  color: var(--text);
  font-size: 12px;
  line-height: 1.35;
  box-shadow: 0 4px 12px rgba(9, 30, 66, 0.15);
  white-space: nowrap;
}
.chart-wrap-sefk svg .chart-week-grid-line.is-hovered {
  stroke-width: 1.2;
  opacity: 0.95;
}
.chart-wrap-sefk svg .chart-month-grid-line.is-hovered {
  stroke-width: 1.4;
  opacity: 0.85;
}
.chart-key--dtrain .chart-key-phase-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin: 8px 0 4px;
}
.chart-key--dtrain .chart-key-phase-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
}
.chart-wrap-sefk svg text[id^="sefk-chev-"] {
  cursor: pointer;
  user-select: none;
}
.sefk-view-controls {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 0 0 10px;
}
.sefk-view-controls button,
.sefk-filter-controls button {
    border: 1px solid #c3ccda;
    border-bottom-color: #a9b6cc;
    border-radius: 999px;
    background: linear-gradient(180deg, #ffffff 0%, #f4f7fc 100%);
    color: var(--text);
    cursor: pointer;
    font: inherit;
    font-size: 12px;
    box-shadow:
        0 1px 0 rgba(255, 255, 255, 0.7) inset,
        0 1px 2px rgba(9, 30, 66, 0.16),
        0 1px 0 rgba(9, 30, 66, 0.05);
    transition: box-shadow 120ms ease, transform 60ms ease, background 120ms ease;
}
.sefk-view-controls button {
    padding: 5px 12px;
}
.sefk-view-controls button:hover,
.sefk-filter-controls button:hover {
    background: linear-gradient(180deg, #ffffff 0%, #eaf0fb 100%);
    box-shadow:
        0 1px 0 rgba(255, 255, 255, 0.8) inset,
        0 3px 6px rgba(9, 30, 66, 0.22);
}
.sefk-view-controls button:active,
.sefk-filter-controls button:active {
    box-shadow: 0 1px 3px rgba(9, 30, 66, 0.22) inset;
    transform: translateY(1px);
}
.sefk-view-controls button.is-active,
.sefk-filter-controls button.is-active {
    background: linear-gradient(180deg, #588aff 0%, #2f4fe0 100%);
    border-color: #2444c9;
    color: #ffffff;
    box-shadow:
        0 1px 3px rgba(9, 30, 66, 0.35) inset,
        0 1px 0 rgba(255, 255, 255, 0.2) inset;
}
.sefk-filter-controls {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 0 0 10px;
}
.sefk-filter-controls button {
    padding: 4px 9px;
}
.sefk-dependency-connector {
    cursor: help;
}
.sefk-dependency-hit-area {
    pointer-events: stroke;
}
.sefk-dependency-path,
.sefk-dependency-endpoint {
    transition: stroke 120ms ease, stroke-width 120ms ease, fill 120ms ease;
}
.sefk-dependency-connector:hover .sefk-dependency-path,
.sefk-dependency-connector.sefk-dependency-related .sefk-dependency-path {
    stroke: #0052cc;
    stroke-width: 2.2;
}
.sefk-dependency-connector:hover .sefk-dependency-endpoint,
.sefk-dependency-connector.sefk-dependency-related .sefk-dependency-endpoint {
    stroke: #0052cc;
    stroke-width: 2;
    fill: #deebff;
}
.chart-wrap-sefk svg [data-sef-key].sefk-dependency-related > rect {
    stroke: #0052cc;
    stroke-width: 2;
}
.chart-wrap-sefk svg [data-sef-key].sefk-dependency-related a text {
    fill: #0052cc;
}
"""

SEFK_COLLAPSE_SCRIPT = """
(function () {
  'use strict';

  function cfg(name, fallback) {
    var el = document.getElementById('sefk-cfg');
    if (!el) return fallback;
    var raw = el.getAttribute('data-' + name);
    var n = parseFloat(raw);
    return isFinite(n) ? n : fallback;
  }

  var BLOCK_PAD_Y = cfg('block-pad-y', 10);
  var SUB_PHASE_ROW_H = cfg('sub-phase-row-h', 36);
  var WORK_STREAM_ROW_H = cfg('work-stream-row-h', 24);
  var EPIC_ROW_H = cfg('epic-row-h', 22);
  var LEVEL_ZERO_ROW_H = cfg('level-zero-row-h', 20);

  function parseManifest(attr) {
    var el = document.getElementById('sefk-cm-sp');
    if (!el) return [];
    try {
      return JSON.parse((el.getAttribute(attr) || '[]').replace(/&quot;/g, '"'));
    } catch (_err) {
      return [];
    }
  }

    function dependencyParentMap() {
        var el = document.getElementById('sefk-cfg');
        if (!el) return {};
        try {
            return JSON.parse((el.getAttribute('data-parent-map') || '{}').replace(/&quot;/g, '"'));
        } catch (_err) {
            return {};
        }
    }

    function blockedByMap(svg) {
        var map = {};
        svg.querySelectorAll('[data-sef-dep-from][data-sef-dep-to]').forEach(function (node) {
            var from = (node.getAttribute('data-sef-dep-from') || '').trim();
            var to = (node.getAttribute('data-sef-dep-to') || '').trim();
            if (!from || !to) return;
            (map[to] = map[to] || []).push(from);
        });
        return map;
    }

    function withAntecedents(keys, blockedBy) {
        var visible = {};
        var queue = keys.slice();
        queue.forEach(function (key) { visible[key] = true; });
        while (queue.length) {
            var current = queue.shift();
            (blockedBy[current] || []).forEach(function (antecedent) {
                if (!visible[antecedent]) {
                    visible[antecedent] = true;
                    queue.push(antecedent);
                }
            });
        }
        return visible;
    }

  function resizeSvg(svg, delta) {
    if (!svg || !isFinite(delta) || delta === 0) return;
    var vb = (svg.getAttribute('viewBox') || '0 0 0 0').split(' ').map(Number);
    if (vb.length < 4) return;
    vb[3] = Math.max(100, vb[3] + delta);
    svg.setAttribute('viewBox', vb.join(' '));
    var h = parseFloat(svg.getAttribute('height') || '0');
    if (isFinite(h)) svg.setAttribute('height', String(Math.max(100, h + delta)));
        svg.querySelectorAll('.chart-week-grid-line, .chart-month-grid-line, .chart-today-line').forEach(function (line) {
            var y2 = parseFloat(line.getAttribute('y2') || '0');
            if (isFinite(y2)) line.setAttribute('y2', String(y2 + delta));
        });
        var axis = svg.getElementById('sefk-x-axis');
        if (axis) {
            var axisOffset = parseFloat(axis.getAttribute('data-offset-y') || '0') || 0;
            axisOffset += delta;
            axis.setAttribute('data-offset-y', String(axisOffset));
            axis.setAttribute('transform', 'translate(0,' + axisOffset + ')');
        }
  }

  function isHidden(node) {
    return !node || node.getAttribute('visibility') === 'hidden' || node.style.display === 'none';
  }

    function isEffectivelyHidden(node) {
        for (var current = node; current; current = current.parentElement) {
            if (isHidden(current)) return true;
        }
        return false;
    }

    function refreshDependencyVisibility(svg) {
        if (!svg) return;
        svg.querySelectorAll('[data-sef-dep-from][data-sef-dep-to]').forEach(function (connector) {
            var from = (connector.getAttribute('data-sef-dep-from') || '').trim();
            var to = (connector.getAttribute('data-sef-dep-to') || '').trim();
            var fromNode = svg.querySelector('[data-sef-key="' + from + '"]');
            var toNode = svg.querySelector('[data-sef-key="' + to + '"]');
            connector.setAttribute('visibility', !isEffectivelyHidden(fromNode) && !isEffectivelyHidden(toNode) ? 'visible' : 'hidden');
        });
    }

    function refreshDependencyGeometry(svg) {
        if (!svg) return;
        var svgRect = svg.getBoundingClientRect();
        var viewBox = (svg.getAttribute('viewBox') || '0 0 0 0').split(' ').map(Number);
        if (!svgRect.width || !svgRect.height || viewBox.length < 4) return;
        var scaleX = viewBox[2] / svgRect.width;
        var scaleY = viewBox[3] / svgRect.height;

        function barRect(key) {
            var bar = svg.querySelector(
                '[data-sef-key="' + key + '"][data-sef-role$="-bar"] rect, ' +
                '[data-sef-key="' + key + '"][data-sef-role$="-bar"] polygon, ' +
                '[data-sef-key="' + key + '"][data-sef-role$="-bar"] image'
            );
            return bar ? bar.getBoundingClientRect() : null;
        }
        function xFor(clientX) { return viewBox[0] + ((clientX - svgRect.left) * scaleX); }
        function yFor(clientY) { return viewBox[1] + ((clientY - svgRect.top) * scaleY); }

        svg.querySelectorAll('[data-sef-dep-from][data-sef-dep-to]').forEach(function (connector) {
            var from = (connector.getAttribute('data-sef-dep-from') || '').trim();
            var to = (connector.getAttribute('data-sef-dep-to') || '').trim();
            var fromRect = barRect(from);
            var toRect = barRect(to);
            if (!fromRect || !toRect) return;
            var pointsForward = toRect.left >= fromRect.right;
            var startX = xFor(pointsForward ? fromRect.right : fromRect.left) + (pointsForward ? 4 : -4);
            var endX = xFor(pointsForward ? toRect.left : toRect.right) + (pointsForward ? -4 : 4);
            var startY = yFor(fromRect.top + (fromRect.height / 2));
            var endY = yFor(toRect.top + (toRect.height / 2));
            var controlOffset = Math.min(64, Math.max(18, Math.abs(endX - startX) * 0.45)) * (pointsForward ? 1 : -1);
            var pathD = 'M ' + startX.toFixed(1) + ' ' + startY.toFixed(1) +
                ' C ' + (startX + controlOffset).toFixed(1) + ' ' + startY.toFixed(1) +
                ', ' + (endX - controlOffset).toFixed(1) + ' ' + endY.toFixed(1) +
                ', ' + endX.toFixed(1) + ' ' + endY.toFixed(1);
            connector.querySelectorAll('.sefk-dependency-hit-area, .sefk-dependency-path').forEach(function (path) {
                path.setAttribute('d', pathD);
            });
            var endpoints = connector.querySelectorAll('.sefk-dependency-endpoint');
            if (endpoints[0]) {
                endpoints[0].setAttribute('cx', startX.toFixed(1));
                endpoints[0].setAttribute('cy', startY.toFixed(1));
            }
            if (endpoints[1]) {
                endpoints[1].setAttribute('cx', endX.toFixed(1));
                endpoints[1].setAttribute('cy', endY.toFixed(1));
            }
        });
    }

  function workStreamBlockHeight(wsKey) {
    var sub = document.getElementById('sefk-sub-ws-' + wsKey);
    var epicH = parseInt((document.getElementById('sefk-ws-' + wsKey) || {}).getAttribute('data-epic-h') || '0', 10) || 0;
    if (isHidden(sub)) return WORK_STREAM_ROW_H;
    return WORK_STREAM_ROW_H + epicH;
  }

    function reflowWorkStreamEpics(wsGroup) {
        if (!wsGroup) return;
        var cumulativeShift = 0;
        wsGroup.querySelectorAll('.sefk-epic-row').forEach(function (epicGroup) {
            if (isHidden(epicGroup)) {
                cumulativeShift -= EPIC_ROW_H;
                return;
            }
            epicGroup.setAttribute('transform', cumulativeShift ? ('translate(0,' + cumulativeShift + ')') : 'translate(0,0)');
            var epicKey = (epicGroup.getAttribute('data-epic-key') || '').trim();
            var sub = document.getElementById('sefk-sub-epic-' + epicKey);
            if (!isHidden(sub)) {
                cumulativeShift += parseInt(epicGroup.getAttribute('data-level-zero-h') || '0', 10) || 0;
            }
        });
    }

    function recomputeEpicH(epicGroups) {
        var total = 0;
        epicGroups.forEach(function (epicGroup) {
            if (isHidden(epicGroup)) return;
            total += EPIC_ROW_H;
            var epicKey = (epicGroup.getAttribute('data-epic-key') || '').trim();
            var sub = document.getElementById('sefk-sub-epic-' + epicKey);
            if (sub && !isHidden(sub)) {
                total += parseInt(epicGroup.getAttribute('data-level-zero-h') || '0', 10) || 0;
            }
        });
        return total;
    }

    function reflowWorkStreamEpicVisibility(wsGroup, epicGroups, svg) {
        var oldEpicH = parseInt(wsGroup.getAttribute('data-epic-h') || '0', 10) || 0;
        var newEpicH = recomputeEpicH(epicGroups);
        if (newEpicH === oldEpicH) return;
        wsGroup.setAttribute('data-epic-h', String(newEpicH));
        reflowWorkStreamEpics(wsGroup);
        var spKey = (wsGroup.getAttribute('data-sp-key') || '').trim();
        if (spKey) {
            reflowSubPhaseContent(spKey);
            reflowSubPhaseBlocks();
        }
        resizeSvg(svg, newEpicH - oldEpicH);
    }

  function reflowSubPhaseContent(spKey) {
    var border = document.getElementById('sefk-bd-' + spKey);
    var spGroup = document.getElementById('sefk-sp-' + spKey);
    var sub = document.getElementById('sefk-sub-sp-' + spKey);
    if (!border || !spGroup || !sub) return 0;

    var y = BLOCK_PAD_Y + SUB_PHASE_ROW_H;
    var wsKeys = (sub.getAttribute('data-work-stream-keys') || '').split(',').filter(Boolean);
    wsKeys.forEach(function (wsKey) {
      var wsGroup = document.getElementById('sefk-ws-' + wsKey);
      if (!wsGroup || isHidden(wsGroup)) return;
      wsGroup.setAttribute('transform', 'translate(0,' + y + ')');
      y += workStreamBlockHeight(wsKey);
    });

    var collapsedH = parseInt(spGroup.getAttribute('data-collapsed-h'), 10) || (BLOCK_PAD_Y * 2 + SUB_PHASE_ROW_H);
    var subHidden = isHidden(sub);
    var newH = subHidden ? collapsedH : (y + BLOCK_PAD_Y);
    border.setAttribute('height', String(newH));

    var subH = Math.max(0, newH - collapsedH);
    spGroup.setAttribute('data-sub-h', String(subH));
    return newH;
  }

  function reflowSubPhaseBlocks() {
    var chapters = parseManifest('data-chapters');
    var cumulativeShift = 0;
    chapters.forEach(function (ch) {
      var g = document.getElementById('sefk-sp-' + ch.key);
      if (!g) return;
      g.setAttribute('transform', cumulativeShift ? ('translate(0,' + cumulativeShift + ')') : 'translate(0,0)');
      var sub = document.getElementById('sefk-sub-sp-' + ch.key);
            var baseSubH = parseInt(ch.baseSubH, 10) || 0;
            var currentSubH = isHidden(sub)
                ? 0
                : (parseInt(g.getAttribute('data-sub-h') || '0', 10) || 0);
            cumulativeShift += currentSubH - baseSubH;
    });
  }

    function reflowEpicLevelZeroHeight(epicGroup, newH, svg) {
        var oldH = parseInt(epicGroup.getAttribute('data-level-zero-h') || '0', 10) || 0;
        if (newH === oldH) return;
        epicGroup.setAttribute('data-level-zero-h', String(newH));
        var wsGroup = epicGroup.closest('[id^="sefk-ws-"]');
        var spKey = wsGroup ? (wsGroup.getAttribute('data-sp-key') || '').trim() : '';
        if (wsGroup) {
            var epicH = parseInt(wsGroup.getAttribute('data-epic-h') || '0', 10) || 0;
            wsGroup.setAttribute('data-epic-h', String(epicH + (newH - oldH)));
            reflowWorkStreamEpics(wsGroup);
        }
        if (spKey) {
            reflowSubPhaseContent(spKey);
            reflowSubPhaseBlocks();
        }
        resizeSvg(svg, newH - oldH);
    }

    function resetAllLevelZeroRowFilters(svg) {
        svg.querySelectorAll('.sefk-epic-row').forEach(function (epicGroup) {
            var baseH = parseInt(epicGroup.getAttribute('data-level-zero-base-h') || '0', 10) || 0;
            reflowEpicLevelZeroHeight(epicGroup, baseH, svg);
            epicGroup.querySelectorAll('.sefk-level-zero-row').forEach(function (row) {
                row.setAttribute('visibility', 'visible');
                row.style.display = '';
                row.setAttribute('transform', 'translate(0,0)');
            });
        });
    }

    function applyLevelZeroRowFilter(svg, visibleKeys) {
        svg.querySelectorAll('.sefk-epic-row').forEach(function (epicGroup) {
            var epicKey = (epicGroup.getAttribute('data-epic-key') || '').trim();
            var sub = document.getElementById('sefk-sub-epic-' + epicKey);
            if (!sub || isHidden(sub)) return;
            var rows = epicGroup.querySelectorAll('.sefk-level-zero-row');
            var visibleIndex = 0;
            rows.forEach(function (row, idx) {
                var key = (row.getAttribute('data-level-zero-key') || '').trim();
                if (visibleKeys[key]) {
                    var shift = (visibleIndex - idx) * LEVEL_ZERO_ROW_H;
                    row.setAttribute('transform', 'translate(0,' + shift + ')');
                    row.setAttribute('visibility', 'visible');
                    row.style.display = '';
                    visibleIndex += 1;
                } else {
                    row.setAttribute('visibility', 'hidden');
                    row.style.display = 'none';
                }
            });
            reflowEpicLevelZeroHeight(epicGroup, visibleIndex * LEVEL_ZERO_ROW_H, svg);
        });
    }

    function resetEpicVisibilityFilter(svg) {
        svg.querySelectorAll('[id^="sefk-sub-ws-"]').forEach(function (subWs) {
            var epicGroups = Array.prototype.slice.call(subWs.querySelectorAll(':scope > .sefk-epic-row'));
            if (!epicGroups.length) return;
            var anyHidden = epicGroups.some(function (g) { return isHidden(g); });
            if (!anyHidden) return;
            epicGroups.forEach(function (epicGroup) {
                epicGroup.setAttribute('visibility', 'visible');
                epicGroup.style.display = '';
            });
            var wsGroup = subWs.closest('[id^="sefk-ws-"]');
            if (wsGroup) reflowWorkStreamEpicVisibility(wsGroup, epicGroups, svg);
        });
    }

    function applyEpicVisibilityFilter(svg, visibleKeys) {
        svg.querySelectorAll('[id^="sefk-sub-ws-"]').forEach(function (subWs) {
            if (isHidden(subWs)) return;
            var epicGroups = Array.prototype.slice.call(subWs.querySelectorAll(':scope > .sefk-epic-row'));
            if (!epicGroups.length) return;
            epicGroups.forEach(function (epicGroup) {
                var epicKey = (epicGroup.getAttribute('data-epic-key') || '').trim();
                var visible = !!visibleKeys[epicKey];
                epicGroup.setAttribute('visibility', visible ? 'visible' : 'hidden');
                epicGroup.style.display = visible ? '' : 'none';
            });
            var wsGroup = subWs.closest('[id^="sefk-ws-"]');
            if (wsGroup) reflowWorkStreamEpicVisibility(wsGroup, epicGroups, svg);
        });
    }

    function resetWorkStreamVisibilityFilter(svg) {
        var affectedSpKeys = {};
        svg.querySelectorAll('[id^="sefk-ws-"]').forEach(function (wsGroup) {
            if (isHidden(wsGroup)) {
                wsGroup.setAttribute('visibility', 'visible');
                wsGroup.style.display = '';
                var spKey = (wsGroup.getAttribute('data-sp-key') || '').trim();
                if (spKey) affectedSpKeys[spKey] = true;
            }
        });
        var totalDelta = 0;
        Object.keys(affectedSpKeys).forEach(function (spKey) {
            var border = document.getElementById('sefk-bd-' + spKey);
            var oldH = border ? (parseInt(border.getAttribute('height') || '0', 10) || 0) : 0;
            var newH = reflowSubPhaseContent(spKey);
            totalDelta += newH - oldH;
        });
        if (totalDelta !== 0) {
            reflowSubPhaseBlocks();
            resizeSvg(svg, totalDelta);
        }
    }

    function applyWorkStreamVisibilityFilter(svg, visibleKeys) {
        var totalDelta = 0;
        svg.querySelectorAll('[id^="sefk-sub-sp-"]').forEach(function (sub) {
            if (isHidden(sub)) return;
            var spKey = sub.id.replace('sefk-sub-sp-', '');
            var wsKeys = (sub.getAttribute('data-work-stream-keys') || '').split(',').filter(Boolean);
            var border = document.getElementById('sefk-bd-' + spKey);
            var oldH = border ? (parseInt(border.getAttribute('height') || '0', 10) || 0) : 0;
            var changed = false;
            wsKeys.forEach(function (wsKey) {
                var wsGroup = document.getElementById('sefk-ws-' + wsKey);
                if (!wsGroup) return;
                var visible = !!visibleKeys[wsKey];
                if (visible === isHidden(wsGroup)) changed = true;
                wsGroup.setAttribute('visibility', visible ? 'visible' : 'hidden');
                wsGroup.style.display = visible ? '' : 'none';
            });
            if (!changed) return;
            var newH = reflowSubPhaseContent(spKey);
            totalDelta += newH - oldH;
        });
        if (totalDelta !== 0) {
            reflowSubPhaseBlocks();
            resizeSvg(svg, totalDelta);
        }
    }

  window.sefkToggleWorkStream = function (evt, wsKey) {
    if (evt) evt.stopPropagation();
    var sub = document.getElementById('sefk-sub-ws-' + wsKey);
    var chev = document.getElementById('sefk-chev-ws-' + wsKey);
    var wsGroup = document.getElementById('sefk-ws-' + wsKey);
    if (!sub || !wsGroup) return;

    var spKey = (wsGroup.getAttribute('data-sp-key') || '').trim();
    var epicH = parseInt(wsGroup.getAttribute('data-epic-h'), 10) || 0;
    var open = isHidden(sub);
    var delta = open ? epicH : -epicH;

    if (open) {
      sub.setAttribute('visibility', 'visible');
      sub.style.display = '';
      if (chev) chev.textContent = '\\u25BC';
    } else {
      sub.setAttribute('visibility', 'hidden');
      sub.style.display = 'none';
      if (chev) chev.textContent = '\\u25B6';
    }

    if (spKey) {
      reflowSubPhaseContent(spKey);
      reflowSubPhaseBlocks();
      var chapters = parseManifest('data-chapters');
      var entry = chapters.find(function (c) { return c.key === spKey; });
      if (entry) entry.subH = parseInt((document.getElementById('sefk-sp-' + spKey) || {}).getAttribute('data-sub-h') || '0', 10) || entry.subH;
    }

    var svg = wsGroup.closest('svg');
    resizeSvg(svg, delta);
        refreshDependencyVisibility(svg);
    refreshDependencyGeometry(svg);
  };

    window.sefkToggleEpic = function (evt, epicKey) {
        if (evt) evt.stopPropagation();
        var sub = document.getElementById('sefk-sub-epic-' + epicKey);
        var epicGroup = document.getElementById('sefk-epic-' + epicKey);
        var chev = document.getElementById('sefk-chev-epic-' + epicKey);
        if (!sub || !epicGroup) return;

        var open = isHidden(sub);
        var levelZeroH = parseInt(epicGroup.getAttribute('data-level-zero-h') || '0', 10) || 0;
        var wsGroup = epicGroup.closest('[id^="sefk-ws-"]');
        var spKey = wsGroup ? (wsGroup.getAttribute('data-sp-key') || '').trim() : '';
        if (open) {
            sub.setAttribute('visibility', 'visible');
            sub.style.display = '';
            if (chev) chev.textContent = '\u25BC';
        } else {
            sub.setAttribute('visibility', 'hidden');
            sub.style.display = 'none';
            if (chev) chev.textContent = '\u25B6';
        }
        if (wsGroup) {
            var epicH = parseInt(wsGroup.getAttribute('data-epic-h') || '0', 10) || 0;
            wsGroup.setAttribute('data-epic-h', String(epicH + (open ? levelZeroH : -levelZeroH)));
            reflowWorkStreamEpics(wsGroup);
        }
        if (spKey) {
            reflowSubPhaseContent(spKey);
            reflowSubPhaseBlocks();
            var chapters = parseManifest('data-chapters');
            var entry = chapters.find(function (c) { return c.key === spKey; });
            if (entry) entry.subH = parseInt((document.getElementById('sefk-sp-' + spKey) || {}).getAttribute('data-sub-h') || '0', 10) || entry.subH;
        }
        var svg = epicGroup.closest('svg');
        resizeSvg(svg, open ? levelZeroH : -levelZeroH);
        refreshDependencyVisibility(svg);
        refreshDependencyGeometry(svg);
    };

  window.sefkToggleSubPhase = function (evt, spKey) {
    if (evt) evt.stopPropagation();
    var sub = document.getElementById('sefk-sub-sp-' + spKey);
    var border = document.getElementById('sefk-bd-' + spKey);
    var chev = document.getElementById('sefk-chev-sp-' + spKey);
    var spGroup = document.getElementById('sefk-sp-' + spKey);
    if (!sub || !spGroup) return;

    var open = isHidden(sub);
    var subH = parseInt(spGroup.getAttribute('data-sub-h'), 10) || 0;
    var collapsedH = parseInt(spGroup.getAttribute('data-collapsed-h'), 10) || 0;

    if (open) {
      sub.setAttribute('visibility', 'visible');
      sub.style.display = '';
      if (chev) chev.textContent = '\\u25BC';
      if (border) border.setAttribute('height', String(collapsedH + subH));
    } else {
      sub.setAttribute('visibility', 'hidden');
      sub.style.display = 'none';
      if (chev) chev.textContent = '\\u25B6';
      if (border) border.setAttribute('height', String(collapsedH));
    }

    reflowSubPhaseBlocks();
    var svg = spGroup.closest('svg');
    resizeSvg(svg, open ? subH : -subH);
        refreshDependencyVisibility(svg);
    refreshDependencyGeometry(svg);
  };

    window.sefkCollapseAll = function () {
        document.querySelectorAll('[id^="sefk-sub-epic-"]').forEach(function (sub) {
            var epicKey = sub.id.replace('sefk-sub-epic-', '');
            if (!isHidden(sub)) window.sefkToggleEpic(null, epicKey);
        });
        document.querySelectorAll('[id^="sefk-sub-ws-"]').forEach(function (sub) {
            var wsKey = sub.id.replace('sefk-sub-ws-', '');
            if (!isHidden(sub)) window.sefkToggleWorkStream(null, wsKey);
        });
        document.querySelectorAll('[id^="sefk-sub-sp-"]').forEach(function (sub) {
            var spKey = sub.id.replace('sefk-sub-sp-', '');
            if (!isHidden(sub)) window.sefkToggleSubPhase(null, spKey);
        });
    };

    window.sefkExpandAll = function () {
        document.querySelectorAll('[id^="sefk-sub-sp-"]').forEach(function (sub) {
            var spKey = sub.id.replace('sefk-sub-sp-', '');
            if (isHidden(sub)) window.sefkToggleSubPhase(null, spKey);
        });
        document.querySelectorAll('[id^="sefk-sub-ws-"]').forEach(function (sub) {
            var wsKey = sub.id.replace('sefk-sub-ws-', '');
            if (isHidden(sub)) window.sefkToggleWorkStream(null, wsKey);
        });
        document.querySelectorAll('[id^="sefk-sub-epic-"]').forEach(function (sub) {
            var epicKey = sub.id.replace('sefk-sub-epic-', '');
            if (isHidden(sub)) window.sefkToggleEpic(null, epicKey);
        });
    };

    function setHierarchyView(level, button) {
        window.sefkCollapseAll();
        if (level === 'workstream' || level === 'epic') {
            document.querySelectorAll('[id^="sefk-sub-sp-"]').forEach(function (sub) {
                var spKey = sub.id.replace('sefk-sub-sp-', '');
                if (isHidden(sub)) window.sefkToggleSubPhase(null, spKey);
            });
        }
        if (level === 'epic') {
            document.querySelectorAll('[id^="sefk-sub-ws-"]').forEach(function (sub) {
                var wsKey = sub.id.replace('sefk-sub-ws-', '');
                if (isHidden(sub)) window.sefkToggleWorkStream(null, wsKey);
            });
        }
        document.querySelectorAll('.sefk-view-controls [data-hierarchy-level]').forEach(function (control) {
            control.classList.toggle('is-active', control === button);
        });
    }

    window.sefkShowPhaseLevel = function (button) {
        setHierarchyView('phase', button);
    };

    window.sefkShowWorkStreamLevel = function (button) {
        setHierarchyView('workstream', button);
    };

    window.sefkShowEpicLevel = function (button) {
        setHierarchyView('epic', button);
    };

    function hierarchyExpansionState(svg) {
        var state = {};
        svg.querySelectorAll('[id^="sefk-sub-sp-"], [id^="sefk-sub-ws-"], [id^="sefk-sub-epic-"]').forEach(function (sub) {
            state[sub.id] = !isHidden(sub);
        });
        return state;
    }

    function restoreHierarchyExpansionState(svg) {
        var raw = svg.getAttribute('data-sefk-filter-expansion-state');
        svg.removeAttribute('data-sefk-filter-expansion-state');
        if (!raw) return;
        var state;
        try {
            state = JSON.parse(raw);
        } catch (_err) {
            return;
        }
        window.sefkCollapseAll();
        Object.keys(state).filter(function (id) { return state[id] && id.indexOf('sefk-sub-sp-') === 0; }).forEach(function (id) {
            window.sefkToggleSubPhase(null, id.replace('sefk-sub-sp-', ''));
        });
        Object.keys(state).filter(function (id) { return state[id] && id.indexOf('sefk-sub-ws-') === 0; }).forEach(function (id) {
            window.sefkToggleWorkStream(null, id.replace('sefk-sub-ws-', ''));
        });
        Object.keys(state).filter(function (id) { return state[id] && id.indexOf('sefk-sub-epic-') === 0; }).forEach(function (id) {
            window.sefkToggleEpic(null, id.replace('sefk-sub-epic-', ''));
        });
    }

    function expandHierarchyPath(svg, key, parents) {
        var ancestors = [];
        var parent = String(parents[key] || '').trim();
        while (parent) {
            ancestors.push(parent);
            parent = String(parents[parent] || '').trim();
        }
        ancestors.reverse().forEach(function (ancestor) {
            if (document.getElementById('sefk-sub-sp-' + ancestor) && isHidden(document.getElementById('sefk-sub-sp-' + ancestor))) {
                window.sefkToggleSubPhase(null, ancestor);
            } else if (document.getElementById('sefk-sub-ws-' + ancestor) && isHidden(document.getElementById('sefk-sub-ws-' + ancestor))) {
                window.sefkToggleWorkStream(null, ancestor);
            } else if (document.getElementById('sefk-sub-epic-' + ancestor) && isHidden(document.getElementById('sefk-sub-epic-' + ancestor))) {
                window.sefkToggleEpic(null, ancestor);
            }
        });
    }

    window.sefkToggleFilter = function (kind, button) {
        var active = button.classList.toggle('is-active');
        var section = button.closest('.chart-section');
        var svg = section ? section.querySelector('svg') : null;
        if (!svg) return;

        if (!active) {
            resetAllLevelZeroRowFilters(svg);
            resetEpicVisibilityFilter(svg);
            resetWorkStreamVisibilityFilter(svg);
            svg.querySelectorAll('[data-sef-key]').forEach(function (node) {
                node.setAttribute('visibility', 'visible');
                node.style.opacity = '';
            });
            svg.querySelectorAll('[data-sef-dep-from][data-sef-dep-to]').forEach(function (node) {
                node.setAttribute('visibility', 'visible');
                node.style.opacity = '';
            });
            restoreHierarchyExpansionState(svg);
            refreshDependencyVisibility(svg);
            refreshDependencyGeometry(svg);
            return;
        }

        svg.setAttribute('data-sefk-filter-expansion-state', JSON.stringify(hierarchyExpansionState(svg)));
        resetAllLevelZeroRowFilters(svg);
        resetEpicVisibilityFilter(svg);
        resetWorkStreamVisibilityFilter(svg);
        var selector = kind === 'dependency'
            ? '[data-sef-has-dependency="1"]'
            : '[data-sef-special="' + kind + '"]';
        var matchedKeys = [];
        svg.querySelectorAll(selector).forEach(function (node) {
            var key = (node.getAttribute('data-sef-key') || '').trim();
            if (key) matchedKeys.push(key);
        });

        // Selected items plus everything that blocks them (their antecedents).
        var visibleKeys = withAntecedents(matchedKeys, blockedByMap(svg));

        // Collapse the whole hierarchy, then re-expand only the branches that lead to a visible item.
        window.sefkCollapseAll();
        var parents = dependencyParentMap();
        Object.keys(visibleKeys).forEach(function (key) {
            expandHierarchyPath(svg, key, parents);
        });
        Object.keys(visibleKeys).forEach(function (key) {
            var parent = String(parents[key] || '').trim();
            while (parent && !visibleKeys[parent]) {
                visibleKeys[parent] = true;
                parent = String(parents[parent] || '').trim();
            }
        });
        svg.querySelectorAll('[data-sef-key]').forEach(function (node) {
            var key = (node.getAttribute('data-sef-key') || '').trim();
            node.setAttribute('visibility', 'visible');
            node.style.opacity = visibleKeys[key] ? '1' : '0.16';
        });
        svg.querySelectorAll('[data-sef-dep-from][data-sef-dep-to]').forEach(function (node) {
            var from = (node.getAttribute('data-sef-dep-from') || '').trim();
            var to = (node.getAttribute('data-sef-dep-to') || '').trim();
            node.setAttribute('visibility', 'visible');
            node.style.opacity = visibleKeys[from] && visibleKeys[to] ? '1' : '0.16';
        });
        applyLevelZeroRowFilter(svg, visibleKeys);
        applyEpicVisibilityFilter(svg, visibleKeys);
        applyWorkStreamVisibilityFilter(svg, visibleKeys);
        refreshDependencyVisibility(svg);
        refreshDependencyGeometry(svg);
    };

    function setDependencyHighlight(svg, fromKey, toKey, active) {
        var relatedKeys = {};
        relatedKeys[fromKey] = true;
        relatedKeys[toKey] = true;
        svg.querySelectorAll('[data-sef-key]').forEach(function (node) {
            var key = (node.getAttribute('data-sef-key') || '').trim();
            if (relatedKeys[key]) node.classList.toggle('sefk-dependency-related', active);
        });
        svg.querySelectorAll('[data-sef-dep-from][data-sef-dep-to]').forEach(function (node) {
            var from = (node.getAttribute('data-sef-dep-from') || '').trim();
            var to = (node.getAttribute('data-sef-dep-to') || '').trim();
            if (from === fromKey && to === toKey) node.classList.toggle('sefk-dependency-related', active);
        });
    }

    function bindDependencyHover(svg) {
        svg.querySelectorAll('[data-sef-dep-from][data-sef-dep-to]').forEach(function (connector) {
            var from = (connector.getAttribute('data-sef-dep-from') || '').trim();
            var to = (connector.getAttribute('data-sef-dep-to') || '').trim();
            connector.addEventListener('mouseenter', function () { setDependencyHighlight(svg, from, to, true); });
            connector.addEventListener('mouseleave', function () { setDependencyHighlight(svg, from, to, false); });
        });
        svg.querySelectorAll('[data-sef-key]').forEach(function (node) {
            var key = (node.getAttribute('data-sef-key') || '').trim();
            if (!key) return;
            var connectors = Array.from(svg.querySelectorAll('[data-sef-dep-from][data-sef-dep-to]')).filter(function (connector) {
                return connector.getAttribute('data-sef-dep-from') === key || connector.getAttribute('data-sef-dep-to') === key;
            });
            if (!connectors.length) return;
            node.addEventListener('mouseenter', function () {
                connectors.forEach(function (connector) {
                    setDependencyHighlight(svg, connector.getAttribute('data-sef-dep-from'), connector.getAttribute('data-sef-dep-to'), true);
                });
            });
            node.addEventListener('mouseleave', function () {
                connectors.forEach(function (connector) {
                    setDependencyHighlight(svg, connector.getAttribute('data-sef-dep-from'), connector.getAttribute('data-sef-dep-to'), false);
                });
            });
        });
    }

    function statusDtrainMap() {
        var el = document.getElementById('sefk-cfg');
        if (!el) return {};
        try {
            return JSON.parse((el.getAttribute('data-status-dtrain-map') || '{}').replace(/&quot;/g, '"'));
        } catch (_err) {
            return {};
        }
    }

    function parseRowInfo(svg) {
        var info = {};
        svg.querySelectorAll('[data-sef-key][data-sef-role$="-bar"]').forEach(function (bar) {
            var key = (bar.getAttribute('data-sef-key') || '').trim();
            if (!key || info[key]) return;
            var titleEl = bar.querySelector('title');
            var text = titleEl ? (titleEl.textContent || '') : '';
            var dates = text.match(/Timeline:\\s*(\\d{4}-\\d{2}-\\d{2})\\S*\\s*to\\s*(\\d{4}-\\d{2}-\\d{2})/);
            if (!dates) return;
            var statusMatch = text.match(/Status:\\s*(.+)/);
            info[key] = {
                start: new Date(dates[1] + 'T00:00:00'),
                end: new Date(dates[2] + 'T00:00:00'),
                status: statusMatch ? statusMatch[1].trim() : '',
                bar: bar
            };
        });
        return info;
    }

    function fmtDate(d) {
        return d.toISOString().slice(0, 10);
    }

    var SEFK_SEVERITY_RANK = { green: 0, amber: 1, red: 2 };
    var SEFK_SEVERITY_FILL = { red: '#DE350B', amber: '#FFAB00', green: '#00875A' };
    var SEFK_SEVERITY_LABEL = { red: 'Alert', amber: 'Warning', green: 'On track' };

    function worseSeverity(a, b) {
        if (!a) return b;
        if (!b) return a;
        return SEFK_SEVERITY_RANK[a] >= SEFK_SEVERITY_RANK[b] ? a : b;
    }

    function appendAlertBadge(barEl, severity, tooltip) {
        var bbox;
        try {
            bbox = barEl.getBBox();
        } catch (_err) {
            return;
        }
        var ns = 'http://www.w3.org/2000/svg';
        var badge = document.createElementNS(ns, 'g');
        badge.setAttribute('class', 'sefk-alert-badge sefk-alert-' + severity);
        var circle = document.createElementNS(ns, 'circle');
        circle.setAttribute('cx', (bbox.x - 6).toFixed(1));
        circle.setAttribute('cy', (bbox.y + bbox.height / 2).toFixed(1));
        circle.setAttribute('r', '4.4');
        circle.setAttribute('fill', SEFK_SEVERITY_FILL[severity]);
        circle.setAttribute('stroke', '#ffffff');
        circle.setAttribute('stroke-width', '1');
        var titleEl = document.createElementNS(ns, 'title');
        titleEl.textContent = SEFK_SEVERITY_LABEL[severity] + ': ' + tooltip;
        badge.appendChild(titleEl);
        badge.appendChild(circle);
        // Insert alongside (not inside) a pill clip wrapper, so the badge isn't clipped away too.
        var anchor = barEl;
        if (anchor.parentNode && anchor.parentNode.classList && anchor.parentNode.classList.contains('sefk-pill-clip-wrap')) {
            anchor = anchor.parentNode;
        }
        anchor.parentNode.insertBefore(badge, anchor.nextSibling);
    }

    function computeSefkAlerts(svg) {
        var statusMap = statusDtrainMap();
        var doneStatuses = {};
        var notStartedStatuses = {};
        Object.keys(statusMap).forEach(function (status) {
            if (statusMap[status] === 'Drive') doneStatuses[status] = true;
            if (statusMap[status] === 'Dream') notStartedStatuses[status] = true;
        });

        var rows = parseRowInfo(svg);
        var blockedBy = blockedByMap(svg);
        var parents = dependencyParentMap();
        var today = new Date();
        today.setHours(0, 0, 0, 0);

        // Each item's own severity/reason, independent of its children.
        var ownSeverity = {};
        var ownReason = {};
        Object.keys(rows).forEach(function (key) {
            var row = rows[key];
            var severity = null;
            var reason = '';

            (blockedBy[key] || []).forEach(function (blockerKey) {
                var blocker = rows[blockerKey];
                if (blocker && row.start < blocker.end) {
                    severity = 'red';
                    reason = 'Starts ' + fmtDate(row.start) + ', before predecessor ' + blockerKey +
                        ' ends ' + fmtDate(blocker.end) + '.';
                }
            });

            if (!severity && !doneStatuses[row.status] && row.end < today) {
                severity = 'red';
                reason = 'Overdue: due ' + fmtDate(row.end) + ', status is "' + row.status + '".';
            }

            if (!severity && notStartedStatuses[row.status] && row.start < today) {
                severity = 'amber';
                reason = 'Not started: start date ' + fmtDate(row.start) + ' has passed.';
            }

            ownSeverity[key] = severity || 'green';
            ownReason[key] = severity ? reason : '';
        });

        // Direct children, derived from the hierarchy parent map (only for keys we have data for).
        var childrenOf = {};
        Object.keys(rows).forEach(function (key) {
            var parent = String(parents[key] || '').trim();
            if (parent && rows[parent]) {
                (childrenOf[parent] = childrenOf[parent] || []).push(key);
            }
        });

        // Worst severity across each item and all of its descendants.
        var aggregateSeverity = {};
        Object.keys(rows).forEach(function (key) {
            aggregateSeverity[key] = worseSeverity(aggregateSeverity[key], ownSeverity[key]);
            var parent = String(parents[key] || '').trim();
            while (parent && rows[parent]) {
                aggregateSeverity[parent] = worseSeverity(aggregateSeverity[parent], ownSeverity[key]);
                parent = String(parents[parent] || '').trim();
            }
        });

        // Red/amber/green counts across all descendants (not including the item itself), for parent tooltips.
        var descendantCountsMemo = {};
        function descendantCounts(key) {
            if (descendantCountsMemo[key]) return descendantCountsMemo[key];
            var counts = { red: 0, amber: 0, green: 0 };
            (childrenOf[key] || []).forEach(function (childKey) {
                counts[ownSeverity[childKey]] += 1;
                var childCounts = descendantCounts(childKey);
                counts.red += childCounts.red;
                counts.amber += childCounts.amber;
                counts.green += childCounts.green;
            });
            descendantCountsMemo[key] = counts;
            return counts;
        }

        Object.keys(rows).forEach(function (key) {
            var counts = descendantCounts(key);
            var totalChildren = counts.red + counts.amber + counts.green;
            var ownIsAlert = ownSeverity[key] !== 'green';
            var tooltip;
            if (totalChildren) {
                tooltip = (ownIsAlert ? ownReason[key] + ' ' : '') + 'Children: ' + counts.red + ' red, ' +
                    counts.amber + ' amber, ' + counts.green + ' green (of ' + totalChildren + ').';
            } else {
                tooltip = ownReason[key] || 'No issues.';
            }
            appendAlertBadge(rows[key].bar, aggregateSeverity[key], tooltip);
        });
    }

    document.querySelectorAll('.chart-wrap-sefk svg').forEach(bindDependencyHover);
    document.querySelectorAll('.chart-wrap-sefk svg').forEach(refreshDependencyVisibility);
    document.querySelectorAll('.chart-wrap-sefk svg').forEach(refreshDependencyGeometry);
    document.querySelectorAll('.chart-wrap-sefk svg').forEach(computeSefkAlerts);

  document.querySelectorAll('.chart-wrap-sefk').forEach(function (wrap) {
    wrap.addEventListener('wheel', function (evt) {
      if (wrap.scrollWidth <= wrap.clientWidth) return;
      var useHorizontal = evt.shiftKey || Math.abs(evt.deltaX) > Math.abs(evt.deltaY);
      if (!useHorizontal && Math.abs(evt.deltaY) > 0.01) useHorizontal = true;
      if (!useHorizontal) return;
      var delta = Math.abs(evt.deltaX) > 0.01 ? evt.deltaX : evt.deltaY;
      wrap.scrollLeft += delta;
      evt.preventDefault();
    }, { passive: false });
  });

  function initGridLineTooltips() {
    document.querySelectorAll('.chart-wrap-sefk').forEach(function (wrap) {
      var cfgEl = wrap.querySelector('#sefk-grid-lines');
      var svg = wrap.querySelector('svg');
      if (!cfgEl || !svg) return;

      var cfg;
      try {
        cfg = JSON.parse((cfgEl.getAttribute('data-grid') || '{}').replace(/&quot;/g, '"'));
      } catch (_err) {
        return;
      }

      var lines = cfg.lines || [];
      if (!lines.length) return;

      var plotTop = cfg.plotTop;
      var plotBottom = cfg.plotBottom;
      var plotLeft = cfg.plotLeft;
      var plotRight = cfg.plotRight;
      var hitHalf = cfg.hitHalfWidth || 8;

      var tipEl = document.createElement('div');
      tipEl.className = 'chart-grid-tooltip';
      tipEl.setAttribute('role', 'tooltip');
      wrap.appendChild(tipEl);

      var activeId = null;

      function clearHover() {
        if (activeId) {
          var prev = svg.getElementById(activeId);
          if (prev) prev.classList.remove('is-hovered');
          activeId = null;
        }
        tipEl.style.display = 'none';
        tipEl.textContent = '';
      }

      function svgCoords(evt) {
        var pt = svg.createSVGPoint();
        pt.x = evt.clientX;
        pt.y = evt.clientY;
        var ctm = svg.getScreenCTM();
        if (!ctm) return null;
        return pt.matrixTransform(ctm.inverse());
      }

      function lineDomId(line) {
        return 'sefk-grid-' + line.kind + '-' + line.idx;
      }

      function nearestLine(svgX, svgY) {
        if (svgY < plotTop || svgY > plotBottom || svgX < plotLeft || svgX > plotRight) return null;
        var best = null;
        var bestDist = hitHalf + 1;
        lines.forEach(function (line) {
          var dist = Math.abs(svgX - line.x);
          if (dist > hitHalf) return;
          if (
            !best ||
            dist < bestDist ||
            (dist === bestDist && line.kind === 'month' && best.kind !== 'month')
          ) {
            best = line;
            bestDist = dist;
          }
        });
        return best;
      }

      function positionTip(evt, text) {
        var rect = wrap.getBoundingClientRect();
        tipEl.textContent = text;
        tipEl.style.display = 'block';
        var tipRect = tipEl.getBoundingClientRect();
        var left = evt.clientX - rect.left + wrap.scrollLeft + 12;
        var top = evt.clientY - rect.top + wrap.scrollTop - tipRect.height - 10;
        if (left + tipRect.width > wrap.clientWidth - 4) {
          left = evt.clientX - rect.left + wrap.scrollLeft - tipRect.width - 12;
        }
        if (top < 4) top = evt.clientY - rect.top + wrap.scrollTop + 16;
        tipEl.style.left = left + 'px';
        tipEl.style.top = top + 'px';
      }

      svg.addEventListener('mousemove', function (evt) {
        var pt = svgCoords(evt);
        if (!pt) return;
        var line = nearestLine(pt.x, pt.y);
        if (!line) {
          clearHover();
          return;
        }
        var domId = lineDomId(line);
        if (activeId !== domId) {
          clearHover();
          var el = svg.getElementById(domId);
          if (el) {
            el.classList.add('is-hovered');
            activeId = domId;
          }
        }
        positionTip(evt, line.tip);
      });

      svg.addEventListener('mouseleave', clearHover);
    });
  }

  initGridLineTooltips();
})();
"""


def _sefk_truncate_label(text: str, max_chars: int = LABEL_MAX_CHARS) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[: max_chars - 1]}…"


def _sefk_work_stream_display_label(
    work_stream: dict[str, Any],
    sub_phase: dict[str, Any],
) -> str:
    summary = str(work_stream.get("summary") or work_stream.get("key") or "").strip()
    parent = str(sub_phase.get("summary") or "").strip()
    prefix = f"{parent} | "
    if parent and summary.lower().startswith(prefix.lower()):
        summary = summary[len(prefix) :].strip()
    return summary.replace("-", " ").replace("_", " ")


def _sefk_label_column_width(phases: list[dict[str, Any]]) -> float:
    labels: list[str] = []
    for phase in phases:
        phase_label = _label_with_duration_metrics(
            str(phase.get("summary") or phase.get("key") or ""),
            phase,
        )
        labels.append(phase_label)
        for sub_phase in phase.get("subPhases") or []:
            sub_label = _label_with_duration_metrics(
                str(sub_phase.get("summary") or sub_phase.get("key") or ""),
                sub_phase,
            )
            labels.append(sub_label)
            for work_stream in sub_phase.get("workStreams") or []:
                ws_label = _label_with_duration_metrics(
                    _sefk_work_stream_display_label(work_stream, sub_phase),
                    work_stream,
                )
                labels.append(ws_label)
                for epic in work_stream.get("epics") or []:
                    labels.append(
                        _sefk_truncate_label(
                            str(epic.get("summary") or epic.get("key") or ""),
                            SEFK_EPIC_LABEL_MAX_CHARS,
                        )
                    )
                    for level_zero in epic.get("levelZero") or []:
                        labels.append(
                            _sefk_truncate_label(
                                str(level_zero.get("summary") or level_zero.get("key") or ""),
                                SEFK_EPIC_LABEL_MAX_CHARS,
                            )
                        )
    longest = max((len(item.strip()) for item in labels if str(item).strip()), default=0)
    dynamic = 24 + (longest * 6.4)
    return min(max(float(LABEL_WIDTH), dynamic), float(SEFK_LABEL_WIDTH_CAP))


def default_sefk_project_plan_timeline_path(repo_root: Path | None = None) -> Path:
    from extensions.twoa_programme.sefk_project_plan_reporting import load_sefk_project_plan_reporting_config

    root = repo_root or _REPO_ROOT
    config = load_sefk_project_plan_reporting_config(repo_root=root)
    return config.timeline_path(root)


def load_sefk_project_plan_timeline_payload(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_sefk_rows(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for phase in phases:
        rows.append(phase)
        for sub_phase in phase.get("subPhases") or []:
            rows.append(sub_phase)
            for work_stream in sub_phase.get("workStreams") or []:
                rows.append(work_stream)
                for epic in work_stream.get("epics") or []:
                    rows.append(epic)
                    rows.extend(epic.get("levelZero") or [])
    return rows


def _sefk_rows_by_key(phases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("key") or "").strip(): row
        for row in _iter_sefk_rows(phases)
        if str(row.get("key") or "").strip()
    }


def _build_sefk_block_link_maps(phases: list[dict[str, Any]]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    blocked_by: dict[str, list[str]] = {}
    blocks: dict[str, list[str]] = {}
    for row in _iter_sefk_rows(phases):
        blocked_key = str(row.get("key") or "").strip()
        if not blocked_key:
            continue
        for blocker in row.get("blockedByKeys") or []:
            blocker_key = str(blocker or "").strip()
            if not blocker_key or blocker_key == blocked_key:
                continue
            blocked_by.setdefault(blocked_key, []).append(blocker_key)
            blocks.setdefault(blocker_key, []).append(blocked_key)

    for values in blocked_by.values():
        values[:] = list(dict.fromkeys(values))
    for values in blocks.values():
        values[:] = list(dict.fromkeys(values))
    return blocked_by, blocks


def _append_sefk_dependency_connectors(
    parts: list[str],
    *,
    edges: list[tuple[str, str]],
    row_positions: dict[str, tuple[float, float, float]],
) -> None:
    for blocker_key, blocked_key in edges:
        blocker = row_positions.get(blocker_key)
        blocked = row_positions.get(blocked_key)
        if not blocker or not blocked:
            continue

        _blocker_start, blocker_y, blocker_end = blocker
        blocked_start, blocked_y, _blocked_end = blocked
        direction = 1.0 if blocked_start >= blocker_end else -1.0
        start_x = blocker_end + (4.0 * direction)
        end_x = blocked_start - (4.0 * direction)
        control_offset = min(64.0, max(18.0, abs(end_x - start_x) * 0.45)) * direction
        path_d = (
            f"M {start_x:.1f} {blocker_y:.1f} "
            f"C {start_x + control_offset:.1f} {blocker_y:.1f}, "
            f"{end_x - control_offset:.1f} {blocked_y:.1f}, "
            f"{end_x:.1f} {blocked_y:.1f}"
        )
        tooltip = f"Dependency: {blocker_key} blocks {blocked_key}"
        parts.append(
            f'<g class="sefk-dependency-connector" data-sef-dep-from="{html.escape(blocker_key)}" '
            f'data-sef-dep-to="{html.escape(blocked_key)}">{_svg_embedded_title(tooltip)}'
            f'<path class="sefk-dependency-hit-area" d="{path_d}" stroke="transparent" stroke-width="12" fill="none"/>'
            f'<path class="sefk-dependency-path" d="{path_d}" stroke="#5e6c84" stroke-width="1.4" '
            f'stroke-linecap="round" stroke-linejoin="round" fill="none" marker-end="url(#dep-arrow)"/>'
            f'<circle class="sefk-dependency-endpoint" cx="{start_x:.1f}" cy="{blocker_y:.1f}" r="3.4" fill="#ffffff" stroke="#5e6c84" stroke-width="1.4"/>'
            f'<circle class="sefk-dependency-endpoint" cx="{end_x:.1f}" cy="{blocked_y:.1f}" r="3.4" fill="#ffffff" stroke="#5e6c84" stroke-width="1.4"/>'
            f"</g>"
        )


def _mark_sefk_special_rows(phases: list[dict[str, Any]], config: SefkProjectPlanReportingConfig) -> None:
    milestone_types = {name.casefold() for name in config.milestone_issue_types}
    gate_types = {name.casefold() for name in config.gate_issue_types}
    for row in _iter_sefk_rows(phases):
        issue_type = str(row.get("issueType") or "").strip().casefold()
        if issue_type in milestone_types or "milestone" in issue_type:
            row["isMilestone"] = True
        if issue_type in gate_types or "gate" in issue_type:
            row["isMeetingGate"] = True


def resolve_chart_window_for_phases(phases: list[dict[str, Any]]) -> tuple[date, date]:
    starts: list[date] = []
    ends: list[date] = []
    for row in _iter_sefk_rows(phases):
        start = _parse_day(str(row.get("startDate") or "")[:10])
        end = _parse_day(str(row.get("endDate") or "")[:10])
        if start:
            starts.append(start)
        if end:
            ends.append(end)
    if not starts or not ends:
        return date(2026, 6, 1), date(2027, 12, 31)
    return min(starts), max(ends)


def _merge_scope_rollups(rollups: list[dict[str, Any]]) -> dict[str, Any] | None:
    active = [rollup for rollup in rollups if float(rollup.get("totalWeight") or 0) > 0]
    if not active:
        return None
    lanes = {str(index): rollup for index, rollup in enumerate(active)}
    return aggregate_milestone_scope(lanes)


def _bubble_scope_rollups(phases: list[dict[str, Any]]) -> None:
    for phase in phases:
        for sub_phase in phase.get("subPhases") or []:
            for work_stream in sub_phase.get("workStreams") or []:
                epic_rollups = [
                    epic.get("scopeRollup")
                    for epic in work_stream.get("epics") or []
                    if isinstance(epic.get("scopeRollup"), dict)
                ]
                merged = _merge_scope_rollups(epic_rollups)
                if merged and not work_stream.get("scopeRollup"):
                    work_stream["scopeRollup"] = merged
            ws_rollups = [
                work_stream.get("scopeRollup")
                for work_stream in sub_phase.get("workStreams") or []
                if isinstance(work_stream.get("scopeRollup"), dict)
            ]
            merged_sp = _merge_scope_rollups(ws_rollups)
            if merged_sp:
                sub_phase["scopeRollup"] = merged_sp
        sp_rollups = [
            sub_phase.get("scopeRollup")
            for sub_phase in phase.get("subPhases") or []
            if isinstance(sub_phase.get("scopeRollup"), dict)
        ]
        merged_phase = _merge_scope_rollups(sp_rollups)
        if merged_phase:
            phase["scopeRollup"] = merged_phase


def _linked_epic_keys(work_stream_issue: dict[str, Any], *, epic_issue_type: str) -> list[str]:
    keys: list[str] = []
    for target in linked_scope_targets(work_stream_issue):
        itype = str(((target.get("fields") or {}).get("issuetype") or {}).get("name") or "")
        key = str(target.get("key") or "")
        if key and itype == epic_issue_type:
            keys.append(key)
    return keys


def _attach_epic_scope_rollups(
    adapter: "AtlassianAdapter",
    epic_issues: dict[str, dict[str, Any]],
    *,
    config: SefkProjectPlanReportingConfig,
) -> dict[str, dict[str, Any]]:
    if not epic_issues:
        return {}
    epic_keys = sorted(epic_issues.keys())
    child_jql = sefk_epic_scope_jql(
        parent_keys_csv=", ".join(epic_keys),
        scope_issue_types=config.scope_issue_types,
    )
    scope_fields = ["parent", "issuetype", "status"]
    children = search_all(adapter, child_jql, scope_fields)
    return rollup_sefk_epic_phases(
        children,
        epic_keys=epic_keys,
        scope_issue_types=config.scope_issue_types,
        status_map=config.status_dtrain,
        skip_issue=issue_excluded_from_sefk_project_plan,
    )


def _attach_level_zero_rows(
    adapter: "AtlassianAdapter",
    phases: list[dict[str, Any]],
    *,
    config: SefkProjectPlanReportingConfig,
    fallback_start: date,
    fallback_end: date,
) -> None:
    epics = [
        epic
        for phase in phases
        for sub_phase in phase.get("subPhases") or []
        for work_stream in sub_phase.get("workStreams") or []
        for epic in work_stream.get("epics") or []
        if str(epic.get("key") or "").strip()
    ]
    if not epics:
        return
    children = search_all(
        adapter,
        sefk_epic_scope_jql(
            parent_keys_csv=", ".join(str(epic["key"]) for epic in epics),
            scope_issue_types=config.scope_issue_types,
        ),
        ["summary", "status", "issuetype", "created", "duedate", START_DATE_FIELD, "issuelinks", "parent", "labels"],
    )
    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    for child in children:
        if issue_excluded_from_sefk_project_plan(child):
            continue
        parent_key = str((((child.get("fields") or {}).get("parent") or {}).get("key")) or "").strip()
        if parent_key:
            children_by_parent.setdefault(parent_key, []).append(child)
    for epic in epics:
        level_zero = [
            _issue_timeline_row(
                child,
                fallback_start=fallback_start,
                fallback_end=fallback_end,
                milestone_issue_types=(*config.milestone_issue_types, *config.gate_issue_types),
            )
            for child in children_by_parent.get(str(epic["key"]), [])
        ]
        level_zero.sort(key=lambda row: (str(row.get("startDate") or ""), str(row.get("key") or "")))
        epic["levelZero"] = level_zero


def _fetch_work_stream_epics(
    adapter: "AtlassianAdapter",
    config: SefkProjectPlanReportingConfig,
    *,
    work_stream_issue: dict[str, Any],
    fallback_start: date,
    fallback_end: date,
    fields: list[str],
    epic_issues: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    work_stream_key = str(work_stream_issue.get("key") or "")
    epic_rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for epic_type in (config.epic_issue_type, *config.additional_epic_types):
        for epic_issue in _fetch_children(
            adapter,
            parent_key=work_stream_key,
            issue_type=epic_type,
            fields=fields,
        ):
            epic_key = str(epic_issue.get("key") or "")
            if not epic_key or epic_key in seen:
                continue
            seen.add(epic_key)
            epic_issues[epic_key] = epic_issue
            epic_rows.append(
                _issue_timeline_row(
                    epic_issue,
                    fallback_start=fallback_start,
                    fallback_end=fallback_end,
                    milestone_issue_types=(*config.milestone_issue_types, *config.gate_issue_types),
                )
            )

    for epic_key in _linked_epic_keys(work_stream_issue, epic_issue_type=config.epic_issue_type):
        if epic_key in seen:
            continue
        epic_issue_list = search_all(adapter, f"key = {epic_key}", fields)
        if not epic_issue_list:
            continue
        epic_issue = epic_issue_list[0]
        seen.add(epic_key)
        epic_issues[epic_key] = epic_issue
        epic_rows.append(
            _issue_timeline_row(
                epic_issue,
                fallback_start=fallback_start,
                fallback_end=fallback_end,
                milestone_issue_types=(*config.milestone_issue_types, *config.gate_issue_types),
            )
        )

    epic_rows.sort(key=lambda row: (str(row.get("startDate") or ""), str(row.get("key") or "")))
    return epic_rows


def _epics_for_work_stream(
    work_stream_key: str,
    work_stream_issue: dict[str, Any],
    *,
    by_key: dict[str, dict[str, Any]],
    children_of: dict[str, list[str]],
    config: SefkProjectPlanReportingConfig,
    fallback_start: date,
    fallback_end: date,
) -> list[dict[str, Any]]:
    epic_type = {config.epic_issue_type, *config.additional_epic_types}
    epic_rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for epic_key in _child_keys_for_types(
        work_stream_key,
        children_of=children_of,
        by_key=by_key,
        issue_types=epic_type,
    ):
        if epic_key not in by_key:
            continue
        seen.add(epic_key)
        epic_rows.append(
            _issue_timeline_row(
                by_key[epic_key],
                fallback_start=fallback_start,
                fallback_end=fallback_end,
                milestone_issue_types=(*config.milestone_issue_types, *config.gate_issue_types),
            )
        )

    for epic_key in _linked_epic_keys(work_stream_issue, epic_issue_type=config.epic_issue_type):
        if epic_key in seen or epic_key not in by_key:
            continue
        seen.add(epic_key)
        epic_rows.append(
            _issue_timeline_row(
                by_key[epic_key],
                fallback_start=fallback_start,
                fallback_end=fallback_end,
                milestone_issue_types=(*config.milestone_issue_types, *config.gate_issue_types),
            )
        )

    epic_rows.sort(key=lambda row: (str(row.get("startDate") or ""), str(row.get("key") or "")))
    return epic_rows


def _build_sefk_hierarchy_from_flat(
    issues: list[dict[str, Any]],
    config: SefkProjectPlanReportingConfig,
    *,
    fallback_start: date,
    fallback_end: date,
) -> tuple[list[dict[str, Any]], list[str], list[str], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Build phase→subPhase→workStream→epic hierarchy from a flat issue list.

    Returns (phases, hub_keys, warnings, block_issues, epic_issues).
    """
    allowed_types = {
        config.phase_hub_issue_type,
        config.sub_phase_issue_type,
        config.work_stream_issue_type,
        config.epic_issue_type,
        *config.additional_epic_types,
    }
    by_key: dict[str, dict[str, Any]] = {}
    for issue in issues:
        key = str(issue.get("key") or "")
        if not key:
            continue
        if issue_has_kpmg_deleted_label(issue):
            continue
        if _issue_type_name(issue) in allowed_types:
            by_key[key] = issue

    children_of: dict[str, list[str]] = {}
    for key, issue in by_key.items():
        parent_key = ((issue.get("fields") or {}).get("parent") or {}).get("key") or ""
        children_of.setdefault(parent_key, []).append(key)

    hub_keys = _sort_sibling_keys(
        [
            key
            for key, issue in by_key.items()
            if _issue_type_name(issue) == config.phase_hub_issue_type
        ],
        by_key,
    )
    warnings: list[str] = []
    sub_phase_types = {config.sub_phase_issue_type}
    work_stream_types = {config.work_stream_issue_type}

    block_issues: dict[str, dict[str, Any]] = {}
    epic_issues: dict[str, dict[str, Any]] = {}

    def make_work_stream(key: str) -> dict[str, Any]:
        block_issues[key] = by_key[key]
        row = _issue_timeline_row(
            by_key[key],
            fallback_start=fallback_start,
            fallback_end=fallback_end,
            milestone_issue_types=(*config.milestone_issue_types, *config.gate_issue_types),
        )
        row["epics"] = _epics_for_work_stream(
            key,
            by_key[key],
            by_key=by_key,
            children_of=children_of,
            config=config,
            fallback_start=fallback_start,
            fallback_end=fallback_end,
        )
        for epic in row["epics"]:
            epic_key = str(epic.get("key") or "")
            if epic_key in by_key:
                epic_issues[epic_key] = by_key[epic_key]
        return row

    def make_sub_phase(key: str) -> dict[str, Any]:
        block_issues[key] = by_key[key]
        row = _issue_timeline_row(
            by_key[key],
            fallback_start=fallback_start,
            fallback_end=fallback_end,
            milestone_issue_types=(*config.milestone_issue_types, *config.gate_issue_types),
        )
        ws_keys = _child_keys_for_types(
            key,
            children_of=children_of,
            by_key=by_key,
            issue_types=work_stream_types,
        )
        row["workStreams"] = [
            make_work_stream(ws_key)
            for ws_key in ws_keys
            if ws_key in by_key and _issue_type_name(by_key[ws_key]) in work_stream_types
        ]
        return row

    phases: list[dict[str, Any]] = []
    for hub_key in hub_keys:
        block_issues[hub_key] = by_key[hub_key]
        phase_row = _issue_timeline_row(
            by_key[hub_key],
            fallback_start=fallback_start,
            fallback_end=fallback_end,
            milestone_issue_types=(*config.milestone_issue_types, *config.gate_issue_types),
        )
        sub_phase_keys = _child_keys_for_types(
            hub_key,
            children_of=children_of,
            by_key=by_key,
            issue_types=sub_phase_types,
        )
        sub_phase_keys = _sort_sub_phase_sibling_keys(sub_phase_keys, by_key, config.sub_phase_order)
        phase_row["subPhases"] = [
            make_sub_phase(sp_key)
            for sp_key in sub_phase_keys
            if sp_key in by_key and _issue_type_name(by_key[sp_key]) in sub_phase_types
        ]
        phases.append(phase_row)

    if not phases:
        warnings.append(
            f"Scope filter returned no {config.phase_hub_issue_type} (phase hub) issues."
        )
    return phases, hub_keys, warnings, block_issues, epic_issues


def _attach_rollups_to_phases(
    adapter: "AtlassianAdapter",
    phases: list[dict[str, Any]],
    *,
    config: SefkProjectPlanReportingConfig,
    block_issues: dict[str, dict[str, Any]],
    epic_issues: dict[str, dict[str, Any]],
) -> None:
    epic_rollups = _attach_epic_scope_rollups(
        adapter,
        epic_issues,
        config=config,
    )
    for phase in phases:
        for sub_phase in phase.get("subPhases") or []:
            for work_stream in sub_phase.get("workStreams") or []:
                for epic in work_stream.get("epics") or []:
                    epic_key = str(epic.get("key") or "")
                    rollup = epic_rollups.get(epic_key)
                    if rollup and float(rollup.get("totalWeight") or 0) > 0:
                        epic["scopeRollup"] = rollup

    story_points_field = field_aliases()["Story Points"]
    scope_rollups = build_block_scope_rollups(
        adapter,
        block_issues=block_issues,
        story_points_field=story_points_field,
        skip_issue=issue_excluded_from_sefk_project_plan,
    )
    for phase in phases:
        phase_key = str(phase.get("key") or "")
        if phase_key in scope_rollups:
            phase["scopeRollup"] = scope_rollups[phase_key]
        for sub_phase in phase.get("subPhases") or []:
            sub_phase_key = str(sub_phase.get("key") or "")
            if sub_phase_key in scope_rollups:
                sub_phase["scopeRollup"] = scope_rollups[sub_phase_key]
            for work_stream in sub_phase.get("workStreams") or []:
                work_stream_key = str(work_stream.get("key") or "")
                if work_stream_key in scope_rollups and not work_stream.get("scopeRollup"):
                    work_stream["scopeRollup"] = scope_rollups[work_stream_key]

    _bubble_scope_rollups(phases)


def _fetch_sefk_via_phase_hubs(
    adapter: "AtlassianAdapter",
    config: SefkProjectPlanReportingConfig,
    *,
    fields: list[str],
    scope_fields: list[str],
    fallback_start: date,
    fallback_end: date,
) -> tuple[list[dict[str, Any]], list[str], list[str], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    hub_issues, hub_warnings = discover_phase_hub_issues(adapter, config, fields=fields)
    phases: list[dict[str, Any]] = []
    block_issues: dict[str, dict[str, Any]] = {}
    epic_issues: dict[str, dict[str, Any]] = {}

    for hub in hub_issues:
        hub_key = str(hub.get("key") or "")
        if not hub_key:
            continue
        block_issues[hub_key] = hub
        phase_row = _issue_timeline_row(
            hub,
            fallback_start=fallback_start,
            fallback_end=fallback_end,
            milestone_issue_types=(*config.milestone_issue_types, *config.gate_issue_types),
        )
        sub_phases_raw = _fetch_children(
            adapter,
            parent_key=hub_key,
            issue_type=config.sub_phase_issue_type,
            fields=scope_fields,
        )
        sub_phases_raw = _sort_sub_phase_issues(sub_phases_raw, config.sub_phase_order)
        sub_phases: list[dict[str, Any]] = []
        for sub_phase_issue in sub_phases_raw:
            sub_phase_key = str(sub_phase_issue.get("key") or "")
            block_issues[sub_phase_key] = sub_phase_issue
            sub_phase_row = _issue_timeline_row(
                sub_phase_issue,
                fallback_start=fallback_start,
                fallback_end=fallback_end,
                milestone_issue_types=(*config.milestone_issue_types, *config.gate_issue_types),
            )
            work_streams_raw = _fetch_children(
                adapter,
                parent_key=sub_phase_key,
                issue_type=config.work_stream_issue_type,
                fields=scope_fields,
            )
            work_streams_raw = sorted(work_streams_raw, key=_issue_start_sort_key)
            work_streams: list[dict[str, Any]] = []
            for work_stream_issue in work_streams_raw:
                work_stream_key = str(work_stream_issue.get("key") or "")
                block_issues[work_stream_key] = work_stream_issue
                work_stream_row = _issue_timeline_row(
                    work_stream_issue,
                    fallback_start=fallback_start,
                    fallback_end=fallback_end,
                    milestone_issue_types=(*config.milestone_issue_types, *config.gate_issue_types),
                )
                work_stream_row["epics"] = _fetch_work_stream_epics(
                    adapter,
                    config,
                    work_stream_issue=work_stream_issue,
                    fallback_start=fallback_start,
                    fallback_end=fallback_end,
                    fields=scope_fields,
                    epic_issues=epic_issues,
                )
                work_streams.append(work_stream_row)
            sub_phase_row["workStreams"] = work_streams
            sub_phases.append(sub_phase_row)
        phase_row["subPhases"] = sub_phases
        phases.append(phase_row)

    return phases, [str(issue.get("key") or "") for issue in hub_issues if issue.get("key")], hub_warnings, block_issues, epic_issues


def fetch_sefk_project_plan_timeline(
    adapter: "AtlassianAdapter",
    config: SefkProjectPlanReportingConfig,
) -> dict[str, Any]:
    fallback_start = date.fromisoformat(config.chart_window_start)
    fallback_end = date.fromisoformat(config.chart_window_end)
    fields = [
        "summary",
        "status",
        "issuetype",
        "created",
        "duedate",
        START_DATE_FIELD,
        RUN_ORDER_FIELD,
        "issuelinks",
        "parent",
    ]
    scope_fields = [*fields]

    scope_filter_jql = resolve_scope_filter_jql(adapter, config)
    warnings: list[str] = []
    hub_keys: list[str] = []

    if scope_filter_jql:
        scope_filter_jql = (
            f"project = {config.project_key} AND ({scope_filter_jql}) "
            f"AND {sefk_scope_exclusion_jql()}"
        )
        all_issues = search_all(adapter, scope_filter_jql, scope_fields)
        phases, hub_keys, build_warnings, block_issues, epic_issues = _build_sefk_hierarchy_from_flat(
            all_issues,
            config,
            fallback_start=fallback_start,
            fallback_end=fallback_end,
        )
        warnings.extend(build_warnings)
    else:
        phases, hub_keys, hub_warnings, block_issues, epic_issues = _fetch_sefk_via_phase_hubs(
            adapter,
            config,
            fields=fields,
            scope_fields=scope_fields,
            fallback_start=fallback_start,
            fallback_end=fallback_end,
        )
        warnings.extend(hub_warnings)

    _attach_level_zero_rows(
        adapter,
        phases,
        config=config,
        fallback_start=fallback_start,
        fallback_end=fallback_end,
    )
    _mark_sefk_special_rows(phases, config)

    _attach_rollups_to_phases(
        adapter,
        phases,
        config=config,
        block_issues=block_issues,
        epic_issues=epic_issues,
    )
    window_start, window_end = resolve_chart_window_for_phases(phases)
    return {
        "projectKey": config.project_key,
        "pageTitle": config.page_title,
        "scopeFilterName": config.scope_filter_name,
        "chartWindowStart": window_start.isoformat(),
        "chartWindowEnd": window_end.isoformat(),
        "phaseHubKeys": hub_keys,
        "phases": phases,
        "warnings": warnings,
        "statusDtrain": dict(config.status_dtrain),
    }


def _sub_phase_block_height(sub_phase: dict[str, Any]) -> float:
    height = BLOCK_PAD_Y * 2 + SUB_PHASE_ROW_HEIGHT
    for work_stream in sub_phase.get("workStreams") or []:
        height += WORK_STREAM_ROW_HEIGHT + len(work_stream.get("epics") or []) * EPIC_ROW_HEIGHT
    return height


def _sefk_scope_has_story_points(scope: dict[str, Any]) -> bool:
    return float(scope.get("storyPoints") or 0) > 0


def _sefk_status_bar_fill(row: dict[str, Any], *, status_map: dict[str, str] | None = None) -> str:
    phase = resolve_sefk_issue_dtrain_phase(str(row.get("status") or ""), status_map=status_map)
    return DTRAIN_PHASE_FILL.get(phase, DTRAIN_PHASE_FILL.get("Unknown", "#c1c7d0"))


def _sefk_bar_fill(row: dict[str, Any], *, status_map: dict[str, str] | None = None) -> str:
    scope = row.get("scopeRollup")
    if isinstance(scope, dict) and _sefk_scope_has_story_points(scope):
        return DTRAIN_BASE_FILL
    return _sefk_status_bar_fill(row, status_map=status_map)


def _sefk_render_scope_overlay(row: dict[str, Any]) -> bool:
    scope = row.get("scopeRollup")
    return isinstance(scope, dict) and _sefk_scope_has_story_points(scope)


def sefk_dtrain_key_html() -> str:
    phase_items = []
    for phase in chart_dtrain_phases():
        phase_items.append(
            f'<span class="chart-key-phase-item">'
            f'<span class="legend-swatch" style="background:{DTRAIN_PHASE_FILL[phase]}"></span>'
            f"{html.escape(phase)}</span>"
        )
    return (
        '<div class="chart-key chart-key--dtrain">'
        '<p class="chart-key-title"><strong>Key</strong></p>'
        '<div class="chart-key-row">'
        '<span class="legend-swatch" style="background:#0052cc;opacity:0.85"></span> '
        "Schedule window (start date through due date)"
        "</div>"
        '<div class="chart-key-row">'
        "Scope bars: D-Train phases left to right with "
        '<span class="legend-swatch" style="background:#00875a"></span> Drive '
        "through "
        '<span class="legend-swatch" style="background:#de350b"></span> Dream '
        "(matches milestone report palette)"
        "</div>"
        f'<div class="chart-key-phase-strip">{"".join(phase_items)}</div>'
        f'<div class="chart-key-row">'
        f"Items without scoped Story Points use a solid bar coloured by their Jira status "
        f"(mapped to D-Train phase above)."
        f"</div>"
        '<div class="chart-key-row">'
        '<span class="legend-swatch" style="background:#de350b;border-radius:50%"></span> '
        "Alert: overdue and not completed, or starts before its predecessor finishes &nbsp; "
        '<span class="legend-swatch" style="background:#ffab00;border-radius:50%"></span> '
        "Warning: not started and its start date has passed &nbsp; "
        '<span class="legend-swatch" style="background:#00875a;border-radius:50%"></span> '
        "On track. Parents show the worst badge among their children; hover a parent to see the "
        "breakdown."
        "</div>"
        "</div>"
    )


def sefk_project_plan_timeline_svg(payload: dict[str, Any]) -> str:
    phases = payload.get("phases") or []
    if not phases:
        return '<p class="footnote">No phases. Run fetch_sefk_project_plan_timeline.py --write.</p>'

    status_map = dict(payload.get("statusDtrain") or {})
    blocked_by, blocks = _build_sefk_block_link_maps(phases)
    rows_by_key = _sefk_rows_by_key(phases)
    dependency_edges = [
        (blocker_key, blocked_key)
        for blocked_key, blocker_keys in blocked_by.items()
        for blocker_key in blocker_keys
    ]
    row_positions: dict[str, tuple[float, float, float]] = {}
    parent_by_key: dict[str, str] = {}
    pill_clip_ids = count(1)

    def _append_sefk_bar(
        parts_list: list[str],
        *,
        row: dict[str, Any],
        role: str,
        x1: float,
        bar_y: float,
        bar_w: float,
        bar_h: float,
    ) -> None:
        render_overlay = _sefk_render_scope_overlay(row) and not _is_milestone_row(row)
        rx = max(4, int(bar_h / 2))
        clip_id = ""
        if render_overlay:
            # Clip the striped D-Train segments to the bar's own pill outline so they
            # don't poke out past the rounded ends as square corners.
            clip_id = f"sefk-pill-clip-{next(pill_clip_ids)}"
            parts_list.append(
                f'<clipPath id="{clip_id}"><rect x="{x1:.1f}" y="{bar_y:.1f}" width="{bar_w:.1f}" '
                f'height="{bar_h:.1f}" rx="{rx}"/></clipPath>'
            )
            parts_list.append(f'<g class="sefk-pill-clip-wrap" clip-path="url(#{clip_id})">')
        _append_timeline_bar(
            parts_list,
            row=row,
            x1=x1,
            bar_y=bar_y,
            bar_w=bar_w,
            bar_h=bar_h,
            fill=_sefk_bar_fill(row, status_map=status_map),
            opacity=BAR_OPACITY,
            role=role,
            rx=rx,
            scope_overlay_opacity=SCOPE_OVERLAY_OPACITY,
            blocked_by_keys=blocked_by.get(str(row.get("key") or ""), []),
            blocks_keys=blocks.get(str(row.get("key") or ""), []),
            rows_by_key=rows_by_key,
            render_scope_overlay=render_overlay,
            render_dependency_icon=False,
        )
        if render_overlay:
            parts_list.append("</g>")

    x_min, x_max = resolve_chart_window_for_phases(phases)
    span_days = max((x_max - x_min).days, 1)
    px_per_day = EPIC_CHART_PX_PER_DAY
    plot_width = max(
        QUARTERLY_REPORT_MIN_PLOT_WIDTH,
        min(int(span_days * px_per_day), QUARTERLY_REPORT_MAX_SVG_WIDTH),
    )
    plot_left = _sefk_label_column_width(phases)
    plot_right = plot_left + plot_width
    svg_width = plot_right + RIGHT_PAD

    plot_height = 0.0
    for phase_index, phase in enumerate(phases):
        if phase_index > 0:
            plot_height += PHASE_GAP
        plot_height += PHASE_ROW_HEIGHT
        for sub_phase_index, sub_phase in enumerate(phase.get("subPhases") or []):
            if sub_phase_index > 0:
                plot_height += BLOCK_GAP
            plot_height += _sub_phase_block_height(sub_phase)

    calendar_top = CALENDAR_TOP
    plot_top = calendar_top + 28
    plot_bottom = plot_top + plot_height
    bottom_margin = _svg_x_bottom_margin()
    svg_height = plot_bottom + bottom_margin

    def x_for(day: date) -> float:
        return plot_left + ((day - x_min).days / span_days) * plot_width

    grid_specs = _week_month_grid_line_specs(x_min=x_min, x_max=x_max, x_for=x_for)

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_width:.0f}" '
        f'height="{svg_height:.0f}" viewBox="0 0 {svg_width:.0f} {svg_height:.0f}">',
        "<defs>",
        f'<clipPath id="sef-plan-label-col">'
        f'<rect x="0" y="{plot_top:.1f}" width="{plot_left - 8:.1f}" height="{plot_height:.1f}"/>'
        f"</clipPath>",
        f'<clipPath id="sef-plan-label-col-x">'
        f'<rect x="0" y="-10000" width="{plot_left - 8:.1f}" height="20000"/>'
        f"</clipPath>",
        f'<marker id="dep-arrow" markerWidth="8" markerHeight="8" refX="8" refY="4" orient="auto" markerUnits="userSpaceOnUse">'
        f'<path d="M 0 0 L 8 4 L 0 8 z" fill="#5e6c84"/>'
        f"</marker>",
        "</defs>",
    ]
    parts.append(
        f'<line x1="{plot_left:.1f}" y1="{plot_top:.1f}" x2="{plot_right:.1f}" y2="{plot_top:.1f}" '
        f'stroke="{ATL["line"]}" stroke-width="1"/>'
    )
    _svg_week_month_grid_lines(
        parts,
        specs=grid_specs,
        plot_top=plot_top,
        plot_bottom=plot_bottom,
    )

    y_cursor = plot_top
    sub_phase_manifest: list[dict[str, Any]] = []
    for phase_index, phase in enumerate(phases):
        if phase_index > 0:
            y_cursor += PHASE_GAP
            parts.append(
                f'<rect x="0" y="{y_cursor - PHASE_GAP / 2:.1f}" width="{plot_right:.1f}" '
                f'height="{PHASE_GAP:.1f}" fill="{ATL["page"]}"/>'
            )

        phase_key = str(phase.get("key") or "")
        phase_label = str(phase.get("summary") or phase_key)
        phase_start = date.fromisoformat(str(phase.get("startDate"))[:10])
        phase_end = date.fromisoformat(str(phase.get("endDate"))[:10])
        phase_row_cy = y_cursor + PHASE_ROW_HEIGHT / 2
        phase_x1 = x_for(phase_start)
        phase_x2 = x_for(phase_end)
        phase_bar_w = max(phase_x2 - phase_x1, 2.0)
        phase_bar_y = y_cursor + (PHASE_ROW_HEIGHT - PHASE_BAR_HEIGHT) / 2

        if phase_key:
            parent_by_key[phase_key] = ""
            _append_sefk_bar(
                parts,
                row=phase,
                x1=phase_x1,
                bar_y=phase_bar_y,
                bar_w=phase_bar_w,
                bar_h=PHASE_BAR_HEIGHT,
                role="phase-bar",
            )
            row_positions[phase_key] = (phase_x1, phase_row_cy, phase_x1 + phase_bar_w)
            _append_sefk_issue_type_icon(
                parts,
                row=phase,
                x=SEFK_PHASE_LABEL_X - 11,
                y_center=phase_row_cy,
            )
            _append_label_link(
                parts,
                text=_label_with_duration_metrics(phase_label, phase),
                x=SEFK_PHASE_LABEL_X,
                y_center=phase_row_cy,
                url=f"{JIRA_SERVER}/browse/{html.escape(phase_key)}",
                tooltip=_bar_tooltip(phase),
                font_size=13,
                font_weight="700",
                row_key=phase_key,
            )
        y_cursor += PHASE_ROW_HEIGHT

        for sub_phase_index, sub_phase in enumerate(phase.get("subPhases") or []):
            if sub_phase_index > 0:
                y_cursor += BLOCK_GAP
            block_h = _sub_phase_block_height(sub_phase)
            block_y = y_cursor
            y0 = block_y + BLOCK_PAD_Y
            row_cy = y0 + SUB_PHASE_ROW_HEIGHT / 2
            sub_phase_key = str(sub_phase.get("key") or "")
            sub_phase_label = str(sub_phase.get("summary") or sub_phase_key)
            work_streams = sub_phase.get("workStreams") or []
            has_work_streams = bool(work_streams)
            ws_keys = [str(ws.get("key") or "") for ws in work_streams if str(ws.get("key") or "")]
            sub_content_h = max(0, int(block_h - BLOCK_PAD_Y * 2 - SUB_PHASE_ROW_HEIGHT))
            collapsed_h = int(BLOCK_PAD_Y * 2 + SUB_PHASE_ROW_HEIGHT)

            if sub_phase_key:
                parent_by_key[sub_phase_key] = phase_key
                parts.append(
                    f'<g id="sefk-sp-{html.escape(sub_phase_key)}" transform="translate(0,0)" '
                    f'data-sub-h="{sub_content_h}" data-collapsed-h="{collapsed_h}">'
                )
                parts.append(
                    f'<rect id="sefk-bd-{html.escape(sub_phase_key)}" '
                    f'x="0" y="{block_y:.1f}" width="{plot_right:.1f}" height="{block_h:.1f}" '
                    f'data-sef-key="{html.escape(sub_phase_key)}" data-sef-row="1" '
                    f'data-sef-role="sub-phase-border" data-sef-orig-y="{block_y:.1f}" '
                    f'data-sef-orig-height="{block_h:.1f}" '
                    f'fill="none" stroke="{ATL["ink"]}" stroke-width="{BLOCK_BORDER_WIDTH}"/>'
                )
                start_day = date.fromisoformat(str(sub_phase.get("startDate"))[:10])
                end_day = date.fromisoformat(str(sub_phase.get("endDate"))[:10])
                x1 = x_for(start_day)
                x2 = x_for(end_day)
                bar_w = max(x2 - x1, 2.0)
                bar_y = y0 + (SUB_PHASE_ROW_HEIGHT - SUB_PHASE_BAR_HEIGHT) / 2
                _append_sefk_bar(
                    parts,
                    row=sub_phase,
                    x1=x1,
                    bar_y=bar_y,
                    bar_w=bar_w,
                    bar_h=SUB_PHASE_BAR_HEIGHT,
                    role="sub-phase-bar",
                )
                row_positions[sub_phase_key] = (x1, row_cy, x1 + bar_w)
                _append_sefk_issue_type_icon(
                    parts,
                    row=sub_phase,
                    x=SEFK_SUB_PHASE_LABEL_X - 11,
                    y_center=row_cy,
                )
                _append_label_link(
                    parts,
                    text=_label_with_duration_metrics(sub_phase_label, sub_phase),
                    x=SEFK_SUB_PHASE_LABEL_X,
                    y_center=row_cy,
                    url=f"{JIRA_SERVER}/browse/{html.escape(sub_phase_key)}",
                    tooltip=_bar_tooltip(sub_phase),
                    font_weight="600",
                    row_key=sub_phase_key,
                )
                if has_work_streams:
                    chev_x = SEFK_SUB_PHASE_LABEL_X - 24
                    parts.append(
                        f'<text id="sefk-chev-sp-{html.escape(sub_phase_key)}" '
                        f'data-sef-key="{html.escape(sub_phase_key)}" data-sef-row="1" '
                        f'x="{chev_x:.1f}" y="{row_cy + 4:.1f}" '
                        f'font-family="{SVG_FONT}" font-size="10" fill="{ATL["ink"]}" '
                        f'style="cursor:pointer;user-select:none" text-anchor="end" '
                        f'onclick="sefkToggleSubPhase(event,&apos;{html.escape(sub_phase_key)}&apos;)">'
                        f"&#x25BC;</text>"
                    )
                    parts.append(
                        f'<g id="sefk-sub-sp-{html.escape(sub_phase_key)}" '
                        f'transform="translate(0,{block_y:.1f})" '
                        f'data-work-stream-keys="{html.escape(",".join(ws_keys))}">'
                    )

            ws_cursor = BLOCK_PAD_Y + SUB_PHASE_ROW_HEIGHT
            for work_stream in work_streams:
                work_stream_key = str(work_stream.get("key") or "")
                work_stream_label = str(work_stream.get("summary") or work_stream_key)
                epics = work_stream.get("epics") or []
                epic_h = len(epics) * EPIC_ROW_HEIGHT
                ws_rel_y = ws_cursor
                ws_bar_y_rel = (WORK_STREAM_ROW_HEIGHT - WORK_STREAM_BAR_HEIGHT) / 2
                ws_row_cy_rel = WORK_STREAM_ROW_HEIGHT / 2
                ws_start = date.fromisoformat(str(work_stream.get("startDate"))[:10])
                ws_end = date.fromisoformat(str(work_stream.get("endDate"))[:10])
                wx1 = x_for(ws_start)
                wx2 = x_for(ws_end)
                ws_bar_w = max(wx2 - wx1, 2.0)
                sub_cy = block_y + ws_rel_y + ws_row_cy_rel

                if sub_phase_key and work_stream_key:
                    parts.append(
                        f'<g id="sefk-ws-{html.escape(work_stream_key)}" '
                        f'transform="translate(0,{ws_rel_y:.1f})" '
                        f'data-epic-h="{int(epic_h)}" data-sp-key="{html.escape(sub_phase_key)}">'
                    )

                bar_y = (block_y + ws_rel_y + ws_bar_y_rel) if not (sub_phase_key and work_stream_key) else ws_bar_y_rel
                _append_sefk_bar(
                    parts,
                    row=work_stream,
                    x1=wx1,
                    bar_y=bar_y,
                    bar_w=ws_bar_w,
                    bar_h=WORK_STREAM_BAR_HEIGHT,
                    role="work-stream-bar",
                )
                if work_stream_key:
                    parent_by_key[work_stream_key] = sub_phase_key
                    row_positions[work_stream_key] = (wx1, sub_cy, wx1 + ws_bar_w)
                ws_display = _sefk_work_stream_display_label(work_stream, sub_phase)
                if work_stream_key:
                    label_y = ws_row_cy_rel if (sub_phase_key and work_stream_key) else sub_cy
                    _append_sefk_issue_type_icon(
                        parts,
                        row=work_stream,
                        x=SEFK_WORK_STREAM_LABEL_X - 11,
                        y_center=label_y,
                    )
                    if epics:
                        chev_ws_x = SEFK_WORK_STREAM_LABEL_X - 24
                        chev_ws_y = (ws_row_cy_rel + 4) if (sub_phase_key and work_stream_key) else (sub_cy + 4)
                        parts.append(
                            f'<text id="sefk-chev-ws-{html.escape(work_stream_key)}" '
                            f'data-sef-key="{html.escape(work_stream_key)}" data-sef-row="1" '
                            f'x="{chev_ws_x:.1f}" y="{chev_ws_y:.1f}" '
                            f'font-family="{SVG_FONT}" font-size="9" fill="{ATL["ink"]}" '
                            f'style="cursor:pointer;user-select:none" text-anchor="end" '
                            f'onclick="sefkToggleWorkStream(event,&apos;{html.escape(work_stream_key)}&apos;)">'
                            f"&#x25BC;</text>"
                        )
                    ws_label_text = _sefk_truncate_label(
                        _label_with_duration_metrics(ws_display, work_stream),
                        SEFK_WORK_STREAM_LABEL_MAX_CHARS,
                    )
                    _append_label_link(
                        parts,
                        text=ws_label_text,
                        x=SEFK_WORK_STREAM_LABEL_X,
                        y_center=label_y,
                        url=f"{JIRA_SERVER}/browse/{html.escape(work_stream_key)}",
                        tooltip=_bar_tooltip(work_stream),
                        font_size=11,
                        clip_path="sef-plan-label-col-x" if (sub_phase_key and work_stream_key) else "sef-plan-label-col",
                        row_key=work_stream_key,
                    )
                else:
                    _append_label_text(
                        parts,
                        text=_sefk_truncate_label(
                            _label_with_duration_metrics(ws_display, work_stream),
                            SEFK_WORK_STREAM_LABEL_MAX_CHARS,
                        ),
                        x=SEFK_WORK_STREAM_LABEL_X,
                        y_center=sub_cy,
                        tooltip=_bar_tooltip(work_stream),
                        font_size=11,
                    )

                if epics and sub_phase_key and work_stream_key:
                    parts.append(f'<g id="sefk-sub-ws-{html.escape(work_stream_key)}">')

                epic_cursor = WORK_STREAM_ROW_HEIGHT
                for epic in epics:
                    epic_key = str(epic.get("key") or "")
                    epic_label = str(epic.get("summary") or epic_key)
                    level_zero = epic.get("levelZero") or []
                    epic_rel_y = epic_cursor
                    epic_bar_y_rel = epic_rel_y + (EPIC_ROW_HEIGHT - EPIC_BAR_HEIGHT) / 2
                    epic_cy_rel = epic_rel_y + EPIC_ROW_HEIGHT / 2
                    epic_cy = epic_cy_rel if (sub_phase_key and work_stream_key) else (block_y + ws_rel_y + epic_cy_rel)
                    epic_start = date.fromisoformat(str(epic.get("startDate"))[:10])
                    epic_end = date.fromisoformat(str(epic.get("endDate"))[:10])
                    ex1 = x_for(epic_start)
                    ex2 = x_for(epic_end)
                    epic_bar_w = max(ex2 - ex1, 2.0)
                    epic_bar_y = epic_bar_y_rel if (sub_phase_key and work_stream_key) else (block_y + ws_rel_y + epic_bar_y_rel)
                    if epic_key:
                        level_zero_total_h = len(level_zero) * LEVEL_ZERO_ROW_HEIGHT
                        parts.append(
                            f'<g id="sefk-epic-{html.escape(epic_key)}" class="sefk-epic-row" '
                            f'data-epic-key="{html.escape(epic_key)}" transform="translate(0,0)" '
                            f'data-level-zero-h="{level_zero_total_h}" '
                            f'data-level-zero-base-h="{level_zero_total_h}">'
                        )
                    _append_sefk_bar(
                        parts,
                        row=epic,
                        x1=ex1,
                        bar_y=epic_bar_y,
                        bar_w=epic_bar_w,
                        bar_h=EPIC_BAR_HEIGHT,
                        role="epic-bar",
                    )
                    if epic_key:
                        parent_by_key[epic_key] = work_stream_key
                        row_positions[epic_key] = (
                            ex1,
                            block_y + ws_rel_y + epic_cy_rel,
                            ex1 + epic_bar_w,
                        )
                    if epic_key:
                        _append_sefk_issue_type_icon(
                            parts,
                            row=epic,
                            x=SEFK_EPIC_LABEL_X - 10,
                            y_center=epic_cy,
                            size=11.0,
                        )
                        _append_label_link(
                            parts,
                            text=_sefk_truncate_label(epic_label, SEFK_EPIC_LABEL_MAX_CHARS),
                            x=SEFK_EPIC_LABEL_X,
                            y_center=epic_cy,
                            url=f"{JIRA_SERVER}/browse/{html.escape(epic_key)}",
                            tooltip=_bar_tooltip(epic),
                            font_size=10,
                            clip_path="sef-plan-label-col-x" if (sub_phase_key and work_stream_key) else "sef-plan-label-col",
                            row_key=epic_key,
                        )

                    if level_zero and epic_key:
                        chev_epic_x = SEFK_EPIC_LABEL_X - 24
                        parts.append(
                            f'<text id="sefk-chev-epic-{html.escape(epic_key)}" '
                            f'data-sef-key="{html.escape(epic_key)}" data-sef-row="1" '
                            f'x="{chev_epic_x:.1f}" y="{epic_cy + 4:.1f}" '
                            f'font-family="{SVG_FONT}" font-size="8" fill="{ATL["ink"]}" '
                            f'style="cursor:pointer;user-select:none" text-anchor="end" '
                            f'onclick="sefkToggleEpic(event,&apos;{html.escape(epic_key)}&apos;)">'
                            f"&#x25B6;</text>"
                        )
                        parts.append(
                            f'<g id="sefk-sub-epic-{html.escape(epic_key)}" visibility="hidden" style="display:none">'
                        )

                    for level_zero_index, level_zero in enumerate(level_zero):
                        level_zero_key = str(level_zero.get("key") or "")
                        level_zero_label = str(level_zero.get("summary") or level_zero_key)
                        level_zero_rel_y = epic_rel_y + EPIC_ROW_HEIGHT + level_zero_index * LEVEL_ZERO_ROW_HEIGHT
                        level_zero_bar_y_rel = level_zero_rel_y + (LEVEL_ZERO_ROW_HEIGHT - LEVEL_ZERO_BAR_HEIGHT) / 2
                        level_zero_cy_rel = level_zero_rel_y + LEVEL_ZERO_ROW_HEIGHT / 2
                        level_zero_cy = level_zero_cy_rel if (sub_phase_key and work_stream_key) else (block_y + ws_rel_y + level_zero_cy_rel)
                        level_zero_start = date.fromisoformat(str(level_zero.get("startDate"))[:10])
                        level_zero_end = date.fromisoformat(str(level_zero.get("endDate"))[:10])
                        level_zero_x1 = x_for(level_zero_start)
                        level_zero_x2 = x_for(level_zero_end)
                        level_zero_bar_w = max(level_zero_x2 - level_zero_x1, 2.0)
                        level_zero_bar_y = level_zero_bar_y_rel if (sub_phase_key and work_stream_key) else (block_y + ws_rel_y + level_zero_bar_y_rel)
                        parts.append(
                            f'<g class="sefk-level-zero-row" data-epic-key="{html.escape(epic_key)}" '
                            f'data-level-zero-key="{html.escape(level_zero_key)}" transform="translate(0,0)">'
                        )
                        _append_sefk_bar(
                            parts,
                            row=level_zero,
                            x1=level_zero_x1,
                            bar_y=level_zero_bar_y,
                            bar_w=level_zero_bar_w,
                            bar_h=LEVEL_ZERO_BAR_HEIGHT,
                            role="level-zero-bar",
                        )
                        if level_zero_key:
                            parent_by_key[level_zero_key] = epic_key
                            row_positions[level_zero_key] = (
                                level_zero_x1,
                                block_y + ws_rel_y + level_zero_cy_rel,
                                level_zero_x1 + level_zero_bar_w,
                            )
                            _append_sefk_issue_type_icon(
                                parts,
                                row=level_zero,
                                x=SEFK_LEVEL_ZERO_LABEL_X - 9,
                                y_center=level_zero_cy,
                                size=10.0,
                            )
                            _append_label_link(
                                parts,
                                text=_sefk_truncate_label(level_zero_label, SEFK_EPIC_LABEL_MAX_CHARS),
                                x=SEFK_LEVEL_ZERO_LABEL_X,
                                y_center=level_zero_cy,
                                url=f"{JIRA_SERVER}/browse/{html.escape(level_zero_key)}",
                                tooltip=_bar_tooltip(level_zero),
                                font_size=9,
                                clip_path="sef-plan-label-col-x" if (sub_phase_key and work_stream_key) else "sef-plan-label-col",
                                row_key=level_zero_key,
                            )
                        parts.append("</g>")

                    if level_zero and epic_key:
                        parts.append("</g>")
                    if epic_key:
                        parts.append("</g>")
                    epic_cursor += EPIC_ROW_HEIGHT

                if epics and sub_phase_key and work_stream_key:
                    parts.append("</g>")
                if sub_phase_key and work_stream_key:
                    parts.append("</g>")
                ws_cursor += WORK_STREAM_ROW_HEIGHT + epic_h

            if sub_phase_key:
                if has_work_streams:
                    parts.append("</g>")
                sub_phase_manifest.append(
                    {
                        "key": sub_phase_key,
                        "subH": sub_content_h,
                        "baseSubH": sub_content_h,
                        "collapsedH": collapsed_h,
                    }
                )
                parts.append("</g>")

            y_cursor += block_h

    _append_sefk_dependency_connectors(
        parts,
        edges=dependency_edges,
        row_positions=row_positions,
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

    parts.append('<g id="sefk-x-axis" data-offset-y="0">')
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

    _svg_week_month_grid_config_element(
        parts,
        specs=grid_specs,
        plot_top=plot_top,
        plot_bottom=plot_bottom,
        plot_left=plot_left,
        plot_right=plot_right,
    )

    if sub_phase_manifest:
        manifest_str = json.dumps(sub_phase_manifest).replace('"', "&quot;")
        parts.append(
            f'<text id="sefk-cm-sp" data-chapters="{manifest_str}" '
            f'visibility="hidden" fill="none">.</text>'
        )

    parent_map_str = json.dumps(parent_by_key).replace('"', "&quot;")
    status_dtrain_str = json.dumps(status_map).replace('"', "&quot;")
    parts.append(
        f'<text id="sefk-cfg" data-block-pad-y="{BLOCK_PAD_Y}" '
        f'data-sub-phase-row-h="{SUB_PHASE_ROW_HEIGHT}" '
        f'data-work-stream-row-h="{WORK_STREAM_ROW_HEIGHT}" '
        f'data-epic-row-h="{EPIC_ROW_HEIGHT}" '
        f'data-level-zero-row-h="{LEVEL_ZERO_ROW_HEIGHT}" '
        f'data-parent-map="{parent_map_str}" '
        f'data-status-dtrain-map="{status_dtrain_str}" '
        f'visibility="hidden" fill="none">.</text>'
    )

    parts.append("</svg>")
    return "".join(parts)


def build_sefk_project_plan_report_html(
    payload: dict[str, Any],
    *,
    generated_on: str,
    page_title: str | None = None,
    breadcrumb_nav: str = "",
) -> str:
    title = page_title or str(payload.get("pageTitle") or "SEFK | Integrated Project Plan")
    chart = sefk_project_plan_timeline_svg(payload)
    window_start = str(payload.get("chartWindowStart") or "")[:10]
    window_end = str(payload.get("chartWindowEnd") or "")[:10]
    sub_phase_count = sum(len(phase.get("subPhases") or []) for phase in payload.get("phases") or [])
    work_stream_count = sum(
        len(sub_phase.get("workStreams") or [])
        for phase in payload.get("phases") or []
        for sub_phase in phase.get("subPhases") or []
    )
    epic_count = sum(
        len(work_stream.get("epics") or [])
        for phase in payload.get("phases") or []
        for sub_phase in phase.get("subPhases") or []
        for work_stream in sub_phase.get("workStreams") or []
    )
    level_zero_count = sum(
        len(epic.get("levelZero") or [])
        for phase in payload.get("phases") or []
        for sub_phase in phase.get("subPhases") or []
        for work_stream in sub_phase.get("workStreams") or []
        for epic in work_stream.get("epics") or []
    )
    footnote = (
        f"{sub_phase_count} sub-phases, {work_stream_count} work streams, {epic_count} epics, and {level_zero_count} Level 0 items "
        f"from SEFK schedule items ({window_start} to {window_end}). "
        "Each bar runs from start date through due date. "
        "Bar colours show D-Train scope composition (Drive left, Dream right). "
        "Use ▼ beside sub-phases and work streams to collapse or expand rows."
    )
    nav_block = f"\n      {breadcrumb_nav}" if breadcrumb_nav else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html.escape(title)}</title>
  <style>{REPORT_CSS}{BREADCRUMB_CSS}{MILESTONE_TIMELINE_EXTRA_CSS}{SEFK_EXTRA_CSS}</style>
</head>
<body>
  <main class="report-shell">{nav_block}
    <header class="report-header">
      <h1>{html.escape(title)}</h1>
      <p class="report-subtitle">Generated {html.escape(generated_on)}</p>
      <p class="footnote">{html.escape(footnote)}</p>
    </header>
    <section class="report-card chart-section">
            <div class="sefk-view-controls" aria-label="Hierarchy controls">
                <button type="button" onclick="sefkCollapseAll()">Collapse All</button>
                <button type="button" data-hierarchy-level="phase" onclick="sefkShowPhaseLevel(this)">Phase</button>
                <button type="button" data-hierarchy-level="workstream" onclick="sefkShowWorkStreamLevel(this)">Workstream</button>
                <button type="button" data-hierarchy-level="epic" onclick="sefkShowEpicLevel(this)">Epic</button>
                <button type="button" onclick="sefkExpandAll()">Expand All</button>
            </div>
            <div class="sefk-filter-controls" aria-label="Report filters">
                <button type="button" onclick="sefkToggleFilter('milestone', this)">Milestones</button>
                <button type="button" onclick="sefkToggleFilter('gate', this)">Gates</button>
                <button type="button" onclick="sefkToggleFilter('dependency', this)">Dependencies</button>
            </div>
      <div class="chart-wrap chart-wrap-timeline chart-wrap-milestone chart-wrap-sefk">{chart}</div>
      {sefk_dtrain_key_html()}
    </section>
  </main>
  <script>{SEFK_COLLAPSE_SCRIPT}</script>
</body>
</html>
"""
