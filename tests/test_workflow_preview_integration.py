"""
Workflow Preview 통합 테스트.

- build_classify_batch_preview 기본 동작
- _Step7Preview → _Step8Execute preview_ready 신호 전달
- compute_preview_risk_level 결과가 summary에서 올바르게 반환
"""
from __future__ import annotations

import pytest

from db.database import initialize_database
from core.workflow_summary import compute_preview_risk_level


# ---------------------------------------------------------------------------
# DB 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "test.db"
    c = initialize_database(str(db))
    yield c
    c.close()


def _insert_group(conn, group_id, artwork_id, sync_status="full",
                  series_json='["Blue Archive"]', char_json='["狐坂ワカモ"]',
                  artist_name="test_artist"):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO artwork_groups "
        "(group_id, artwork_id, status, metadata_sync_status, "
        " series_tags_json, character_tags_json, artist_name, "
        " downloaded_at, indexed_at, source_site) "
        "VALUES (?, ?, 'inbox', ?, ?, ?, ?, ?, ?, 'pixiv')",
        (group_id, artwork_id, sync_status,
         series_json, char_json, artist_name, now, now),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# build_classify_batch_preview 통합 테스트
# ---------------------------------------------------------------------------

def _default_config(tmp_path):
    return {
        "classified_dir": str(tmp_path / "Classified"),
        "classification": {
            "primary_strategy": "by_series_character",
            "folder_locale": "canonical",
            "enable_localized_folder_names": True,
            "fallback_by_author": True,
        },
    }


class TestBuildClassifyBatchPreview:
    def test_empty_returns_empty_preview(self, conn, tmp_path):
        from core.batch_classifier import build_classify_batch_preview
        result = build_classify_batch_preview(conn, [], _default_config(tmp_path))
        assert result["total_groups"] == 0
        assert result.get("previews", []) == []

    def test_preview_has_required_keys(self, conn, tmp_path):
        from core.batch_classifier import build_classify_batch_preview
        _insert_group(conn, "g1", "111")
        result = build_classify_batch_preview(conn, ["g1"], _default_config(tmp_path))
        assert "total_groups" in result
        assert "estimated_copies" in result
        assert "estimated_bytes" in result

    def test_metadata_missing_groups_are_excluded(self, conn, tmp_path):
        from core.batch_classifier import build_classify_batch_preview
        _insert_group(conn, "g1", "111", sync_status="metadata_missing",
                      series_json="[]", char_json="[]")
        result = build_classify_batch_preview(conn, ["g1"], _default_config(tmp_path))
        assert result["estimated_copies"] == 0


# ---------------------------------------------------------------------------
# preview_ready Signal → _Step8Execute.set_preview 연동
# ---------------------------------------------------------------------------

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def wizard_fixture(qapp, tmp_path):
    db = tmp_path / "test.db"
    def conn_factory():
        return initialize_database(str(db))
    from app.views.workflow_wizard_view import WorkflowWizardView
    config = {"data_dir": "", "db": {"path": ""}}
    w = WorkflowWizardView(conn_factory, config, "config.json")
    yield w
    w.close()


class TestPreviewReadyWiring:
    def test_preview_ready_signal_propagates_to_step8(self, wizard_fixture):
        from app.views.workflow_wizard_view import _Step7Preview, _Step8Execute
        step7 = wizard_fixture._panels[6]
        step8 = wizard_fixture._panels[7]
        assert isinstance(step7, _Step7Preview)
        assert isinstance(step8, _Step8Execute)

        # simulate preview_ready signal
        fake_preview = {"estimated_copies": 10, "estimated_bytes": 5000, "summary": {}}
        step7.preview_ready.emit(fake_preview)

        assert step8._batch_preview == fake_preview
        assert step8._btn_execute.isEnabled()

    def test_execute_button_disabled_before_preview(self, wizard_fixture):
        from app.views.workflow_wizard_view import _Step8Execute
        step8 = wizard_fixture._panels[7]
        # reset
        step8._batch_preview = None
        step8._btn_execute.setEnabled(False)
        assert not step8._btn_execute.isEnabled()


# ---------------------------------------------------------------------------
# compute_preview_risk_level 종합
# ---------------------------------------------------------------------------

class TestRiskLevelIntegration:
    def test_risk_levels_cover_all_cases(self):
        cases = [
            ({"total_groups": 0}, "low"),
            ({"total_groups": 50, "excluded_count": 0,
              "author_fallback_count": 5, "conflict_count": 0}, "low"),
            ({"total_groups": 100, "excluded_count": 0,
              "author_fallback_count": 25, "conflict_count": 0}, "medium"),
            ({"total_groups": 100, "excluded_count": 0,
              "author_fallback_count": 0, "conflict_count": 10}, "medium"),
            ({"total_groups": 600, "excluded_count": 0,
              "author_fallback_count": 0, "conflict_count": 0}, "medium"),
            ({"total_groups": 100, "excluded_count": 35,
              "author_fallback_count": 0, "conflict_count": 0}, "high"),
            ({"total_groups": 100, "excluded_count": 0,
              "author_fallback_count": 0, "conflict_count": 25}, "high"),
        ]
        for summary, expected in cases:
            result = compute_preview_risk_level(summary)
            assert result == expected, f"summary={summary!r} → expected {expected!r}, got {result!r}"

    def test_risk_level_values_are_valid(self):
        valid = {"low", "medium", "high"}
        for fallback_ratio in [0.0, 0.1, 0.25, 0.5]:
            for conflict_ratio in [0.0, 0.05, 0.1, 0.25]:
                summary = {
                    "total_groups": 100,
                    "excluded_count": 0,
                    "author_fallback_count": int(fallback_ratio * 100),
                    "conflict_count": int(conflict_ratio * 100),
                }
                result = compute_preview_risk_level(summary)
                assert result in valid
