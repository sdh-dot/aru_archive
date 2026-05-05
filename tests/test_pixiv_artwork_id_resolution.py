"""Pixiv artwork_id resolution 경로 테스트.

Phase split 이후 DB에 비숫자 artwork_id(예: file_hash[:16] placeholder)가
저장된 경우, fetch_and_store_pixiv_metadata 가 Pixiv API에 잘못된 값을
전달하지 않고 filename fallback으로 올바른 숫자 Pixiv ID를 얻는지 검증한다.

핵심 버그 재현:
    inbox_scanner.py 는 내장 메타데이터가 없는 파일에 artwork_id = file_hash[:16]
    (예: "d43965258a880b20")을 저장한다.
    Phase 1이 이 값을 그대로 Pixiv API로 전달하면 404.
    수정 후: isdigit() 검증 → 비숫자이면 파일명 파싱 fallback.
"""
from __future__ import annotations

import io
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from PIL import Image as PILImage

from core.metadata_enricher import (
    build_enrichment_queue,
    fetch_and_store_pixiv_metadata,
)


# ---------------------------------------------------------------------------
# fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _make_jpg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    PILImage.new("RGB", (1, 1)).save(buf, format="JPEG")
    path.write_bytes(buf.getvalue())


def _insert_group(
    conn: sqlite3.Connection,
    group_id: str,
    artwork_id: str,
    source_site: str = "pixiv",
    sync_status: str = "metadata_missing",
) -> None:
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, source_site, artwork_id, downloaded_at, indexed_at,
            metadata_sync_status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (group_id, source_site, artwork_id, _now(), _now(), sync_status),
    )
    conn.commit()


