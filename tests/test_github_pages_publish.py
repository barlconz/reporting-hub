"""Tests for GitHub Pages dashboard publish."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from extensions.twoa_programme.github_pages_publish import (
    SiteIndexReport,
    build_github_pages_programme_hub_html,
    build_github_pages_root_index_html,
    build_github_pages_site_index_html,
    load_github_pages_site_config,
    programme_hub_path,
    site_root_index_path,
    write_pages_snapshot,
)
from extensions.twoa_programme.quarterly_reporting import GitHubPagesPublish, load_quarterly_reporting_config


class GitHubPagesPublishTests(unittest.TestCase):
    def test_config_loads_github_pages(self):
        config = load_quarterly_reporting_config()
        self.assertIsNotNone(config.github_pages)
        pages = config.github_pages
        assert pages is not None
        self.assertEqual(pages.publish_dir, "docs/quarter")
        self.assertEqual(pages.index_file, "index.html")
        self.assertEqual(pages.site_path, "quarter")

    def test_site_url(self):
        pages = GitHubPagesPublish(
            publish_dir="docs/quarter",
            index_file="index.html",
            site_path="quarter",
            github_user="barlconz",
            repo_name="artifact-consumer-twoa",
        )
        self.assertEqual(
            pages.site_url(),
            "https://barlconz.github.io/artifact-consumer-twoa/quarter/",
        )

    def test_publish_path(self):
        pages = GitHubPagesPublish(
            publish_dir="docs/quarter",
            index_file="index.html",
        )
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(
            pages.publish_path(root),
            root / "docs" / "quarter" / "index.html",
        )

    def test_write_pages_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "docs" / "quarter" / "index.html"
            write_pages_snapshot("<html>ok</html>", dest)
            self.assertTrue(dest.is_file())
            self.assertEqual(dest.read_text(encoding="utf-8"), "<html>ok</html>")

    def test_site_index_html_lists_reports(self):
        html_doc = build_github_pages_site_index_html(
            [
                SiteIndexReport(href="quarter/", title="Quarter dashboard"),
                SiteIndexReport(href="sprint-health/", title="Sprint Health"),
            ],
            generated_on="19 Jun 2026 05:00 NZST",
            site_url="https://barlconz.github.io/artifact-consumer-twoa/",
        )
        self.assertIn("EPCE delivery reports", html_doc)
        self.assertIn('href="quarter/"', html_doc)
        self.assertIn('href="sprint-health/"', html_doc)
        self.assertIn("barlconz.github.io/artifact-consumer-twoa/", html_doc)

    def test_site_config_loads_programmes(self):
        root = Path(__file__).resolve().parents[1]
        config = load_github_pages_site_config(root / "config" / "github-pages-site.json")
        self.assertEqual(config.site_title, "TWoA reporting hub")
        ids = [programme.id for programme in config.programmes]
        self.assertEqual(ids, ["epc", "sef", "sefk", "enterprise"])

    def test_root_index_groups_by_programme(self):
        root = Path(__file__).resolve().parents[1]
        config = load_github_pages_site_config(root / "config" / "github-pages-site.json")
        html_doc = build_github_pages_root_index_html(
            config,
            generated_on="27 Jun 2026 12:00 NZST",
            site_url="https://arlitwoa.github.io/reporting-hub/",
        )
        self.assertIn("TWoA reporting hub", html_doc)
        self.assertIn('href="epc/"', html_doc)
        self.assertIn('href="sef/"', html_doc)
        self.assertIn('href="enterprise/"', html_doc)
        self.assertIn("EPC delivery", html_doc)
        self.assertIn("Enterprise reporting", html_doc)

    def test_programme_hub_uses_relative_links(self):
        root = Path(__file__).resolve().parents[1]
        config = load_github_pages_site_config(root / "config" / "github-pages-site.json")
        sef = next(programme for programme in config.programmes if programme.id == "sef")
        html_doc = build_github_pages_programme_hub_html(
            sef,
            site_title=config.site_title,
            generated_on="27 Jun 2026 12:00 NZST",
        )
        self.assertIn('href="project-plan.html"', html_doc)
        self.assertIn('href="plans/payroll-parallel.html"', html_doc)
        self.assertIn("Integrated project plan", html_doc)
        self.assertIn('aria-label="Breadcrumb"', html_doc)

    def test_enterprise_hub_lists_governance_report(self):
        root = Path(__file__).resolve().parents[1]
        config = load_github_pages_site_config(root / "config" / "github-pages-site.json")
        enterprise = next(programme for programme in config.programmes if programme.id == "enterprise")
        html_doc = build_github_pages_programme_hub_html(
            enterprise,
            site_title=config.site_title,
            generated_on="27 Jun 2026 12:00 NZST",
        )
        self.assertIn("GitHub Copilot governance summary", html_doc)
        self.assertIn('href="github-copilot-governance.html"', html_doc)

    def test_programme_hub_path(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(programme_hub_path(root, "epc"), root / "docs" / "epc" / "index.html")

    def test_site_root_index_path(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(site_root_index_path(root), root / "docs" / "index.html")


if __name__ == "__main__":
    unittest.main()
