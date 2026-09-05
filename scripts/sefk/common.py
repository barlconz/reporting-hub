"""Shared paths for SEFK project plan reporting scripts."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "sefk-project-plan-reporting.json"
