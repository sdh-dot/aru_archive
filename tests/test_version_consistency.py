"""Regression tests for app version consistency.

Ensures core.version.APP_VERSION is the single source of truth and
main.py does not retain hardcoded version strings.
"""
from __future__ import annotations

import re
from pathlib import Path

from core.version import APP_VERSION


# UTF-8 safe source reader (cp949 환경 회피 — Windows 콘솔 호환)
def _read_source(rel_path: str) -> str:
    root = Path(__file__).resolve().parent.parent
    return (root / rel_path).read_text(encoding="utf-8")


def test_app_version_matches_release_tag():
    """APP_VERSION should match the latest release tag (v0.6.3)."""
    assert APP_VERSION == "0.6.3", (
        f"APP_VERSION={APP_VERSION!r} does not match release tag v0.6.3. "
        "Update core/version.py when bumping the release."
    )


def test_main_py_does_not_hardcode_version():
    """main.py must not contain a hardcoded setApplicationVersion literal."""
    src = _read_source("main.py")
    bad_patterns = [
        r'setApplicationVersion\s*\(\s*["\']\d',  # any digit literal
    ]
    for pat in bad_patterns:
        assert not re.search(pat, src), (
            f"main.py contains hardcoded setApplicationVersion literal "
            f"matching {pat!r}. Use APP_VERSION instead."
        )


def test_main_py_uses_app_version():
    """main.py must reference APP_VERSION for setApplicationVersion."""
    src = _read_source("main.py")
    assert "from core.version import APP_VERSION" in src or \
           "import core.version" in src or \
           "from core import version" in src, (
        "main.py does not import APP_VERSION from core.version"
    )
    assert re.search(r'setApplicationVersion\s*\(\s*APP_VERSION', src), (
        "main.py does not pass APP_VERSION to setApplicationVersion"
    )