def _insert_file(
    conn: sqlite3.Connection,
    file_id: str,
    group_id: str,
    file_path: str,
) -> None:
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path, file_format,
            created_at, file_status)
           VALUES (?, ?, 0, 'original', ?, 'jpg', ?, 'present')""",
        (file_id, group_id, file_path, _now()),
    )
    conn.commit()


def _make_adapter(artwork_id: str = "12345678") -> MagicMock:
    from core.models import AruMetadata
    adapter = MagicMock()
    adapter.fetch_metadata.return_value = {
        "illustId": artwork_id, "title": "Test", "userId": "999",
        "userName": "Artist", "pageCount": 1, "illustType": 0,
        "tags": {"tags": []},
    }
    meta = AruMetadata(
        artwork_id=artwork_id, artwork_title="Test",
        artist_id="999", artist_name="Artist",
        artist_url="https://www.pixiv.net/users/999",
        tags=[], series_tags=[], character_tags=[], raw_tags=[],
    )
    adapter.to_aru_metadata.return_value = meta
    return adapter


# ---------------------------------------------------------------------------
# TestDbNumericArtworkId — DB에 숫자 artwork_id가 있으면 그대로 사용
# ---------------------------------------------------------------------------

class TestDbNumericArtworkId:
    def test_uses_db_numeric_id_directly(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """DB에 숫자 artwork_id가 있으면 파일명과 무관하게 해당 ID로 API 호출."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_group(db, gid, "12345678")
        _insert_file(db, fid, gid, str(img))

        adapter = _make_adapter("12345678")
        r = fetch_and_store_pixiv_metadata(db, fid, adapter=adapter)

        assert r["status"] == "ok"
        adapter.fetch_metadata.assert_called_once_with("12345678")

    def test_numeric_db_id_is_not_replaced_by_filename(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """파일명의 ID와 DB의 숫자 ID가 다를 때 DB 값 우선."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        # 파일명에는 99999999, DB에는 12345678
        img = tmp_path / "99999999_p0.jpg"
        _make_jpg(img)
        _insert_group(db, gid, "12345678")
        _insert_file(db, fid, gid, str(img))

        adapter = _make_adapter("12345678")
        r = fetch_and_store_pixiv_metadata(db, fid, adapter=adapter)

        assert r["status"] == "ok"
        adapter.fetch_metadata.assert_called_once_with("12345678")


# ---------------------------------------------------------------------------
# TestHashPlaceholderFallback — DB에 hash placeholder가 있으면 filename fallback
# ---------------------------------------------------------------------------

class TestHashPlaceholderFallback:
    def test_non_numeric_db_id_falls_back_to_filename(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """DB artwork_id가 hash placeholder(비숫자)이면 파일명에서 Pixiv ID를 추출."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        # 스캐너가 기록한 hash placeholder
        hash_placeholder = "d43965258a880b20"
        img = tmp_path / "12345678_p0.jpg"   # Pixiv 형식 파일명
        _make_jpg(img)
        _insert_group(db, gid, hash_placeholder, source_site="local")
        _insert_file(db, fid, gid, str(img))

        adapter = _make_adapter("12345678")
        r = fetch_and_store_pixiv_metadata(db, fid, adapter=adapter)

        assert r["status"] == "ok", f"예상: ok, 실제: {r['status']} ({r.get('message')})"
        # hash placeholder가 아닌 파일명에서 추출한 숫자 ID로 호출되어야 함
        adapter.fetch_metadata.assert_called_once_with("12345678")
        assert adapter.fetch_metadata.call_args[0][0] != hash_placeholder

    def test_hash_placeholder_is_not_sent_to_pixiv_api(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """비숫자 DB artwork_id는 절대 Pixiv API로 전달되지 않는다."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        img = tmp_path / "87654321_p0.jpg"
        _make_jpg(img)
        _insert_group(db, gid, "ea6f21659f3a6d5f", source_site="local")
        _insert_file(db, fid, gid, str(img))

        adapter = _make_adapter("87654321")
        fetch_and_store_pixiv_metadata(db, fid, adapter=adapter)

        sent_id = adapter.fetch_metadata.call_args[0][0]
        assert sent_id.isdigit(), f"비숫자 ID가 API로 전달됨: {sent_id!r}"

    @pytest.mark.parametrize("placeholder", [
        "d43965258a880b20",   # file_hash[:16] 예시
        "ea6f21659f3a6d5f",
        "ec459c7e061361d5",
        "abc123def456",       # 짧은 hex
        "some-uuid-prefix",   # uuid 앞부분
    ])
    def test_various_non_numeric_placeholders_trigger_fallback(
        self, db: sqlite3.Connection, tmp_path: Path, placeholder: str
    ) -> None:
        """다양한 형태의 비숫자 DB artwork_id 모두 filename fallback으로 처리."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        img = tmp_path / "11223344_p0.jpg"
        _make_jpg(img)
        _insert_group(db, gid, placeholder, source_site="local")
        _insert_file(db, fid, gid, str(img))

        adapter = _make_adapter("11223344")
        r = fetch_and_store_pixiv_metadata(db, fid, adapter=adapter)

        assert r["status"] == "ok"
        assert adapter.fetch_metadata.call_args[0][0] == "11223344"


# ---------------------------------------------------------------------------
# TestInvalidIdNoFilenameMatch — 비숫자 DB + 파일명도 파싱 불가 → no_artwork_id
# ---------------------------------------------------------------------------

class TestInvalidIdNoFilenameMatch:
    def test_no_artwork_id_when_db_invalid_and_filename_unparseable(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """DB artwork_id가 비숫자이고 파일명도 Pixiv 형식이 아니면 no_artwork_id 오류."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        img = tmp_path / "my_drawing.jpg"   # Pixiv 형식 아님
        _make_jpg(img)
        _insert_group(db, gid, "d43965258a880b20", source_site="local")
        _insert_file(db, fid, gid, str(img))

        adapter = MagicMock()
        r = fetch_and_store_pixiv_metadata(db, fid, adapter=adapter)

        assert r["status"] == "error"
        assert r["error"] == "no_artwork_id"
        # Pixiv API 호출 없음
        adapter.fetch_metadata.assert_not_called()

    def test_pixiv_api_not_called_for_invalid_id(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """비숫자 artwork_id로는 Pixiv API가 절대 호출되지 않는다."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        img = tmp_path / "non_pixiv_file.jpg"
        _make_jpg(img)
        _insert_group(db, gid, "abc123xyz", source_site="local")
        _insert_file(db, fid, gid, str(img))

        adapter = MagicMock()
        fetch_and_store_pixiv_metadata(db, fid, adapter=adapter)
        adapter.fetch_metadata.assert_not_called()


# ---------------------------------------------------------------------------
# TestEmptyDbArtworkId — DB artwork_id가 빈 문자열/None → 기존 fallback 유지
# ---------------------------------------------------------------------------

class TestEmptyDbArtworkId:
    def test_empty_db_id_falls_back_to_filename(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """DB artwork_id가 빈 문자열이면 기존 동작대로 파일명 파싱."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        img = tmp_path / "55667788_p0.jpg"
        _make_jpg(img)
        _insert_group(db, gid, "")   # 빈 artwork_id
        _insert_file(db, fid, gid, str(img))

        adapter = _make_adapter("55667788")
        r = fetch_and_store_pixiv_metadata(db, fid, adapter=adapter)

        assert r["status"] == "ok"
        adapter.fetch_metadata.assert_called_once_with("55667788")


# ---------------------------------------------------------------------------
# TestBuildEnrichmentQueue — 큐가 file_id를 올바르게 반환하는지
# ---------------------------------------------------------------------------

class TestBuildEnrichmentQueue:
    def test_queue_returns_file_ids_not_group_ids(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """build_enrichment_queue는 file_id를 반환한다 (group_id가 아님)."""
        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        assert gid != fid   # 두 값이 다름을 보장

        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_group(db, gid, "12345678")
        _insert_file(db, fid, gid, str(img))

        queue = build_enrichment_queue(db, mode="missing_only")

        assert fid in queue, "file_id가 queue에 없음"
        assert gid not in queue, "group_id가 file_id 자리에 들어있음"

    def test_queue_includes_hash_placeholder_groups(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """hash placeholder artwork_id 가진 파일도 큐에 포함 (Phase 1에서 fallback 처리)."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_group(db, gid, "d43965258a880b20", source_site="local")
        _insert_file(db, fid, gid, str(img))

        queue = build_enrichment_queue(db, mode="missing_only")
        assert fid in queue

    def test_phase1_receives_correct_file_id(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """_EnrichThread가 큐에서 받은 file_id를 그대로 Phase 1에 전달한다 (group_id 혼동 없음)."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_group(db, gid, "12345678")
        _insert_file(db, fid, gid, str(img))

        captured_file_ids: list[str] = []

        original_fn = fetch_and_store_pixiv_metadata

        def capturing_phase1(conn, file_id, adapter=None):
            captured_file_ids.append(file_id)
            return {"status": "error", "phase": "fetch_store",
                    "group_id": gid, "file_id": file_id,
                    "sync_status": None, "message": "test stop", "error": "network_error"}

        with patch("core.metadata_enricher.fetch_and_store_pixiv_metadata", side_effect=capturing_phase1):
            # _EnrichThread 오케스트레이션을 함수 레벨로 재현
            from core.metadata_enricher import build_enrichment_queue as bq
            from core.metadata_enricher import fetch_and_store_pixiv_metadata as p1
            file_ids = bq(db, mode="missing_only")
            for file_id in file_ids:
                p1(db, file_id, adapter=None)

        assert fid in captured_file_ids
        assert gid not in captured_file_ids, "group_id가 Phase 1에 전달됨"


# ---------------------------------------------------------------------------
# TestBatchPartialInvalidId — 배치 중 일부 invalid → 해당 건만 실패
# ---------------------------------------------------------------------------

class TestBatchPartialInvalidId:
    def test_batch_with_mixed_ids(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """배치 3건 중 1건이 비숫자+비파싱 → fetch_failed=1, 나머지 2건 정상."""
        # 정상 파일 2개
        gid1, fid1 = str(uuid.uuid4()), str(uuid.uuid4())
        gid2, fid2 = str(uuid.uuid4()), str(uuid.uuid4())
        img1 = tmp_path / "11111111_p0.jpg"
        img2 = tmp_path / "22222222_p0.jpg"
        _make_jpg(img1)
        _make_jpg(img2)
        _insert_group(db, gid1, "11111111")
        _insert_file(db, fid1, gid1, str(img1))
        _insert_group(db, gid2, "22222222")
        _insert_file(db, fid2, gid2, str(img2))

        # 비숫자 artwork_id + 파싱 불가 파일명
        gid3, fid3 = str(uuid.uuid4()), str(uuid.uuid4())
        img3 = tmp_path / "my_art.jpg"
        _make_jpg(img3)
        _insert_group(db, gid3, "ec459c7e061361d5", source_site="local")
        _insert_file(db, fid3, gid3, str(img3))

        adapter1 = _make_adapter("11111111")
        adapter2 = _make_adapter("22222222")

        fetch_success = fetch_failed = 0
        write_targets: list[str] = []

        for fid, adapter in [(fid1, adapter1), (fid2, adapter2), (fid3, None)]:
            r = fetch_and_store_pixiv_metadata(
                db, fid,
                adapter=adapter if adapter else MagicMock(),
            )
            if r["status"] == "ok":
                fetch_success += 1
                write_targets.append(fid)
            else:
                fetch_failed += 1

        assert fetch_success == 2
        assert fetch_failed == 1
        assert fid3 not in write_targets

    def test_invalid_id_failure_does_not_stop_batch(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """비숫자 artwork_id 항목이 실패해도 배치 전체가 중단되지 않는다."""
        ids = []
        for i, artwork_id in enumerate(["11111111", "d43965258a880b20", "33333333"]):
            gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
            if artwork_id.isdigit():
                img = tmp_path / f"{artwork_id}_p0.jpg"
            else:
                img = tmp_path / f"non_pixiv_{i}.jpg"
            _make_jpg(img)
            source = "pixiv" if artwork_id.isdigit() else "local"
            _insert_group(db, gid, artwork_id, source_site=source)
            _insert_file(db, fid, gid, str(img))
            ids.append((fid, artwork_id.isdigit()))

        results = []
        for fid, is_valid in ids:
            adapter = _make_adapter() if is_valid else MagicMock()
            r = fetch_and_store_pixiv_metadata(db, fid, adapter=adapter)
            results.append(r["status"])

        assert results.count("ok") == 2
        assert results.count("error") == 1
        assert results[1] == "error"   # 중간 항목 실패
        # 배치가 중단되지 않아 결과가 3개 모두 있음
        assert len(results) == 3
