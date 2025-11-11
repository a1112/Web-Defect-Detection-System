"""
Server package bootstrap.

Ensures the local bkjc_database project is importable without requiring an
editable install.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BKJC_PROJECT = REPO_ROOT / "link_project" / "bkjc_database"
if BKJC_PROJECT.exists():
    sys.path.insert(0, str(BKJC_PROJECT))
