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


# ---------------------------------------------------------------------------
# P0 가드: classified_dir 미설정 시 _on_preview가 thread를 시작하지 않음
# ---------------------------------------------------------------------------
#
# 배경:
#   build_classify_preview()는 cfg["classified_dir"]가 비면 모든 group에 대해
#   silently None을 반환한다. UI는 단지 0건 결과로 보이고, "분류 폴더 미설정"
#   원인을 사용자가 알기 어렵다.
#
#   P0 가드: _Step7Preview._on_preview 진입 시 classified_dir가 비어 있으면
#   - QMessageBox.warning을 띄우고
#   - preview thread를 시작하지 않으며
#   - _batch_preview를 새로 설정하지 않고
#   - 버튼 enable/label도 변경하지 않는다 (preview≡execute frozen 구조 보호).

class TestPreviewGuardOnEmptyClassifiedDir:
    """classified_dir 미설정 시 preview 시작 가드."""

    def test_warning_shown_when_classified_dir_blank(
        self, wizard_fixture, monkeypatch
    ):
        from app.views import workflow_wizard_view as mod
        step7 = wizard_fixture._panels[6]

        # config에 classified_dir 키 자체가 없다 — fixture default.
        wizard_fixture._config.pop("classified_dir", None)

        called: list[tuple] = []

        def _fake_warning(parent, title, text, *args, **kwargs):
            called.append((title, text))
            return None

        monkeypatch.setattr(mod.QMessageBox, "warning", _fake_warning)

        step7._on_preview()

        assert len(called) == 1, "QMessageBox.warning이 정확히 한 번 호출되어야 한다"
        title, text = called[0]
        assert title == "분류 폴더 미설정"
        assert "Step 1" in text
        assert "분류 결과를 저장할 폴더" in text

    def test_warning_shown_when_classified_dir_whitespace(
        self, wizard_fixture, monkeypatch
    ):
        from app.views import workflow_wizard_view as mod
        step7 = wizard_fixture._panels[6]

        # 공백만 있는 경우도 빈 값으로 간주해야 한다.
        wizard_fixture._config["classified_dir"] = "   "

        called: list[tuple] = []
        monkeypatch.setattr(
            mod.QMessageBox, "warning",
            lambda *a, **k: called.append(("called",)) or None,
        )

        step7._on_preview()

        assert len(called) == 1

    def test_preview_thread_not_started_when_classified_dir_blank(
        self, wizard_fixture, monkeypatch
    ):
        from app.views import workflow_wizard_view as mod
        step7 = wizard_fixture._panels[6]

        wizard_fixture._config.pop("classified_dir", None)

        # warning은 무음 처리.
        monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **k: None)

        # _PreviewThread가 절대 생성되지 않음을 확인하기 위해 생성자를 sentinel로 패치.
        thread_ctor_calls: list[tuple] = []

        def _fail_ctor(*args, **kwargs):
            thread_ctor_calls.append((args, kwargs))
            raise AssertionError(
                "classified_dir 미설정 시 _PreviewThread가 생성되면 안 된다"
            )

        monkeypatch.setattr(mod, "_PreviewThread", _fail_ctor)

        before_thread = step7._preview_thread

        step7._on_preview()

        assert step7._preview_thread is before_thread, (
            "preview thread reference가 바뀌지 않아야 한다 (생성/시작 모두 차단)"
        )
        assert thread_ctor_calls == []

    def test_batch_preview_unchanged_when_classified_dir_blank(
        self, wizard_fixture, monkeypatch
    ):
        from app.views import workflow_wizard_view as mod
        step7 = wizard_fixture._panels[6]

        wizard_fixture._config.pop("classified_dir", None)

        # 기존 preview를 흉내 — 가드 발동 후에도 그대로 보존되어야 한다.
        sentinel = {"previews": [{"group_id": "preserved"}], "estimated_copies": 1}
        step7._batch_preview = sentinel

        monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **k: None)

        step7._on_preview()

        assert step7._batch_preview is sentinel, (
            "가드 발동 시 기존 _batch_preview를 None으로 덮어쓰면 안 된다"
        )

    def test_button_state_unchanged_when_classified_dir_blank(
        self, wizard_fixture, monkeypatch
    ):
        from app.views import workflow_wizard_view as mod
        step7 = wizard_fixture._panels[6]

        wizard_fixture._config.pop("classified_dir", None)

        monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **k: None)

        before_enabled = step7._btn_preview.isEnabled()
        before_text = step7._btn_preview.text()

        step7._on_preview()

        assert step7._btn_preview.isEnabled() == before_enabled, (
            "가드 발동 시 버튼 enable 상태가 바뀌면 안 된다"
        )
        assert step7._btn_preview.text() == before_text, (
            "가드 발동 시 버튼 텍스트가 '생성 중…'으로 바뀌면 안 된다"
        )

    def test_dirty_state_untouched_when_classified_dir_blank(
        self, wizard_fixture, monkeypatch
    ):
        """가드는 dirty state 의미를 변경하지 않는다.

        guard 진입 전 dirty였다면 guard 후에도 dirty여야 한다.
        guard 진입 전 clean이었다면 guard 후에도 clean이어야 한다.
        """
        from app.views import workflow_wizard_view as mod
        step7 = wizard_fixture._panels[6]
        wizard_fixture._config.pop("classified_dir", None)
        monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **k: None)

        # case 1: clean 상태 유지
        step7.clear_preview_dirty()
        assert step7.is_preview_dirty() is False
        step7._on_preview()
        assert step7.is_preview_dirty() is False

        # case 2: dirty 상태 유지
        step7.mark_preview_dirty("test reason")
        assert step7.is_preview_dirty() is True
        step7._on_preview()
        assert step7.is_preview_dirty() is True
        # cleanup
        step7.clear_preview_dirty()
