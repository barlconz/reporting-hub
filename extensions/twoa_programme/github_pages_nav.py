"""Breadcrumb navigation for reporting-hub GitHub Pages snapshots."""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import PurePosixPath

DEFAULT_SITE_TITLE = "TWoA reporting hub"
EPC_PROGRAMME_ID = "epc"
EPC_PROGRAMME_TITLE = "EPC delivery"
SEF_PROGRAMME_ID = "sef"
SEF_PROGRAMME_TITLE = "SEF"
SEFK_PROGRAMME_ID = "sefk"
SEFK_PROGRAMME_TITLE = "SEFK"

BREADCRUMB_CSS = """
.breadcrumb, .report-nav {
  font-size: 13px;
  line-height: 1.5;
  margin: 0 0 16px;
  color: #5e6c84;
}
.breadcrumb a, .report-nav a {
  color: #0052cc;
  text-decoration: none;
  font-weight: 600;
}
.breadcrumb a:hover, .report-nav a:hover { text-decoration: underline; }
.breadcrumb .sep, .report-nav .sep { margin: 0 0.35em; color: #97a0af; }
.breadcrumb .current, .report-nav .current { color: #172b4d; font-weight: 600; }
"""


@dataclass(frozen=True)
class NavCrumb:
    label: str
    href: str | None = None


def docs_relative_href(from_doc: str, to_doc: str) -> str:
    """Relative href from one docs/ HTML path to another."""
    import os

    from_dir = PurePosixPath(from_doc).parent
    rel = os.path.relpath(to_doc, from_dir.as_posix())
    return rel.replace("\\", "/")


def build_breadcrumb_html(
    crumbs: list[NavCrumb],
    *,
    css_class: str = "breadcrumb",
) -> str:
    if not crumbs:
        return ""
    parts: list[str] = []
    for index, crumb in enumerate(crumbs):
        if index:
            parts.append('<span class="sep">›</span>')
        label = html.escape(crumb.label)
        if crumb.href and index < len(crumbs) - 1:
            parts.append(f'<a href="{html.escape(crumb.href)}">{label}</a>')
        else:
            parts.append(f'<span class="current">{label}</span>')
    inner = " ".join(parts)
    return f'<nav class="{css_class}" aria-label="Breadcrumb">{inner}</nav>'


def programme_report_breadcrumbs(
    *,
    publish_path: str,
    programme_id: str,
    programme_title: str,
    report_title: str,
    site_title: str = DEFAULT_SITE_TITLE,
) -> str:
    """Breadcrumb nav for a programme report under docs/."""
    crumbs = [
        NavCrumb(site_title, docs_relative_href(publish_path, "index.html")),
        NavCrumb(
            programme_title,
            docs_relative_href(publish_path, f"{programme_id}/index.html"),
        ),
        NavCrumb(report_title),
    ]
    return build_breadcrumb_html(crumbs, css_class="report-nav")


def epc_report_breadcrumbs(
    *,
    publish_path: str,
    report_title: str,
    site_title: str = DEFAULT_SITE_TITLE,
    programme_title: str = EPC_PROGRAMME_TITLE,
) -> str:
    return programme_report_breadcrumbs(
        publish_path=publish_path,
        programme_id=EPC_PROGRAMME_ID,
        programme_title=programme_title,
        report_title=report_title,
        site_title=site_title,
    )


def programme_hub_breadcrumbs(
    *,
    programme_title: str,
    site_title: str = DEFAULT_SITE_TITLE,
) -> str:
    crumbs = [
        NavCrumb(site_title, "../index.html"),
        NavCrumb(programme_title),
    ]
    return build_breadcrumb_html(crumbs)
