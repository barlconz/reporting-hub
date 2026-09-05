#!/usr/bin/env python3
"""Publish Sprint Health and Dev Done risk HTML snapshots for GitHub Pages."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from artifact.atlassian import AtlassianAdapter  # noqa: E402
from artifact.delivery_health.dev_done_engine import run_dev_done_risk_report  # noqa: E402
from artifact.delivery_health.gateway import ArtifactJiraGateway  # noqa: E402
from artifact.delivery_health.sprint_engine import run_sprint_health_reports  # noqa: E402

from extensions.twoa_programme.delivery_health import load_delivery_health_config  # noqa: E402
from extensions.twoa_programme.delivery_health_pages import (  # noqa: E402
    DeliveryHealthPagesConfig,
    build_no_active_sprint_html,
    build_sprint_health_landing_html,
    ensure_dev_done_generated_timestamp,
    ensure_epc_report_breadcrumb,
    load_delivery_health_pages_config,
    reorder_dev_done_fix_version_section,
    resolve_in_cycle_fix_version,
)
from extensions.twoa_programme.github_pages_publish import write_pages_snapshot  # noqa: E402
from extensions.twoa_programme.quarterly_reporting import NZ_TZ  # noqa: E402

_DEFAULT_PROFILE = "atlassian"


def _profiles_dir() -> Path:
    return Path(os.environ.get("ARTIFACT_PROFILES_DIR", str(_REPO_ROOT / "config" / "profiles")))


def _profile_name(argv: list[str] | None) -> str:
    if not argv:
        return _DEFAULT_PROFILE
    for index, token in enumerate(argv):
        if token == "--profile" and index + 1 < len(argv):
            return argv[index + 1]
    return _DEFAULT_PROFILE


def _gateway(profile_name: str) -> ArtifactJiraGateway:
    adapter = AtlassianAdapter.from_profile(profile_name, profiles_dir=str(_profiles_dir()))
    return ArtifactJiraGateway(adapter.http)


def publish_snapshots(
    *,
    gateway: ArtifactJiraGateway,
    pages: DeliveryHealthPagesConfig,
    health_config,
    repo_root: Path,
    generated_on: str,
    sprint_only: bool = False,
    dev_done_only: bool = False,
) -> list[Path]:
    written: list[Path] = []
    risk = health_config.dev_done_risk
    if risk is None:
        raise SystemExit("config/delivery-health.json has no devDoneRisk section.")

    release_fix_version = resolve_in_cycle_fix_version(gateway, dev_done_risk=risk)

    if not dev_done_only:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            for squad_slug, squad in sorted(health_config.squads.items()):
                sprint_args = Namespace(
                    sprint_name="",
                    active_sprint=True,
                    squad=[squad_slug],
                    release_fix_version=release_fix_version,
                    output_dir=tmp_dir,
                    redact_names=False,
                )
                try:
                    generated = run_sprint_health_reports(health_config, gateway, sprint_args)
                except SystemExit as exc:
                    message = str(exc)
                    if "No active sprint for squad" not in message:
                        raise
                    generated = []

                dest = pages.squad_publish_path(repo_root, squad_slug)
                publish_path = f"sprint-health/{squad_slug}/index.html"
                if generated:
                    source = generated[0]
                    html_doc = source.read_text(encoding="utf-8")
                    html_doc = ensure_epc_report_breadcrumb(
                        html_doc,
                        publish_path=publish_path,
                    )
                else:
                    html_doc = build_no_active_sprint_html(
                        squad_label=squad.label,
                        generated_on=generated_on,
                        publish_path=publish_path,
                    )
                write_pages_snapshot(html_doc, dest)
                written.append(dest)

            landing = build_sprint_health_landing_html(
                health_config.squads,
                pages,
                generated_on=generated_on,
            )
            landing_dest = pages.sprint_landing_path(repo_root)
            write_pages_snapshot(landing, landing_dest)
            written.append(landing_dest)

    if not sprint_only:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            dev_args = Namespace(
                fixversion=None,
                milestone_label=None,
                large_sp_threshold=None,
                output=None,
                output_dir=tmp_dir,
                redact_names=False,
            )
            source = run_dev_done_risk_report(health_config, gateway, dev_args)
            dest = pages.dev_done_publish_path(repo_root)
            html_doc = source.read_text(encoding="utf-8")
            html_doc = ensure_epc_report_breadcrumb(
                html_doc,
                publish_path=f"{pages.dev_done_risk.site_path}/{pages.dev_done_risk.index_file}",
                report_title="EPCE Dev Done Risk",
            )
            html_doc = reorder_dev_done_fix_version_section(html_doc)
            html_doc = ensure_dev_done_generated_timestamp(html_doc, generated_on=generated_on)
            write_pages_snapshot(html_doc, dest)
            written.append(dest)

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate Sprint Health and Dev Done risk HTML into docs/ for GitHub Pages."
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write HTML into githubPages paths from config/delivery-health.json.",
    )
    parser.add_argument(
        "--sprint-health-only",
        action="store_true",
        help="Publish squad Sprint Health reports and landing page only.",
    )
    parser.add_argument(
        "--dev-done-only",
        action="store_true",
        help="Publish Dev Done risk report only.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved paths only; do not call Jira or write files.",
    )
    args = parser.parse_args(argv)

    if args.sprint_health_only and args.dev_done_only:
        parser.error("Pass at most one of --sprint-health-only or --dev-done-only.")

    if not args.write and not args.dry_run:
        parser.error("Pass --write or --dry-run.")

    pages = load_delivery_health_pages_config()
    if pages is None:
        raise SystemExit("config/delivery-health.json has no githubPages section.")

    health_config = load_delivery_health_config()
    generated_on = datetime.now(NZ_TZ).strftime("%d %b %Y %H:%M %Z")

    if args.dry_run:
        print("Sprint Health landing:", pages.sprint_landing_path(_REPO_ROOT))
        for slug in sorted(health_config.squads):
            print(f"Sprint Health {slug}:", pages.squad_publish_path(_REPO_ROOT, slug))
        print("Dev Done risk:", pages.dev_done_publish_path(_REPO_ROOT))
        sprint_url = pages.sprint_health.site_url()
        dev_url = pages.dev_done_risk.site_url()
        if sprint_url:
            print("Sprint Health URL:", sprint_url)
        if dev_url:
            print("Dev Done risk URL:", dev_url)
        return 0

    gateway = _gateway(_profile_name(argv))
    written = publish_snapshots(
        gateway=gateway,
        pages=pages,
        health_config=health_config,
        repo_root=_REPO_ROOT,
        generated_on=generated_on,
        sprint_only=args.sprint_health_only,
        dev_done_only=args.dev_done_only,
    )

    for path in written:
        print(f"Wrote {path}", file=sys.stderr)
    sprint_url = pages.sprint_health.site_url()
    dev_url = pages.dev_done_risk.site_url()
    if sprint_url and not args.dev_done_only:
        print(f"Sprint Health: {sprint_url}", file=sys.stderr)
    if dev_url and not args.sprint_health_only:
        print(f"Dev Done risk: {dev_url}", file=sys.stderr)
    print(
        "Commit docs/sprint-health/ and docs/dev-done-risk/, push to develop, "
        "then open the URLs above.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
