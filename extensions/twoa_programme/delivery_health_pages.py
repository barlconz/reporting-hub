"""GitHub Pages publish paths for Sprint Health and Dev Done risk reports."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from artifact.delivery_health.config import SquadConfig
from artifact.delivery_health.dev_done_engine import fetch_engine
from artifact.delivery_health.gateway import JiraGateway

from extensions.twoa_programme.quarterly_reporting import GitHubPagesPublish

from extensions.twoa_programme.github_pages_nav import BREADCRUMB_CSS, epc_report_breadcrumbs

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_HEALTH = _REPO_ROOT / "config" / "delivery-health.json"


@dataclass(frozen=True)
class DeliveryHealthPagesConfig:
    sprint_health: GitHubPagesPublish
    dev_done_risk: GitHubPagesPublish

    def squad_publish_path(self, repo_root: Path, squad_slug: str) -> Path:
        return repo_root / self.sprint_health.publish_dir / squad_slug / "index.html"

    def sprint_landing_path(self, repo_root: Path) -> Path:
        return repo_root / self.sprint_health.publish_dir / "index.html"

    def dev_done_publish_path(self, repo_root: Path) -> Path:
        return repo_root / self.dev_done_risk.publish_dir / self.dev_done_risk.index_file


def _pages_section(payload: dict[str, Any], key: str, *, github_user: str, repo_name: str) -> GitHubPagesPublish:
    section = payload[key]
    return GitHubPagesPublish(
        publish_dir=str(section["publishDir"]),
        index_file=str(section.get("indexFile", "index.html")),
        site_path=str(section.get("sitePath", "")),
        github_user=github_user,
        repo_name=repo_name,
    )


def load_delivery_health_pages_config(
    *,
    health_path: Path | None = None,
) -> DeliveryHealthPagesConfig | None:
    health_file = health_path or _DEFAULT_HEALTH
    payload = json.loads(health_file.read_text(encoding="utf-8"))
    pages_payload = payload.get("githubPages")
    if not pages_payload:
        return None
    github_user = str(pages_payload.get("githubUser", ""))
    repo_name = str(pages_payload.get("repoName", ""))
    return DeliveryHealthPagesConfig(
        sprint_health=_pages_section(
            pages_payload,
            "sprintHealth",
            github_user=github_user,
            repo_name=repo_name,
        ),
        dev_done_risk=_pages_section(
            pages_payload,
            "devDoneRisk",
            github_user=github_user,
            repo_name=repo_name,
        ),
    )


def resolve_in_cycle_fix_version(
    jira: JiraGateway,
    *,
    dev_done_risk,
) -> str:
    """FixVersion on the current in-cycle PDE Engine (smart-engine-in-cycle)."""
    engine = fetch_engine(jira, dev_done_risk, None)
    engine_fields = engine["fields"]
    fix_versions = engine_fields.get("fixVersions") or []
    if fix_versions:
        return str(fix_versions[0]["name"])
    return str(engine_fields.get("summary") or "engine")


def _extract_report_title(html_doc: str) -> str:
    match = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", html_doc, flags=re.IGNORECASE)
    if not match:
        return "Report"
    text = re.sub(r"<[^>]+>", "", match.group(1))
    text = " ".join(html.unescape(text).split())
    return text or "Report"


def ensure_epc_report_breadcrumb(
    html_doc: str,
    *,
    publish_path: str,
    report_title: str | None = None,
) -> str:
    """Ensure EPC report HTML has breadcrumb CSS and nav.

    Some upstream report generators do not emit breadcrumbs. This helper
    injects the standard breadcrumb styles and nav block so GitHub Pages
    snapshots remain navigable.
    """
    if 'aria-label="Breadcrumb"' in html_doc:
        return html_doc

    resolved_title = report_title or _extract_report_title(html_doc)
    breadcrumb = epc_report_breadcrumbs(
        publish_path=publish_path,
        report_title=resolved_title,
    )

    patched = html_doc
    if ".breadcrumb, .report-nav" not in patched and "</style>" in patched:
        patched = patched.replace("</style>", f"{BREADCRUMB_CSS}\n</style>", 1)

    main_match = re.search(r"<main\b[^>]*>", patched, flags=re.IGNORECASE)
    if main_match:
        insert_at = main_match.end()
        patched = patched[:insert_at] + f"\n{breadcrumb}\n" + patched[insert_at:]
        return patched

    body_match = re.search(r"<body\b[^>]*>", patched, flags=re.IGNORECASE)
    if body_match:
        insert_at = body_match.end()
        patched = patched[:insert_at] + f"\n{breadcrumb}\n" + patched[insert_at:]
    return patched


_FIX_VERSION_SECTION_RE = re.compile(
    r'\s*<section class="report-section">\s*<h2>FixVersion join timeline</h2>[\s\S]*?</section>',
    flags=re.IGNORECASE,
)
_ONTRACK_SECTION_RE = re.compile(
    r'\s*<section class="report-section risk-ontrack">[\s\S]*?</section>',
    flags=re.IGNORECASE,
)


def reorder_dev_done_fix_version_section(html_doc: str) -> str:
    """Move FixVersion join timeline after the Already past Dev Done section.

    barlconz-artifact-core 0.2.1 renders the timeline before the risk buckets.
    Reorder published HTML so severity sections read top-to-bottom before scope history.
    """
    fix_match = _FIX_VERSION_SECTION_RE.search(html_doc)
    ontrack_match = _ONTRACK_SECTION_RE.search(html_doc)
    if not fix_match or not ontrack_match:
        return html_doc

    if fix_match.start() > ontrack_match.start():
        return html_doc

    fix_section = fix_match.group(0)
    without_fix = html_doc[: fix_match.start()] + html_doc[fix_match.end() :]
    ontrack_match = _ONTRACK_SECTION_RE.search(without_fix)
    if not ontrack_match:
        return html_doc

    insert_at = ontrack_match.end()
    return without_fix[:insert_at] + fix_section + without_fix[insert_at:]


def ensure_dev_done_generated_timestamp(html_doc: str, *, generated_on: str) -> str:
    """Force Dev Done subtitle to include a full generated timestamp.

    The core report can emit date-only text (for example, "Generated Monday 03 August 2026").
    For GitHub Pages delivery reports we require NZ local time as well.
    """

    stamp = f"· Generated {generated_on}"
    return re.sub(r"·\s*Generated[^<\n]*", stamp, html_doc, count=1)


def build_sprint_health_landing_html(
    squads: dict[str, SquadConfig],
    pages: DeliveryHealthPagesConfig,
    *,
    generated_on: str,
) -> str:
    base = pages.sprint_health.site_url() or ""
    items = []
    for slug, squad in sorted(squads.items(), key=lambda item: item[1].label):
        href = f"{slug}/"
        title = html.escape(squad.label)
        items.append(f'<li><a href="{html.escape(href)}">{title}</a></li>')
    squad_list = "\n      ".join(items)
    site_note = ""
    if base:
        site_note = f'<p class="note">Stable URLs under <a href="{html.escape(base)}">{html.escape(base)}</a>.</p>'
    breadcrumb = epc_report_breadcrumbs(
        publish_path="sprint-health/index.html",
        report_title="EPCE Sprint Health",
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EPCE Sprint Health</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 2rem; color: #172b4d; }}
    h1 {{ font-size: 1.5rem; margin: 0 0 8px; }}
    .report-subtitle {{ margin: 0 0 1rem; color: #5e6c84; font-size: 0.95rem; }}
    ul {{ line-height: 1.8; }}
    .note {{ color: #5e6c84; font-size: 0.9rem; }}
    {BREADCRUMB_CSS}
  </style>
</head>
<body>
  <main>
    {breadcrumb}
    <h1>EPCE Sprint Health</h1>
    <p class="report-subtitle">Generated {html.escape(generated_on)}</p>
    <p>Per-squad sprint scope, forecast, and delivery health. Each link is overwritten when the snapshot refreshes.</p>
    <ul>
      {squad_list}
    </ul>
    {site_note}
  </main>
</body>
</html>
"""


