"""D-Train scope rollups for SEFK schedule Gantt bars (issue-count by child status)."""

from __future__ import annotations

import re
from typing import Any

from extensions.twoa_programme.milestone_scope_chart import (
    _UNKNOWN_PHASE,
    _chart_phase_keys,
    _empty_scope_rollup_bucket,
    _merge_sorted_issue_keys,
    chart_dtrain_phases,
)
from extensions.twoa_programme.quarter_scope import issue_excluded_from_analysis

KPMG_DELETED_LABEL = "kpmg-deleted"

DEFAULT_SCOPE_ISSUE_TYPES: tuple[str, ...] = (
    "Task",
    "Action",
    "Sub-task",
    "Deliverable",
)

DEFAULT_STATUS_DTRAIN: dict[str, str] = {
    "Not Started": "Dream",
    "New": "Dream",
    "Open": "Dream",
    "On Hold": "Discover",
    "Draft Review": "Design",
    "WIP (25%)": "Develop",
    "WIP (50%)": "Develop",
    "WIP (75%)": "Develop",
    "In Progress": "Develop",
    "Final Review": "Demonstrate",
    "Approved": "Demonstrate",
    "Completed": "Drive",
}

_WIP_STATUS_RE = re.compile(r"^WIP\s*\(", re.IGNORECASE)


def issue_has_kpmg_deleted_label(issue: dict[str, Any]) -> bool:
    labels = (issue.get("fields") or {}).get("labels") or []
    if not isinstance(labels, list):
        return False
    folded = {str(label).strip().casefold() for label in labels if str(label).strip()}
    return KPMG_DELETED_LABEL.casefold() in folded


def issue_excluded_from_sefk_project_plan(issue: dict[str, Any]) -> bool:
    """Omit tombstoned KPMG-deleted peers and other analysis exclusions from SEFK plan scope."""
    return issue_excluded_from_analysis(issue) or issue_has_kpmg_deleted_label(issue)


def sefk_scope_exclusion_jql() -> str:
    # Jira treats `labels not in (...)` as false when labels is empty; keep unlabeled issues.
    return f"(labels is EMPTY OR labels not in ({KPMG_DELETED_LABEL}))"


def resolve_sefk_issue_dtrain_phase(
    status: str | None,
    *,
    status_map: dict[str, str] | None = None,
) -> str:
    name = (status or "").strip()
    if not name:
        return _UNKNOWN_PHASE
    mapping = status_map or DEFAULT_STATUS_DTRAIN
    phase = mapping.get(name)
    if not phase and _WIP_STATUS_RE.match(name):
        phase = "Develop"
    if not phase or phase not in chart_dtrain_phases():
        return _UNKNOWN_PHASE
    return phase


def sefk_epic_scope_jql(
    *,
    parent_keys_csv: str,
    scope_issue_types: tuple[str, ...] = DEFAULT_SCOPE_ISSUE_TYPES,
) -> str:
    types = ", ".join(f'"{name.replace("\\", "\\\\").replace("\"", "\\\"")}"' for name in scope_issue_types)
    return (
        f"issuetype in ({types}) AND status != Rejected "
        f"AND {sefk_scope_exclusion_jql()} "
        f"AND parent in ({parent_keys_csv})"
    )


def rollup_sefk_epic_phases(
    children: list[dict[str, Any]],
    *,
    epic_keys: list[str],
    scope_issue_types: tuple[str, ...] = DEFAULT_SCOPE_ISSUE_TYPES,
    status_map: dict[str, str] | None = None,
    skip_issue=issue_excluded_from_sefk_project_plan,
) -> dict[str, dict[str, Any]]:
    """Per-epic D-Train phase counts (weight 1 per in-scope child issue)."""
    allowed_types = set(scope_issue_types)
    buckets: dict[str, dict[str, Any]] = {
        epic_key: _empty_scope_rollup_bucket() for epic_key in epic_keys
    }
    for issue in children:
        fields = issue.get("fields") or {}
        itype = str((fields.get("issuetype") or {}).get("name") or "")
        if itype not in allowed_types:
            continue
        if skip_issue(issue):
            continue

        parent = fields.get("parent") or {}
        epic_key = str(parent.get("key") or "")
        if epic_key not in buckets:
            continue

        issue_key = str(issue.get("key") or "")
        status = str((fields.get("status") or {}).get("name") or "")
        phase = resolve_sefk_issue_dtrain_phase(status, status_map=status_map)
        buckets[epic_key]["phases"][phase] += 1.0
        if issue_key:
            buckets[epic_key]["phaseIssueKeys"][phase].append(issue_key)

    for epic_data in buckets.values():
        phase_keys = _chart_phase_keys()
        issue_count = int(sum(float(epic_data["phases"].get(phase) or 0) for phase in phase_keys))
        epic_data["issueCount"] = issue_count
        epic_data["unpointedCount"] = 0
        epic_data["unpointedIssueKeys"] = []
        epic_data["storyPoints"] = float(issue_count)
        epic_data["totalWeight"] = float(issue_count)
        epic_data["phases"] = {
            phase: round(float(epic_data["phases"].get(phase) or 0), 2) for phase in phase_keys
        }
        epic_data["phaseIssueKeys"] = {
            phase: _merge_sorted_issue_keys(epic_data["phaseIssueKeys"].get(phase) or [])
            for phase in phase_keys
        }
    return buckets
