#!/usr/bin/env python3
"""Fetch milestone timeline rows (start date to due date) for the milestone report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from artifact.atlassian import AtlassianAdapter  # noqa: E402

from extensions.twoa_programme.milestone_report_scope import resolve_milestone_report_scope  # noqa: E402
from extensions.twoa_programme.milestone_timeline import (  # noqa: E402
    fetch_milestone_timeline,
)
from extensions.twoa_programme.quarterly_reporting import load_quarterly_reporting_config  # noqa: E402
from scripts.quarterly.common import CONFIG_PATH, SKIP_ISSUE_TYPES, out_path  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch milestone timeline data from Jira.")
    parser.add_argument("--write", action="store_true", help="Write milestone-timeline.json.")
    args = parser.parse_args(argv)

    config = load_quarterly_reporting_config(CONFIG_PATH)
    adapter = AtlassianAdapter.from_profile("atlassian", os.environ["ARTIFACT_PROFILES_DIR"])
    dm = config.delivery_milestones
    filter_name, filter_jql, report_start, report_end = resolve_milestone_report_scope(
        adapter,
        dm,
        config.quarter,
    )
    # Prefer the immutable filter ID so report scope survives filter renames.
    filter_ref = str(dm.in_scope_filter_id or "").strip() or filter_name
    aliases = adapter._resolve_field_aliases()
    delivery_squad_field = aliases.get("Delivery Squad") or "customfield_11102"
    change_types_field = aliases.get("Change Types") or "customfield_10079"
    platform_field = aliases.get("Platform") or "customfield_10120"
    story_points_field = aliases.get("Story Points") or "customfield_10026"

    payload = fetch_milestone_timeline(
        adapter,
        initiative_key=config.quarter.initiative_key,
        quarter_start=report_start,
        quarter_end=report_end,
        quarter_filter=config.scope.quarter_filter,
        in_scope_filter=filter_ref,
        milestone_report_project=dm.milestone_report_project,
        delivery_squad_field=delivery_squad_field,
        change_types_field=change_types_field,
        platform_field=platform_field,
        story_points_field=story_points_field,
        skip_issue_types=SKIP_ISSUE_TYPES,
        changelog_cache_path=out_path("milestone_scope_changelog_cache.json"),
    )
    payload["inScopeFilterId"] = dm.in_scope_filter_id
    payload["inScopeFilterJql"] = filter_jql
    # Prefer filter/quarter fallbacks only when the timeline payload did not derive a window.
    payload.setdefault("reportWindowStart", report_start.isoformat())
    payload.setdefault("reportWindowEnd", report_end.isoformat())

    text = json.dumps(payload, indent=2)
    print(text)
    if args.write:
        path = out_path("milestone-timeline.json")
        path.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
