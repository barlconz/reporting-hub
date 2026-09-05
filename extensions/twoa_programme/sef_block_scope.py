"""D-Train scope composition for SEF Block Plan Gantt bars (Scope issue link).

For SEF block planning, scope weight is issue-count based (not Story Points).
"""

from __future__ import annotations

from typing import Any, Callable

from extensions.twoa_programme.delivery_milestones import milestone_linked_issues
from extensions.twoa_programme.epic_timeline import EPIC_CHILD_ISSUE_TYPES
from extensions.twoa_programme.jira_binding_loader import load_jira_binding
from extensions.twoa_programme.jira_search import search_all
from extensions.twoa_programme.milestone_scope_chart import (
    _chart_phase_keys,
    _empty_scope_rollup_bucket,
    _merge_sorted_issue_keys,
    resolve_issue_dtrain_phase,
)
from extensions.twoa_programme.quarter_scope import (
    SCOPE_ISSUE_TYPES,
    issue_excluded_from_analysis,
    milestone_linked_epic_scope_jql,
)

BLOCK_SCOPE_LINK_TYPE = "Scope"
EPIC_ISSUE_TYPE = "Epic"


def linked_scope_targets(issue: dict[str, Any], *, link_type: str = BLOCK_SCOPE_LINK_TYPE) -> list[dict[str, Any]]:
    """Issues linked from a Block via the Scope link (either direction)."""
    return milestone_linked_issues(issue, link_type=link_type)


def _linked_issue_type(target: dict[str, Any]) -> str:
    return str(((target.get("fields") or {}).get("issuetype") or {}).get("name") or "")


def rollup_scope_issues(
    issues: list[dict[str, Any]],
    *,
    story_points_field: str,
    binding=None,
) -> dict[str, Any]:
    """Single-bucket D-Train phase rollup for Story/Bug/Spike scope issues.

    Each in-scope issue contributes weight 1 to its resolved D-Train phase.
    """
    jira_binding = binding or load_jira_binding()
    bucket = _empty_scope_rollup_bucket()
    for issue in issues:
        fields = issue.get("fields") or {}
        itype = str((fields.get("issuetype") or {}).get("name") or "")
        if itype not in EPIC_CHILD_ISSUE_TYPES:
            continue
        if issue_excluded_from_analysis(issue):
            continue

        issue_key = str(issue.get("key") or "")
        status = str((fields.get("status") or {}).get("name") or "")
        phase = resolve_issue_dtrain_phase(status, jira_binding)
        bucket["phases"][phase] += 1.0
        if issue_key:
            bucket["phaseIssueKeys"][phase].append(issue_key)

    phase_keys = _chart_phase_keys()
    issue_count = int(sum(float(bucket["phases"].get(phase) or 0) for phase in phase_keys))
    return {
        "phases": {phase: round(float(bucket["phases"].get(phase) or 0), 2) for phase in phase_keys},
        "phaseIssueKeys": {
            phase: _merge_sorted_issue_keys(bucket["phaseIssueKeys"].get(phase) or []) for phase in phase_keys
        },
        "issueCount": issue_count,
        # Legacy fields kept for compatibility with shared overlay helpers.
        "unpointedCount": 0,
        "unpointedIssueKeys": [],
        "storyPoints": float(issue_count),
        "totalWeight": float(issue_count),
    }


def build_block_scope_rollups(
    adapter: Any,
    *,
    block_issues: dict[str, dict[str, Any]],
    link_type: str = BLOCK_SCOPE_LINK_TYPE,
    story_points_field: str = "customfield_10026",
    binding=None,
    skip_issue: Callable[[dict[str, Any]], bool] = issue_excluded_from_analysis,
) -> dict[str, dict[str, Any]]:
    """Resolve Scope-linked epics (rollup children) and direct Story/Bug/Spike per block key."""
    epic_keys: set[str] = set()
    direct_keys: set[str] = set()
    links_by_block: dict[str, list[dict[str, Any]]] = {}

    for block_key, issue in block_issues.items():
        linked = linked_scope_targets(issue, link_type=link_type)
        if not linked:
            continue
        links_by_block[block_key] = linked
        for target in linked:
            target_key = str(target.get("key") or "")
            if not target_key:
                continue
            itype = _linked_issue_type(target)
            if itype == EPIC_ISSUE_TYPE:
                epic_keys.add(target_key)
            elif itype in SCOPE_ISSUE_TYPES:
                direct_keys.add(target_key)

    scope_fields = ["parent", "issuetype", "status", story_points_field]
    scope_issues_by_key: dict[str, dict[str, Any]] = {}
    children_by_epic: dict[str, list[dict[str, Any]]] = {key: [] for key in epic_keys}

    if epic_keys:
        child_jql = milestone_linked_epic_scope_jql(parent_keys_csv=", ".join(sorted(epic_keys)))
        for child in search_all(adapter, child_jql, scope_fields):
            child_key = str(child.get("key") or "")
            if not child_key or skip_issue(child):
                continue
            scope_issues_by_key[child_key] = child
            parent_key = str(((child.get("fields") or {}).get("parent") or {}).get("key") or "")
            if parent_key in children_by_epic:
                children_by_epic[parent_key].append(child)

    remaining_direct = sorted(direct_keys - set(scope_issues_by_key.keys()))
    if remaining_direct:
        direct_jql = f"key in ({', '.join(remaining_direct)})"
        for issue in search_all(adapter, direct_jql, scope_fields):
            issue_key = str(issue.get("key") or "")
            if issue_key and not skip_issue(issue):
                scope_issues_by_key[issue_key] = issue

    rollups: dict[str, dict[str, Any]] = {}
    for block_key, linked in links_by_block.items():
        scope_issues: list[dict[str, Any]] = []
        seen: set[str] = set()
        for target in linked:
            target_key = str(target.get("key") or "")
            itype = _linked_issue_type(target)
            if itype == EPIC_ISSUE_TYPE:
                for child in children_by_epic.get(target_key, []):
                    child_key = str(child.get("key") or "")
                    if child_key and child_key not in seen:
                        seen.add(child_key)
                        scope_issues.append(child)
            elif itype in SCOPE_ISSUE_TYPES and target_key in scope_issues_by_key:
                if target_key not in seen:
                    seen.add(target_key)
                    scope_issues.append(scope_issues_by_key[target_key])
        rollup = rollup_scope_issues(
            scope_issues,
            story_points_field=story_points_field,
            binding=binding,
        )
        if float(rollup.get("totalWeight") or 0) > 0:
            rollups[block_key] = rollup
    return rollups


def apply_scope_rollups_to_rows(
    rows: list[dict[str, Any]],
    rollups: dict[str, dict[str, Any]],
) -> None:
    for row in rows:
        key = str(row.get("key") or "")
        if key and key in rollups:
            row["scopeRollup"] = rollups[key]
