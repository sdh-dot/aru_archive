"""
json_only 메타데이터 경고 표시 테스트.

_Step8Execute._on_execute_done 에서 json_only 건수 ≥1 이면 경고 문구가
_result_lbl에 추가되고, 0건이면 기존 성공 메시지만 표시됨을 검증한다.

PyQt6 전용. PySide6 사용 금지.
offscreen 모드 필요: QT_QPA_PLATFORM=offscreen
"""
from __future__ import annotations

import os
import re
import sys
import types

import pytest

# ------------------------------------------------------------------
# 소스 유틸
# ------------------------------------------------------------------

def _module_source() -> str:
    """workflow_wizard_view 소스를 UTF-8로 직접 읽어 반환."""
    import app.views.workflow_wizard_view as mod
    with open(mod.__file__, encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------
# 순수 로직 테스트 (PyQt6 불필요 — always run)
# ------------------------------------------------------------------

class TestWarningMessageComposition:
    """_on_execute_done 의 경고 문구 구성 로직을 소스 레벨에서 검증한다."""

    def test_warning_text_present_in_source(self):
        """json_only 경고 키워드가 소스에 포함된다."""
        raw = _module_source()
        assert "JSON-only 저장" in raw
        assert "ExifTool 설정을 확인하세요" in raw

    def test_warning_references_json_only_count(self):
        """경고 문구에 건수 포맷팅 패턴이 있다."""
        raw = _module_source()
        assert "json_only_count" in raw

    def test_no_pyside6_import(self):
        """PySide6 import 금지."""
        raw = _module_source()
        assert not re.search(r"^(?:from|import)\s+PySide6", raw, re.MULTILINE)

    def test_no_sqlite3_direct_call(self):
        """UI 코드에서 sqlite3 직접 호출 금지."""
        raw = _module_source()
        assert "import sqlite3" not in raw

    def test_no_file_system_ops(self):
        """UI 코드에서 파일 시스템 직접 조작 금지."""
        raw = _module_source()
        assert "Path.unlink" not in raw
        assert "shutil.copy" not in raw
        assert "os.remove" not in raw

    def test_query_json_only_count_method_exists(self):
        """_query_json_only_count 메서드가 소스에 정의되어 있다."""
        raw = _module_source()
        assert "def _query_json_only_count" in raw

    def test_warning_gate_on_count(self):
        """json_only_count > 0 조건 게이트가 소스에 있다."""
        raw = _module_source()
        assert "json_only_count > 0" in raw

    def test_existing_success_line_preserved(self):
        """기존 성공 메시지 패턴(✅ 완료)이 소스에 여전히 존재한다."""
        raw = _module_source()
        assert "✅ 완료" in raw
        assert "복사:" in raw or "copied" in raw

    def test_korean_warning_text_round_trip(self):
        """한국어 경고 문구가 UTF-8 왕복 후 원형 유지된다."""
        raw = _module_source()
        # 경고 핵심 구절 추출
        assert "Windows Explorer 세부 정보에는 태그/제목이 표시되지 않을 수 있습니다" in raw
        # UTF-8 bytes → str 왕복
        encoded = raw.encode("utf-8")
        decoded = encoded.decode("utf-8")
        assert "Windows Explorer 세부 정보에는 태그/제목이 표시되지 않을 수 있습니다" in decoded

    def test_warning_only_on_success_branch(self):
        """json_only 경고는 success 분기 안에만 있다 (실패 메시지에 추가 안 됨)."""
        raw = _module_source()
        # 실패 분기 키워드 주변에 경고 문구가 없음을 간접 확인:
        # "❌ 실패" 뒤의 텍스트에 "JSON-only"가 들어가지 않아야 한다.
        # 소스 구조상 else 블록이 먼저 끝나므로 이 패턴이 성립.
        fail_idx = raw.find("❌ 실패")
        json_only_idx = raw.find("JSON-only 저장")
        assert fail_idx != -1
        assert json_only_idx != -1
        # json_only_count > 0 게이트는 success 분기 안 (더 앞쪽에 위치)
        gate_idx = raw.find("if json_only_count > 0")
        assert gate_idx < fail_idx, (
            "json_only 경고 게이트가 실패 분기보다 앞에 있어야 합니다"
        )


# ------------------------------------------------------------------
# PyQt6 smoke 테스트 (offscreen 필요)
# ------------------------------------------------------------------

pytestmark_qt = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM", "") == "",
    reason="QT_QPA_PLATFORM=offscreen 필요",
)

pytest.importorskip("PyQt6", reason="PyQt6 필요")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _make_step8(app, conn_factory=None):
    """_Step8Execute 인스턴스를 최소 wizard stub으로 생성한다."""
    from PyQt6.QtWidgets import QWidget
    from app.views.workflow_wizard_view import _Step8Execute

    class _WizardStub(QWidget):
        _config = {}

        def _conn_factory(self):
            if conn_factory is not None:
                return conn_factory()
            # 반환할 conn 없음 — query는 except 처리
            raise RuntimeError("no db")

        def _db_path(self):
            return ":memory:"

        def _go_to_step(self, idx):
            # stub: wizard step navigation not needed in unit tests
            pass

        def _hide_loading(self):
            # stub: loading dialog not used in unit tests
            pass

        def _update_loading(self, **kwargs):
            # stub: loading dialog not used in unit tests
            pass

        def _mirror_loading_log(self, message: str):
            # stub: no-op in unit tests
            pass

    stub = _WizardStub()
    step = _Step8Execute(stub)
    return step


@pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM", "") == "",
    reason="QT_QPA_PLATFORM=offscreen 필요",
)
class TestStep8ExecuteSmoke:
    def test_step8_instantiates(self, app):
        """_Step8Execute 가 예외 없이 생성된다."""
        step = _make_step8(app)
        assert step is not None

    def test_result_lbl_empty_on_init(self, app):
        """초기 _result_lbl 텍스트는 비어 있다."""
        step = _make_step8(app)
        assert step._result_lbl.text() == ""

    def test_warning_when_json_only_count_positive(self, app, tmp_path):
        """json_only 건수 ≥1 이면 경고 문구가 _result_lbl에 추가된다."""
        from db.database import initialize_database

        db_path = str(tmp_path / "test.db")
        conn_ref = initialize_database(db_path)

        # artwork_groups에 json_only 행 2건 삽입
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        for i in range(2):
            conn_ref.execute(
                "INSERT INTO artwork_groups "
                "(group_id, artwork_id, status, metadata_sync_status,"
                " downloaded_at, indexed_at, source_site)"
                " VALUES (?, ?, 'inbox', 'json_only', ?, ?, 'pixiv')",
                (f"g{i}", f"art{i}", now, now),
            )
        conn_ref.commit()
        conn_ref.close()

        import sqlite3

        def _factory():
            return sqlite3.connect(db_path)

        step = _make_step8(app, conn_factory=_factory)
        fake_result = {
            "success": True,
            "copied": 5,
            "skipped": 1,
            "entry_id": "abcd1234efgh",
        }
        step._on_execute_done(fake_result)

        text = step._result_lbl.text()
        assert "JSON-only 저장: 2건" in text
        assert "ExifTool 설정을 확인하세요" in text
        assert "Windows Explorer" in text

    def test_no_warning_when_json_only_zero(self, app, tmp_path):
        """json_only 0건이면 경고 미포함, 기존 성공 메시지만 있다."""
        from db.database import initialize_database

        db_path = str(tmp_path / "test_zero.db")
        conn_ref = initialize_database(db_path)

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        # full 상태만 삽입
        conn_ref.execute(
            "INSERT INTO artwork_groups "
            "(group_id, artwork_id, status, metadata_sync_status,"
            " downloaded_at, indexed_at, source_site)"
            " VALUES ('g0', 'art0', 'inbox', 'full', ?, ?, 'pixiv')",
            (now, now),
        )
        conn_ref.commit()
        conn_ref.close()

        import sqlite3

        def _factory():
            return sqlite3.connect(db_path)

        step = _make_step8(app, conn_factory=_factory)
        fake_result = {
            "success": True,
            "copied": 3,
            "skipped": 0,
            "entry_id": "zzzz9999xxxx",
        }
        step._on_execute_done(fake_result)

        text = step._result_lbl.text()
        assert "✅ 완료" in text
        assert "JSON-only" not in text
        assert "ExifTool 설정을 확인하세요" not in text

    def test_warning_does_not_modify_success_line(self, app, tmp_path):
        """경고 줄 추가 시 기존 성공 라인(복사/스킵/entry_id)이 유지된다."""
        from db.database import initialize_database
        import sqlite3

        db_path = str(tmp_path / "test_preserve.db")
        conn_ref = initialize_database(db_path)

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        conn_ref.execute(
            "INSERT INTO artwork_groups "
            "(group_id, artwork_id, status, metadata_sync_status,"
            " downloaded_at, indexed_at, source_site)"
            " VALUES ('gx', 'artx', 'inbox', 'json_only', ?, ?, 'pixiv')",
            (now, now),
        )
        conn_ref.commit()
        conn_ref.close()

        def _factory():
            return sqlite3.connect(db_path)

        step = _make_step8(app, conn_factory=_factory)
        fake_result = {
            "success": True,
            "copied": 7,
            "skipped": 2,
            "entry_id": "entry-uuid-here",
        }
        step._on_execute_done(fake_result)

        text = step._result_lbl.text()
        assert "✅ 완료" in text
        assert "복사: 7" in text
        assert "스킵: 2" in text
        assert "entry-uu" in text          # entry_id[:8]
        assert "JSON-only 저장: 1건" in text

    def test_failure_result_shows_no_warning(self, app, tmp_path):
        """실패 결과에는 json_only 경고가 추가되지 않는다."""
        from db.database import initialize_database
        import sqlite3

        db_path = str(tmp_path / "test_fail.db")
        conn_ref = initialize_database(db_path)

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        conn_ref.execute(
            "INSERT INTO artwork_groups "
            "(group_id, artwork_id, status, metadata_sync_status,"
            " downloaded_at, indexed_at, source_site)"
            " VALUES ('gf', 'artf', 'inbox', 'json_only', ?, ?, 'pixiv')",
            (now, now),
        )
        conn_ref.commit()
        conn_ref.close()

        def _factory():
            return sqlite3.connect(db_path)

        step = _make_step8(app, conn_factory=_factory)
        fake_result = {
            "success": False,
            "error": "분류 실패 원인",
        }
        step._on_execute_done(fake_result)

        text = step._result_lbl.text()
        assert "❌ 실패" in text
        assert "JSON-only" not in text

    def test_query_json_only_count_returns_zero_on_db_error(self, app):
        """DB 접근 실패 시 _query_json_only_count 는 0을 반환한다 (예외 미전파)."""
        step = _make_step8(app)   # conn_factory는 RuntimeError 발생
        count = step._query_json_only_count()
        assert count == 0
