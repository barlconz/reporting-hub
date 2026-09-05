"""Workstream colour mapping for SEF project plan Gantt."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG = _REPO_ROOT / "config" / "sef-project-plan-component-colors.json"
WORKSTREAM_FIELD_ID = "customfield_12291"
WORKSTREAM_ALIASES: dict[str, str] = {
    "data-migration": "data",
    "people-and-change": "change",
}


def _canonical_workstream(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "-").replace(" ", "-")


@dataclass(frozen=True)
class SefProjectPlanComponentColors:
    default_fill: str
    default_label: str
    workstreams: dict[str, str]
    source: str | None = None

    @property
    def components(self) -> dict[str, str]:
        """Backward-compatible alias for older component-based callers."""
        return self.workstreams

    def fill_for_row(self, row: dict[str, Any]) -> str:
        for name in row.get("workstreams") or row.get("components") or []:
            workstream = str(name or "").strip()
            if workstream in self.workstreams:
                return self.workstreams[workstream]
            canonical = _canonical_workstream(workstream)
            canonical = WORKSTREAM_ALIASES.get(canonical, canonical)
            for key, fill in self.workstreams.items():
                if _canonical_workstream(key) == canonical:
                    return fill
        return self.default_fill

    def legend_entries(self) -> list[tuple[str, str]]:
        rows = [(self.default_label, self.default_fill)]
        for name in sorted(self.workstreams):
            rows.append((name, self.workstreams[name]))
        return rows


def load_sef_project_plan_component_colors(
    path: Path | None = None,
    *,
    repo_root: Path | None = None,
) -> SefProjectPlanComponentColors:
    root = repo_root or _REPO_ROOT
    config_path = path or root / "config" / "sef-project-plan-component-colors.json"
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    workstreams = {
        str(name): str(fill)
        for name, fill in (raw.get("workstreams") or raw.get("components") or {}).items()
        if name and fill
    }
    return SefProjectPlanComponentColors(
        default_fill=str(raw.get("defaultFill") or "#7A869A"),
        default_label=str(raw.get("defaultLabel") or "All other work items"),
        workstreams=workstreams,
        source=str(raw.get("source") or "").strip() or None,
    )


def component_names_from_issue(issue: dict[str, Any]) -> list[str]:
    fields = issue.get("fields") or {}
    return [
        str(component.get("name") or "").strip()
        for component in (fields.get("components") or [])
        if str((component or {}).get("name") or "").strip()
    ]


def workstream_names_from_issue(issue: dict[str, Any]) -> list[str]:
    """Resolve Workstream values from Jira field, with component fallback for older data."""
    fields = issue.get("fields") or {}
    raw = fields.get(WORKSTREAM_FIELD_ID)
    values: list[str] = []

    def _append_value(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, dict):
            text = str(item.get("value") or item.get("name") or "").strip()
        else:
            text = str(item).strip()
        if text:
            values.append(text)

    if isinstance(raw, list):
        for item in raw:
            _append_value(item)
    else:
        _append_value(raw)

    if not values:
        return component_names_from_issue(issue)

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def sef_project_plan_component_legend_html(colors: SefProjectPlanComponentColors) -> str:
    items = []
    for label, fill in colors.legend_entries():
        items.append(
            '<span class="sef-plan-legend-item">'
            f'<span class="sef-plan-legend-swatch" style="background:{html.escape(fill)}"></span>'
            f"{html.escape(label)}"
            "</span>"
        )
    return f'<div class="sef-plan-legend">{"".join(items)}</div>'


def sef_project_plan_workstream_legend_html(colors: SefProjectPlanComponentColors) -> str:
    return sef_project_plan_component_legend_html(colors)
