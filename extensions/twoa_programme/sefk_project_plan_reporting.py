"""Config loader for SEFK integrated project plan Gantt (PDE)."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from artifact.atlassian import AtlassianAdapter

from extensions.twoa_programme.sefk_scope import DEFAULT_SCOPE_ISSUE_TYPES, DEFAULT_STATUS_DTRAIN

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_NAME = "sefk-project-plan-reporting.json"

DEFAULT_PHASE_HUB_JQL = (
    'project = SEFK AND issuetype = Phase ORDER BY "Start date" ASC, key ASC'
)


@dataclass(frozen=True)
class PhaseHubDiscovery:
    filter_id: str | None
    filter_name: str | None
    jql: str | None


@dataclass(frozen=True)
class SefkProjectPlanReportingConfig:
    project_key: str
    phase_hub_keys: tuple[str, ...]
    phase_hub_discovery: PhaseHubDiscovery | None
    chart_window_start: str
    chart_window_end: str
    phase_hub_issue_type: str
    sub_phase_issue_type: str
    work_stream_issue_type: str
    epic_issue_type: str
    milestone_issue_types: tuple[str, ...]
    gate_issue_types: tuple[str, ...]
    additional_epic_types: tuple[str, ...]
    scope_filter_id: str | None
    scope_filter_name: str | None
    timeline_artifact: str
    html_artifact: str
    pages_publish_path: str
    pages_site_path: str
    page_title: str
    scope_issue_types: tuple[str, ...]
    status_dtrain: dict[str, str]
    sub_phase_order: tuple[str, ...]

    def output_root(self, repo_root: Path | None = None) -> Path:
        from extensions.twoa_programme.quarterly_reporting import load_quarterly_reporting_config

        root = repo_root or _REPO_ROOT
        config = load_quarterly_reporting_config(root / "config" / "quarterly-reporting.json")
        return config.output_root(root)

    def timeline_path(self, repo_root: Path | None = None) -> Path:
        return self.output_root(repo_root) / self.timeline_artifact

    def html_path(self, repo_root: Path | None = None) -> Path:
        return self.output_root(repo_root) / self.html_artifact


def load_sefk_project_plan_reporting_config(
    path: Path | None = None,
    *,
    repo_root: Path | None = None,
) -> SefkProjectPlanReportingConfig:
    root = repo_root or _REPO_ROOT
    config_path = path or root / "config" / _CONFIG_NAME
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    hubs = raw.get("phaseHubKeys") or []
    window = raw.get("chartWindow") or {}
    issue_types = raw.get("issueTypes") or {}
    artifacts = raw.get("artifacts") or {}
    pages = raw.get("githubPages") or {}
    discovery_raw = raw.get("phaseHubDiscovery")
    discovery = None
    if isinstance(discovery_raw, dict):
        discovery = PhaseHubDiscovery(
            filter_id=str(discovery_raw["filterId"]).strip() if discovery_raw.get("filterId") else None,
            filter_name=str(discovery_raw["filter"]).strip() if discovery_raw.get("filter") else None,
            jql=str(discovery_raw["jql"]).strip() if discovery_raw.get("jql") else None,
        )
    scope_filter = raw.get("scopeFilter") or {}
    scope_issue_types_raw = raw.get("scopeIssueTypes") or list(DEFAULT_SCOPE_ISSUE_TYPES)
    scope_issue_types = tuple(
        str(name).strip() for name in scope_issue_types_raw if str(name).strip()
    ) or DEFAULT_SCOPE_ISSUE_TYPES
    status_dtrain_raw = raw.get("statusDtrain") or {}
    status_dtrain = {
        str(status).strip(): str(phase).strip()
        for status, phase in status_dtrain_raw.items()
        if str(status).strip() and str(phase).strip()
    } or dict(DEFAULT_STATUS_DTRAIN)
    sub_phase_order_raw = raw.get("subPhaseOrder") or []
    sub_phase_order = tuple(str(name).strip() for name in sub_phase_order_raw if str(name).strip())
    milestone_types_raw = issue_types.get("milestones") or []
    gate_types_raw = issue_types.get("gates") or []
    additional_epic_types_raw = issue_types.get("additionalEpicTypes") or []
    return SefkProjectPlanReportingConfig(
        project_key=str(raw.get("projectKey") or "PDE"),
        phase_hub_keys=tuple(str(key) for key in hubs),
        phase_hub_discovery=discovery,
        chart_window_start=str(window.get("start") or "2026-06-01"),
        chart_window_end=str(window.get("end") or "2027-12-31"),
        phase_hub_issue_type=str(issue_types.get("phaseHub") or "Block Level Two"),
        sub_phase_issue_type=str(issue_types.get("subPhase") or "Block Level One"),
        work_stream_issue_type=str(issue_types.get("workStream") or "Block Level Zero"),
        epic_issue_type=str(issue_types.get("epic") or "Epic"),
        milestone_issue_types=tuple(str(name).strip() for name in milestone_types_raw if str(name).strip()),
        gate_issue_types=tuple(str(name).strip() for name in gate_types_raw if str(name).strip()),
        additional_epic_types=tuple(str(name).strip() for name in additional_epic_types_raw if str(name).strip()),
        scope_filter_id=str(scope_filter.get("filterId") or "").strip() or None,
        scope_filter_name=str(scope_filter.get("filterName") or "").strip() or None,
        timeline_artifact=str(artifacts.get("timelineJson") or "sefk-project-plan-timeline.json"),
        html_artifact=str(artifacts.get("htmlFile") or "sefk-project-plan-chart.html"),
        pages_publish_path=str(pages.get("publishPath") or "docs/sefk/project-plan.html"),
        pages_site_path=str(pages.get("sitePath") or "sefk/project-plan.html"),
        page_title=str(pages.get("pageTitle") or "SEFK | Integrated Project Plan"),
        scope_issue_types=scope_issue_types,
        status_dtrain=status_dtrain,
        sub_phase_order=sub_phase_order,
    )


def resolve_phase_hub_discovery_jql(
    adapter: "AtlassianAdapter",
    discovery: PhaseHubDiscovery,
) -> str:
    if discovery.filter_id:
        from extensions.twoa_programme.delivery_milestones import fetch_jira_saved_filter

        payload = fetch_jira_saved_filter(adapter, discovery.filter_id)
        jql = str(payload.get("jql") or "").strip()
        if jql:
            return jql
    if discovery.filter_name:
        return f"filter = {discovery.filter_name.strip()}"
    if discovery.jql:
        return discovery.jql.strip()
    return DEFAULT_PHASE_HUB_JQL


def discover_phase_hub_issues(
    adapter: "AtlassianAdapter",
    config: SefkProjectPlanReportingConfig,
    *,
    fields: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    from extensions.twoa_programme.jira_search import search_all

    warnings: list[str] = []

    if config.phase_hub_discovery is not None:
        jql = resolve_phase_hub_discovery_jql(adapter, config.phase_hub_discovery)
        issues = search_all(adapter, jql, fields)
        if not issues:
            warnings.append(f"Phase hub discovery returned no issues ({jql}).")
        return issues, warnings

    keys = list(config.phase_hub_keys)
    if not keys:
        warnings.append("No phaseHubDiscovery configured and no phaseHubKeys available.")
        return [], warnings

    jql = f'key in ({", ".join(keys)}) ORDER BY "Start date" ASC, key ASC'
    issues = search_all(adapter, jql, fields)
    found = {str(issue.get("key") or "") for issue in issues}
    for key in keys:
        if key not in found:
            warnings.append(f"Phase hub not found in Jira (skipped): {key}")
    by_key = {str(issue.get("key") or ""): issue for issue in issues}
    ordered = [by_key[key] for key in keys if key in by_key]
    return ordered, warnings


def log_phase_hub_warnings(warnings: list[str]) -> None:
    for message in warnings:
        print(message, file=sys.stderr)


def resolve_scope_filter_jql(
    adapter: "AtlassianAdapter",
    config: SefkProjectPlanReportingConfig,
) -> str | None:
    if config.scope_filter_id:
        from extensions.twoa_programme.delivery_milestones import fetch_jira_saved_filter

        payload = fetch_jira_saved_filter(adapter, config.scope_filter_id)
        jql = str(payload.get("jql") or "").strip()
        return jql or f"filter = {config.scope_filter_id}"
    if config.scope_filter_name:
        return f"filter = {config.scope_filter_name}"
    return None
