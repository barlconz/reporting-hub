import os
import subprocess
import unittest
from pathlib import Path


class RefreshReportsScriptSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.script_path = cls.repo_root / "scripts" / "refresh_github_pages_reports.sh"

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        return subprocess.run(
            ["bash", str(self.script_path), *args],
            cwd=self.repo_root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_list_stages(self):
        result = self._run("--list-stages")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(lines, ["quarterly", "sef", "sefk", "delivery-health", "site-index"])

    def test_site_index_preflight_only(self):
        result = self._run("--stage", "site-index", "--preflight-only")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Preflight passed.", result.stdout)
        self.assertIn("Preflight-only mode complete.", result.stdout)

    def test_quarterly_preflight_only(self):
        result = self._run("--stage", "quarterly", "--preflight-only")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Preflight passed.", result.stdout)
        self.assertIn("Preflight-only mode complete.", result.stdout)


if __name__ == "__main__":
    unittest.main()
