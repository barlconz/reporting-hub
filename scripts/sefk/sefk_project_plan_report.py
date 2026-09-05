#!/usr/bin/env python3
"""Build SEFK integrated project plan Gantt HTML from timeline JSON."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from extensions.twoa_programme.github_pages_nav import (  # noqa: E402
    SEFK_PROGRAMME_ID,
    SEFK_PROGRAMME_TITLE,
    programme_report_breadcrumbs,
)
from extensions.twoa_programme.quarterly_reporting import NZ_TZ  # noqa: E402
from extensions.twoa_programme.sefk_project_plan_reporting import (  # noqa: E402
    load_sefk_project_plan_reporting_config,
)
from extensions.twoa_programme.sefk_project_plan_timeline import (  # noqa: E402
    build_sefk_project_plan_report_html,
    default_sefk_project_plan_timeline_path,
    load_sefk_project_plan_timeline_payload,
)
from scripts.sefk.common import CONFIG_PATH  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build SEFK project plan Gantt HTML report.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write sefk-project-plan-chart.html under output/quarterly/{slug}/.",
    )
    parser.add_argument("--input", type=Path, default=None, help="Override timeline JSON path.")
    parser.add_argument("--output", type=Path, default=None, help="Override output HTML path.")
    args = parser.parse_args(argv)

    config = load_sefk_project_plan_reporting_config(CONFIG_PATH)
    artifact_path = args.input or default_sefk_project_plan_timeline_path(_REPO_ROOT)
    payload = load_sefk_project_plan_timeline_payload(artifact_path)
    if not payload:
        print(
            f"No artifact at {artifact_path}. Run fetch_sefk_project_plan_timeline.py --write.",
            file=sys.stderr,
        )
        return 1

    generated = datetime.now(NZ_TZ).strftime("%d %b %Y %H:%M %Z")
    publish_path = config.pages_publish_path.removeprefix("docs/")
    breadcrumb = programme_report_breadcrumbs(
        publish_path=publish_path,
        programme_id=SEFK_PROGRAMME_ID,
        programme_title=SEFK_PROGRAMME_TITLE,
        report_title=config.page_title,
    )
    html_doc = build_sefk_project_plan_report_html(
        payload,
        generated_on=generated,
        page_title=config.page_title,
        breadcrumb_nav=breadcrumb,
    )

    out_file = args.output or config.html_path(_REPO_ROOT)
    pages_path = _REPO_ROOT / config.pages_publish_path

    if args.write or args.output:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(html_doc, encoding="utf-8")
        print(f"Wrote {out_file}", file=sys.stderr)
        if args.write:
            pages_path.parent.mkdir(parents=True, exist_ok=True)
            pages_path.write_text(html_doc, encoding="utf-8")
            print(f"Wrote {pages_path}", file=sys.stderr)
    else:
        sys.stdout.write(html_doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
