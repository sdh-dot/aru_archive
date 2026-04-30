"""
Tag Pack v3 draft isolation tests.

이 테스트는 다음 하나의 불변식만 검증합니다:
  "draft 파일은 격리된 경로에 있고, active dataset이 아니다."

raw draft의 내용(mojibake, strict validator pass 여부 등)은
검증 대상 외입니다. PR 1 범위 밖.
"""
from __future__ import annotations

import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DRAFT_PATH = PROJECT_ROOT / "docs" / "tag_packs" / "drafts" / "tag_pack_export_20260430.raw.json"
ACTIVE_V2_PATH = PROJECT_ROOT / "docs" / "tag_pack_export_localized_ko_ja_failure_patch_v2.json"
LOADER_SOURCE = PROJECT_ROOT / "core" / "tag_pack_loader.py"


def test_v3_raw_draft_exists_under_drafts():
    """draft 파일이 docs/tag_packs/drafts/ 아래에 존재해야 한다."""
    assert DRAFT_PATH.exists(), (
        f"v3 raw draft not found at expected path: {DRAFT_PATH}"
    )


def test_v3_raw_draft_uses_raw_suffix():
    """draft 파일명은 반드시 '.raw.json'으로 끝나야 한다."""
    assert DRAFT_PATH.name.endswith(".raw.json"), (
        f"draft file '{DRAFT_PATH.name}' does not end with '.raw.json'"
    )


def test_active_v2_dataset_remains_flat_docs_path():
    """active v2 dataset은 flat docs/ 경로에 여전히 존재해야 한다."""
    assert ACTIVE_V2_PATH.exists(), (
        f"active v2 dataset missing at: {ACTIVE_V2_PATH}"
    )


def test_draft_path_is_not_active_dataset_path():
    """draft 경로와 active v2 경로는 서로 달라야 한다."""
    assert DRAFT_PATH.resolve() != ACTIVE_V2_PATH.resolve(), (
        "draft path must not equal active v2 dataset path"
    )


def test_no_loader_source_references_drafts_path():
    """
    loader 파일(core/tag_pack_loader.py)이 존재하면
    그 소스에 'tag_packs/drafts' 또는 'drafts/tag_pack' 문자열이
    포함되어서는 안 된다.

    loader 파일이 없으면 skip (loader 부재 자체는 이 테스트 범위 외).
    """
    if not LOADER_SOURCE.exists():
        pytest.skip(f"loader file not found: {LOADER_SOURCE} — skipping source inspection")

    source_text = LOADER_SOURCE.read_text(encoding="utf-8", errors="replace")

    forbidden_patterns = ["tag_packs/drafts", "drafts/tag_pack"]
    for pattern in forbidden_patterns:
        assert pattern not in source_text, (
            f"loader source '{LOADER_SOURCE.name}' contains forbidden reference: '{pattern}'. "
            "Loader must not reference the drafts directory."
        )
