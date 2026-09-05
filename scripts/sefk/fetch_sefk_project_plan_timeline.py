#!/usr/bin/env python3
"""Fetch SEFK integrated project plan hierarchy from PDE for the plan Gantt."""

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

from extensions.twoa_programme.sefk_project_plan_reporting import (  # noqa: E402
    load_sefk_project_plan_reporting_config,
    log_phase_hub_warnings,
)
from extensions.twoa_programme.sefk_project_plan_timeline import (  # noqa: E402
    fetch_sefk_project_plan_timeline,
)
from scripts.sefk.common import CONFIG_PATH  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch SEFK project plan timeline from Jira.")
    parser.add_argument("--write", action="store_true", help="Write sefk-project-plan-timeline.json.")
    args = parser.parse_args(argv)

    config = load_sefk_project_plan_reporting_config(CONFIG_PATH)
    adapter = AtlassianAdapter.from_profile("atlassian", os.environ["ARTIFACT_PROFILES_DIR"])
    payload = fetch_sefk_project_plan_timeline(adapter, config)
    log_phase_hub_warnings(list(payload.get("warnings") or []))

    text = json.dumps(payload, indent=2)
    print(text)
    if args.write:
        path = config.timeline_path(_REPO_ROOT)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
