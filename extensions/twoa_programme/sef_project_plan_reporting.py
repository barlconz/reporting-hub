"""Config loader for SEF integrated project plan Block Gantt (PDE)."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from artifact.atlassian import AtlassianAdapter

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_NAME = "sef-project-plan-reporting.json"
_MANIFEST_NAME = "sef-project-plan-blocks.json"

DEFAULT_PHASE_HUB_JQL = (
    'project = PDE AND issuetype = "Block Level Two" '
    'AND summary ~ "SEF Phase" ORDER BY "Start date" ASC, key ASC'
)


@dataclass(frozen=True)
class PhaseHubDiscovery:
    filter_id: str | None
    filter_name: str | None
    jql: str | None


@dataclass(frozen=True)
class SefFilterDimensionConfig:
    id: str
    label: str
    source_field: str


@dataclass(frozen=True)
class SefProjectPlanReportingConfig:
    project_key: str
    phase_hub_keys: tuple[str, ...]
    phase_hub_discovery: PhaseHubDiscovery | None
    manifest_path: Path
    chart_window_start: str
    chart_window_end: str
    chapter_issue_type: str
    package_issue_type: str
    detail_issue_type: str
    test_cycle_issue_type: str
    scope_filter_id: str | None
    scope_filter_name: str | None
    timeline_artifact: str
    html_artifact: str
    pages_publish_path: str
    pages_site_path: str
    page_title: str
    milestone_issue_types: tuple[str, ...] = ("Meeting Gate", "Milestone")
    extra_package_issue_types: tuple[str, ...] = ()
    extra_chapter_issue_types: tuple[str, ...] = ()
    filter_dimensions: tuple[SefFilterDimensionConfig, ...] = (
        SefFilterDimensionConfig(id="workstream", label="Workstream", source_field="workstreams"),
    )
    def output_root(self, repo_root: Path | None = None) -> Path:
        from extensions.twoa_programme.quarterly_reporting import load_quarterly_reporting_config

        root = repo_root or _REPO_ROOT
        config = load_quarterly_reporting_config(root / "config" / "quarterly-reporting.json")
        return config.output_root(root)

    def timeline_path(self, repo_root: Path | None = None) -> Path:
        return self.output_root(repo_root) / self.timeline_artifact

    def html_path(self, repo_root: Path | None = None) -> Path:
        return self.output_root(repo_root) / self.html_artifact


def load_sef_project_plan_reporting_config(
    path: Path | None = None,
    *,
    repo_root: Path | None = None,
) -> SefProjectPlanReportingConfig:
    root = repo_root or _REPO_ROOT
    config_path = path or root / "config" / _CONFIG_NAME
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    manifest_file = str(raw.get("manifestFile") or _MANIFEST_NAME)
    manifest_path = root / "config" / manifest_file
    hubs = raw.get("phaseHubKeys") or []
    window = raw.get("chartWindow") or {}
    issue_types = raw.get("issueTypes") or {}
    milestone_issue_types_raw = issue_types.get("milestones")
    milestone_issue_types: list[str]
    if isinstance(milestone_issue_types_raw, list):
        milestone_issue_types = [
            str(name).strip() for name in milestone_issue_types_raw if str(name).strip()
        ]
    elif milestone_issue_types_raw:
        milestone_issue_types = [str(milestone_issue_types_raw).strip()]
    else:
        milestone_issue_types = ["Meeting Gate", "Milestone"]

    filter_dimensions_raw = raw.get("filterDimensions") or []
    filter_dimensions: list[SefFilterDimensionConfig] = []
    for row in filter_dimensions_raw:
        if not isinstance(row, dict):
            continue
        dim_id = str(row.get("id") or "").strip()
        source_field = str(row.get("sourceField") or "").strip()
        if not dim_id or not source_field:
            continue
        label = str(row.get("label") or dim_id.title()).strip()
        filter_dimensions.append(
            SefFilterDimensionConfig(
                id=dim_id,
                label=label,
                source_field=source_field,
            )
        )
    if not filter_dimensions:
        filter_dimensions = [
            SefFilterDimensionConfig(id="workstream", label="Workstream", source_field="workstreams")
        ]
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
    return SefProjectPlanReportingConfig(
        project_key=str(raw.get("projectKey") or "PDE"),
        phase_hub_keys=tuple(str(key) for key in hubs),
        phase_hub_discovery=discovery,
        manifest_path=manifest_path,
        chart_window_start=str(window.get("start") or "2026-06-01"),
        chart_window_end=str(window.get("end") or "2027-12-03"),
        chapter_issue_type=str(issue_types.get("chapter") or "Block Level One"),
        package_issue_type=str(issue_types.get("package") or "Block Level Zero"),
        detail_issue_type=str(issue_types.get("detail") or "Block Level Minus One"),
        test_cycle_issue_type=str(issue_types.get("testCycle") or "Test Cycle"),
        milestone_issue_types=tuple(milestone_issue_types),
        extra_package_issue_types=tuple(
            str(t).strip()
            for t in (issue_types.get("additionalPackageTypes") or [])
            if str(t).strip()
        ),
        extra_chapter_issue_types=tuple(
            str(t).strip()
            for t in (issue_types.get("additionalChapterTypes") or [])
            if str(t).strip()
        ),
        filter_dimensions=tuple(filter_dimensions),
        scope_filter_id=str(raw.get("scopeFilter", {}).get("filterId") or "").strip() or None,
        scope_filter_name=str(raw.get("scopeFilter", {}).get("filterName") or "").strip() or None,
        timeline_artifact=str(artifacts.get("timelineJson") or "sef-project-plan-timeline.json"),
        html_artifact=str(artifacts.get("htmlFile") or "sef-project-plan-chart.html"),
        pages_publish_path=str(pages.get("publishPath") or "docs/sef/project-plan.html"),
        pages_site_path=str(pages.get("sitePath") or "sef/project-plan.html"),
        page_title=str(pages.get("pageTitle") or "SEF | Integrated Project Plan"),
    )


def load_phase_hub_keys(config: SefProjectPlanReportingConfig) -> list[str]:
    if config.phase_hub_keys:
        return list(config.phase_hub_keys)
    if not config.manifest_path.is_file():
        return []
    manifest = json.loads(config.manifest_path.read_text(encoding="utf-8"))
    keys: list[str] = []
    for phase_key in ("phase1", "phase2"):
        block = manifest.get(phase_key) or {}
        hub = block.get(phase_key)
        if hub:
            keys.append(str(hub))
    return keys


def resolve_phase_hub_discovery_jql(
    adapter: "AtlassianAdapter",
    discovery: PhaseHubDiscovery,
) -> str:
    """Resolve saved filter or explicit JQL for phase hub discovery."""
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
    config: SefProjectPlanReportingConfig,
    *,
    fields: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Discover phase hub issues from JQL/filter; skip missing configured keys."""
    from extensions.twoa_programme.jira_search import search_all

    warnings: list[str] = []

    if config.phase_hub_discovery is not None:
        jql = resolve_phase_hub_discovery_jql(adapter, config.phase_hub_discovery)
        issues = search_all(adapter, jql, fields)
        if not issues:
            warnings.append(f"Phase hub discovery returned no issues ({jql}).")
        return issues, warnings

    keys = load_phase_hub_keys(config)
    if not keys:
        warnings.append("No phaseHubDiscovery configured and no phaseHubKeys available.")
        return [], warnings

    jql = f"key in ({', '.join(keys)}) ORDER BY \"Start date\" ASC, key ASC"
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
