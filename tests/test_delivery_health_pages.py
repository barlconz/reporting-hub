"""Tests for delivery health GitHub Pages publish paths."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from extensions.twoa_programme.delivery_health import load_delivery_health_config
from extensions.twoa_programme.delivery_health_pages import (
    build_no_active_sprint_html,
    build_sprint_health_landing_html,
    ensure_dev_done_generated_timestamp,
    ensure_epc_report_breadcrumb,
    load_delivery_health_pages_config,
    reorder_dev_done_fix_version_section,
)
from extensions.twoa_programme.github_pages_publish import write_pages_snapshot

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HEALTH_CONFIG = _REPO_ROOT / "config" / "delivery-health.json"


class DeliveryHealthPagesTests(unittest.TestCase):
    def test_config_loads_github_pages(self):
        pages = load_delivery_health_pages_config(health_path=_HEALTH_CONFIG)
        self.assertIsNotNone(pages)
        assert pages is not None
        self.assertEqual(pages.sprint_health.publish_dir, "docs/sprint-health")
        self.assertEqual(pages.sprint_health.site_path, "sprint-health")
        self.assertEqual(pages.dev_done_risk.publish_dir, "docs/dev-done-risk")
        self.assertEqual(pages.dev_done_risk.site_path, "dev-done-risk")

    def test_stable_publish_paths(self):
        pages = load_delivery_health_pages_config(health_path=_HEALTH_CONFIG)
        assert pages is not None
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(
            pages.squad_publish_path(root, "kakariki"),
            root / "docs" / "sprint-health" / "kakariki" / "index.html",
        )
        self.assertEqual(
            pages.dev_done_publish_path(root),
            root / "docs" / "dev-done-risk" / "index.html",
        )
        self.assertEqual(
            pages.sprint_landing_path(root),
            root / "docs" / "sprint-health" / "index.html",
        )

    def test_site_urls(self):
        pages = load_delivery_health_pages_config(health_path=_HEALTH_CONFIG)
        assert pages is not None
        self.assertEqual(
            pages.sprint_health.site_url(),
            "https://arlitwoa.github.io/reporting-hub/sprint-health/",
        )
        self.assertEqual(
            pages.dev_done_risk.site_url(),
            "https://arlitwoa.github.io/reporting-hub/dev-done-risk/",
        )

    def test_landing_html_lists_squads(self):
        pages = load_delivery_health_pages_config(health_path=_HEALTH_CONFIG)
        assert pages is not None
        health = load_delivery_health_config(health_path=_HEALTH_CONFIG)
        html_doc = build_sprint_health_landing_html(
            health.squads,
            pages,
            generated_on="10 Jun 2026",
        )
        self.assertIn("Kākāriki", html_doc)
        self.assertIn('href="kakariki/"', html_doc)
        self.assertIn("Waiporoporo", html_doc)
        self.assertIn('class="report-subtitle">Generated 10 Jun 2026</p>', html_doc)

    def test_write_pages_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "docs" / "sprint-health" / "kakariki" / "index.html"
            write_pages_snapshot("<html>ok</html>", dest)
            self.assertTrue(dest.is_file())

    def test_ensure_epc_report_breadcrumb_inserts_nav_and_css(self):
        html_doc = """<!doctype html>
<html lang=\"en\">
<head><style>body { color: #172b4d; }</style></head>
<body><main class=\"report-shell\"><h1>Sample Report</h1></main></body>
</html>
"""
        patched = ensure_epc_report_breadcrumb(
            html_doc,
            publish_path="sprint-health/kakariki/index.html",
        )
        self.assertIn('aria-label="Breadcrumb"', patched)
        self.assertIn('href="../../index.html"', patched)
        self.assertIn('href="../../epc/index.html"', patched)
        self.assertIn(".breadcrumb, .report-nav", patched)

    def test_build_no_active_sprint_html_has_breadcrumb(self):
        html_doc = build_no_active_sprint_html(
            squad_label="Kākāriki",
            generated_on="24 Jul 2026 10:00 NZST",
            publish_path="sprint-health/kakariki/index.html",
        )
        self.assertIn('aria-label="Breadcrumb"', html_doc)
        self.assertIn('href="../../index.html"', html_doc)
        self.assertIn('href="../../epc/index.html"', html_doc)
        self.assertIn("No active sprint is currently configured", html_doc)

    def test_reorder_dev_done_fix_version_section_moves_after_ontrack(self):
        html_doc = """
<section class="report-section"><h2>Summary</h2></section>
<section class="report-section"><h2>FixVersion join timeline</h2><p>timeline</p></section>
<section class="report-section risk-critical"><h2>Critical</h2></section>
<section class="report-section risk-ontrack"><h2>Already past Dev Done</h2><p>on track</p></section>
<section class="report-section"><h2>Recommended actions</h2></section>
"""
        reordered = reorder_dev_done_fix_version_section(html_doc)
        self.assertLess(reordered.index("Already past Dev Done"), reordered.index("FixVersion join timeline"))
        self.assertLess(reordered.index("FixVersion join timeline"), reordered.index("Recommended actions"))

    def test_reorder_dev_done_fix_version_section_is_idempotent(self):
        html_doc = """
<section class="report-section risk-ontrack"><h2>Already past Dev Done</h2></section>
<section class="report-section"><h2>FixVersion join timeline</h2><p>timeline</p></section>
<section class="report-section"><h2>Recommended actions</h2></section>
"""
        self.assertEqual(reorder_dev_done_fix_version_section(html_doc), html_doc)

    def test_dev_done_generated_timestamp_upgrades_date_only_subtitle(self):
        html_doc = (
            '<p class="report-subtitle">\n'
            '  Engine <strong>20260801-engine</strong>\n'
            '  · Generated Monday 03 August 2026\n'
            '</p>'
        )
        updated = ensure_dev_done_generated_timestamp(
            html_doc,
            generated_on="03 Aug 2026 15:42 NZST",
        )
        self.assertIn("· Generated 03 Aug 2026 15:42 NZST", updated)

    def test_dev_done_generated_timestamp_replaces_existing_time(self):
        html_doc = (
            '<p class="report-subtitle">\n'
            '  Engine <strong>20260801-engine</strong>\n'
            '  · Generated 03 Aug 2026 13:00 NZST\n'
            '</p>'
        )
        updated = ensure_dev_done_generated_timestamp(
            html_doc,
            generated_on="03 Aug 2026 15:42 NZST",
        )
        self.assertIn("· Generated 03 Aug 2026 15:42 NZST", updated)
        self.assertNotIn("· Generated 03 Aug 2026 13:00 NZST", updated)


if __name__ == "__main__":
    unittest.main()