def build_no_active_sprint_html(
        *,
        squad_label: str,
        generated_on: str,
        publish_path: str,
) -> str:
        """Build a stable Sprint Health placeholder page when no active sprint exists."""
        title = f"Sprint Health Report: {squad_label}"
        breadcrumb = epc_report_breadcrumbs(
                publish_path=publish_path,
                report_title=title,
        )
        return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{html.escape(title)}</title>
    <style>
        :root {{
            color-scheme: light;
            --page-bg: #f3f4f6;
            --card-bg: #ffffff;
            --border: #d1d5db;
            --text: #111827;
            --muted: #4b5563;
        }}
        body {{
            margin: 0;
            background: var(--page-bg);
            color: var(--text);
            font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }}
        .report-shell {{
            max-width: 980px;
            margin: 0 auto;
            padding: 28px 32px 40px;
        }}
        .report-card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 16px;
            box-shadow: 0 12px 32px rgba(15, 23, 42, 0.08);
            padding: 24px;
            margin-bottom: 24px;
        }}
        h1 {{
            margin: 0 0 8px;
            font-size: 26px;
            line-height: 1.2;
            letter-spacing: -0.03em;
        }}
        .report-subtitle {{
            margin: 0 0 18px;
            color: var(--muted);
            font-size: 15px;
            line-height: 1.5;
        }}
        p {{
            color: #374151;
            font-size: 14px;
            line-height: 1.6;
            margin: 0 0 10px;
        }}
        {BREADCRUMB_CSS}
    </style>
</head>
<body>
<main class="report-shell">
    {breadcrumb}
    <section class="report-card">
        <h1>{html.escape(title)}</h1>
        <p class="report-subtitle">Generated {html.escape(generated_on)}</p>
        <p>No active sprint is currently configured for this squad board.</p>
        <p>This placeholder keeps the stable report URL available until a sprint is activated.</p>
    </section>
</main>
</body>
</html>
"""
