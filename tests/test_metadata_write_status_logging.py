"""
메타데이터 쓰기 로그가 실제 단계와 일치하는지 검증하는 회귀 테스트.

배경:
- 사용자가 다음과 같은 로그를 보고했다.
    14:21:50 ExifTool XP field write failed, falling back to direct EXIF write: ...
    14:21:50 XMP+XP 기록 완료: .../142078187_p0_master1200.jpg
    14:21:50 메타데이터 기록 완료: 142075928_p0_master1200.jpg → json_only
- "메타데이터 기록 완료 → json_only" 로그가 JSON 기록 직후(중간 시점)에
  찍혀 사용자가 최종 상태처럼 오해할 여지가 있었다.
- "XMP+XP 기록 완료" 로그가 primary path 성공인지 fallback path 성공인지
  구분되지 않았다.

본 테스트는 두 가지 로그 변경을 lock 한다.
  1. enricher가 JSON 단계 완료와 최종 sync_status 결정을 분리해 로그한다.
  2. write_xmp_metadata_with_exiftool가 XP fallback 사용 여부를 로그에 표시한다.

DB 스키마, 분류 알고리즘, destination path, 파일 시스템 동작은 변경하지 않는다.
실제 ExifTool 또는 외부 네트워크 호출은 사용하지 않는다.
"""
from __future__ import annotations

import io
import logging
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.metadata_enricher import enrich_file_from_pixiv
from core.metadata_writer import (
    XmpWriteError,
    _write_windows_exif_fields_best_effort,
    write_xmp_metadata_with_exiftool,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_META = {
    "artwork_title": "테스트 작품",
    "artist_name": "테스트 작가",
    "artwork_url": "https://www.pixiv.net/artworks/99999",
    "artwork_id": "99999",
    "source_site": "pixiv",
    "tags": ["오리지널", "배경"],
    "series_tags": [],
    "character_tags": [],
}


@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    db_path = str(tmp_path / "test.db")
    conn = initialize_database(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _insert_group(conn: sqlite3.Connection, group_id: str, artwork_id: str) -> None:
    now = "2024-01-01T00:00:00+00:00"
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, artwork_id, downloaded_at, indexed_at, metadata_sync_status)
           VALUES (?, ?, ?, ?, 'metadata_missing')""",
        (group_id, artwork_id, now, now),
    )
    conn.commit()


def _insert_file(
    conn: sqlite3.Connection,
    file_id: str,
    group_id: str,
    file_path: str,
    file_format: str = "jpg",
) -> None:
    now = "2024-01-01T00:00:00+00:00"
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path, file_format, created_at)
           VALUES (?, ?, 0, 'original', ?, ?, ?)""",
        (file_id, group_id, file_path, file_format, now),
    )
    conn.commit()


def _make_jpeg(path: Path) -> Path:
    """1x1 유효 JPEG 생성 — piexif가 처리할 수 있는 최소 파일."""
    from PIL import Image as PILImage
    buf = io.BytesIO()
    PILImage.new("RGB", (1, 1), (128, 64, 32)).save(buf, format="JPEG")
    path.write_bytes(buf.getvalue())
    return path


def _make_adapter() -> MagicMock:
    from core.models import AruMetadata
    from datetime import datetime, timezone
    adapter = MagicMock()
    adapter.fetch_metadata.return_value = {
        "illustId": "12345678",
        "title": "Test",
        "userId": "1",
        "userName": "X",
        "pageCount": 1,
        "illustType": 0,
        "tags": {"tags": []},
    }
    adapter.to_aru_metadata.return_value = AruMetadata(
        artwork_id="12345678",
        artwork_title="Test",
        artist_id="1",
        artist_name="X",
        artist_url="https://www.pixiv.net/users/1",
        tags=["tag1"],
        downloaded_at=datetime.now(timezone.utc).isoformat(),
        _provenance={
            "source": "pixiv_ajax_api",
            "confidence": "high",
            "captured_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return adapter


# ---------------------------------------------------------------------------
# 1) enricher: JSON-step 로그와 최종-status 로그 분리
# ---------------------------------------------------------------------------

class TestEnricherFinalStatusLog:
    """metadata_enricher.enrich_file_from_pixiv의 로그 단계 분리 검증."""

    def test_json_step_log_does_not_claim_final_status(
        self, db: sqlite3.Connection, tmp_path: Path, caplog
    ) -> None:
        """JSON 기록 직후 로그는 "JSON 메타데이터 기록 완료"로 표시되어야 하며
        sync_status 값을 최종처럼 적지 않아야 한다."""
        img = _make_jpeg(tmp_path / "12345678_p0.jpg")
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678")
        _insert_file(db, fid, gid, str(img), "jpg")

        with caplog.at_level(logging.INFO, logger="core.metadata_enricher"):
            enrich_file_from_pixiv(db, fid, adapter=_make_adapter())

        json_step_messages = [
            r.getMessage() for r in caplog.records
            if r.name == "core.metadata_enricher"
            and r.getMessage().startswith("JSON 메타데이터 기록 완료")
        ]
        assert json_step_messages, (
            "JSON 단계 완료 로그가 'JSON 메타데이터 기록 완료'로 시작해야 한다"
        )
        # 중간 로그에는 sync_status가 포함되지 않아야 한다 (최종 로그에서만).
        assert all("→" not in m for m in json_step_messages), (
            "JSON 단계 로그가 화살표(→)로 sync_status를 표시하면 사용자가 "
            "최종 상태로 오해할 수 있다"
        )

    def test_final_log_reflects_actual_sync_status(
        self, db: sqlite3.Connection, tmp_path: Path, caplog
    ) -> None:
        """JSON+XMP 단계가 모두 끝난 뒤 단일 최종 로그가 기록된다."""
        img = _make_jpeg(tmp_path / "12345678_p0.jpg")
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678")
        _insert_file(db, fid, gid, str(img), "jpg")

        with caplog.at_level(logging.INFO, logger="core.metadata_enricher"):
            result = enrich_file_from_pixiv(db, fid, adapter=_make_adapter())

        # exiftool_path 미지정이므로 XMP 단계는 no-op → 최종 sync_status="json_only"
        assert result["sync_status"] == "json_only"

        final_messages = [
            r.getMessage() for r in caplog.records
            if r.name == "core.metadata_enricher"
            and r.getMessage().startswith("메타데이터 기록 완료")
        ]
        assert len(final_messages) == 1, (
            f"최종 sync_status 로그는 정확히 한 번만 찍혀야 한다. "
            f"실제: {final_messages}"
        )
        assert "→ json_only" in final_messages[0]

    def test_final_log_uses_full_when_xmp_succeeds(
        self, db: sqlite3.Connection, tmp_path: Path, caplog
    ) -> None:
        """XMP 기록이 성공하면 최종 로그는 'full'로 마무리되어야 한다.
        과거 버그: JSON 단계 직후 'json_only' 로그가 나가는 바람에 사용자가
        full 전환을 놓쳤다."""
        img = _make_jpeg(tmp_path / "12345678_p0.jpg")
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678")
        _insert_file(db, fid, gid, str(img), "jpg")

        with patch(
            "core.metadata_enricher.write_xmp_metadata_with_exiftool",
            return_value=True,
        ):
            with caplog.at_level(logging.INFO, logger="core.metadata_enricher"):
                result = enrich_file_from_pixiv(
                    db, fid, adapter=_make_adapter(),
                    exiftool_path="/fake/exiftool",
                )

        assert result["sync_status"] == "full"

        final_messages = [
            r.getMessage() for r in caplog.records
            if r.name == "core.metadata_enricher"
            and r.getMessage().startswith("메타데이터 기록 완료")
        ]
        assert final_messages, "최종 로그가 출력되어야 한다"
        assert "→ full" in final_messages[-1], (
            f"XMP 성공 후 최종 로그는 → full 이어야 한다. 실제: {final_messages[-1]}"
        )
        # JSON-단계 로그에 'json_only' 가 포함되어 사용자를 헷갈리게 만들지 않아야 한다.
        json_step_messages = [
            r.getMessage() for r in caplog.records
            if r.name == "core.metadata_enricher"
            and r.getMessage().startswith("JSON 메타데이터 기록 완료")
        ]
        assert json_step_messages
        assert all("json_only" not in m for m in json_step_messages)

    def test_final_log_uses_xmp_write_failed_when_xmp_raises(
        self, db: sqlite3.Connection, tmp_path: Path, caplog
    ) -> None:
        """XMP 단계가 XmpWriteError를 던지면 최종 sync_status는
        xmp_write_failed로 기록되고, 같은 값이 로그에도 반영되어야 한다."""
        img = _make_jpeg(tmp_path / "12345678_p0.jpg")
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678")
        _insert_file(db, fid, gid, str(img), "jpg")

        with patch(
            "core.metadata_enricher.write_xmp_metadata_with_exiftool",
            side_effect=XmpWriteError("simulated"),
        ):
            with caplog.at_level(logging.INFO, logger="core.metadata_enricher"):
                result = enrich_file_from_pixiv(
                    db, fid, adapter=_make_adapter(),
                    exiftool_path="/fake/exiftool",
                )

        assert result["sync_status"] == "xmp_write_failed"
        final_messages = [
            r.getMessage() for r in caplog.records
            if r.name == "core.metadata_enricher"
            and r.getMessage().startswith("메타데이터 기록 완료")
        ]
        assert final_messages
        assert "→ xmp_write_failed" in final_messages[-1]


# ---------------------------------------------------------------------------
# 2) writer: XMP+XP 성공 로그가 fallback 사용 여부를 명시
# ---------------------------------------------------------------------------

class TestXmpXpSuccessLogIndicatesFallback:
    """write_xmp_metadata_with_exiftool 성공 로그가 primary와 fallback 경로를
    구분하는지 검증한다."""

    def _patched_run_jpeg(self, tmp_path: Path):
        """ExifTool 호출 mock + 1x1 JPEG 파일을 묶어 반환."""
        jpg = tmp_path / "ok.jpg"
        _make_jpeg(jpg)
        mock_result = MagicMock(returncode=0)
        return jpg, mock_result

    def test_primary_xp_success_log_has_no_fallback_marker(
        self, tmp_path: Path, caplog
    ) -> None:
        jpg, mock_result = self._patched_run_jpeg(tmp_path)
        with (
            patch("core.exiftool.validate_exiftool_path", return_value=True),
            patch("core.metadata_writer.subprocess.run", return_value=mock_result),
            patch(
                "core.metadata_writer._write_windows_exif_fields_best_effort",
                return_value="primary",
            ),
            caplog.at_level(logging.INFO, logger="core.metadata_writer"),
        ):
            ok = write_xmp_metadata_with_exiftool(
                str(jpg), SAMPLE_META, "/fake/exiftool"
            )
        assert ok is True
        success_messages = [
            r.getMessage() for r in caplog.records
            if r.name == "core.metadata_writer"
            and r.getMessage().startswith("XMP+XP 기록 완료")
        ]
        assert success_messages, "XMP+XP 성공 로그가 출력되어야 한다"
        assert all("fallback" not in m for m in success_messages), (
            f"primary 경로 성공 시 로그에 fallback 표시가 없어야 한다. "
            f"실제: {success_messages}"
        )

    def test_fallback_xp_success_log_marks_fallback(
        self, tmp_path: Path, caplog
    ) -> None:
        jpg, mock_result = self._patched_run_jpeg(tmp_path)
        with (
            patch("core.exiftool.validate_exiftool_path", return_value=True),
            patch("core.metadata_writer.subprocess.run", return_value=mock_result),
            patch(
                "core.metadata_writer._write_windows_exif_fields_best_effort",
                return_value="fallback",
            ),
            caplog.at_level(logging.INFO, logger="core.metadata_writer"),
        ):
            ok = write_xmp_metadata_with_exiftool(
                str(jpg), SAMPLE_META, "/fake/exiftool"
            )
        assert ok is True
        fallback_messages = [
            r.getMessage() for r in caplog.records
            if r.name == "core.metadata_writer"
            and "fallback" in r.getMessage()
            and "XMP+XP 기록 완료" in r.getMessage()
        ]
        assert fallback_messages, (
            "XP fallback 사용 시 성공 로그가 fallback 표시를 포함해야 한다"
        )

    def test_xp_excluded_log_uses_xmp_only_wording(
        self, tmp_path: Path, caplog
    ) -> None:
        """include_xp_fields=False면 'XMP 기록 완료' 로그가 사용된다 (XP 단어 없음)."""
        jpg, mock_result = self._patched_run_jpeg(tmp_path)
        with (
            patch("core.exiftool.validate_exiftool_path", return_value=True),
            patch("core.metadata_writer.subprocess.run", return_value=mock_result),
            caplog.at_level(logging.INFO, logger="core.metadata_writer"),
        ):
            ok = write_xmp_metadata_with_exiftool(
                str(jpg), SAMPLE_META, "/fake/exiftool",
                include_xp_fields=False,
            )
        assert ok is True
        # XMP 기록 완료 로그가 있고, '+XP' 마커는 포함되지 않아야 한다.
        info_msgs = [
            r.getMessage() for r in caplog.records
            if r.name == "core.metadata_writer"
            and "기록 완료" in r.getMessage()
        ]
        assert info_msgs
        assert all("+XP" not in m for m in info_msgs), (
            f"include_xp_fields=False면 +XP 표시가 없어야 한다. 실제: {info_msgs}"
        )


# ---------------------------------------------------------------------------
# 3) _write_windows_exif_fields_best_effort 반환값 직접 검증
# ---------------------------------------------------------------------------

class TestBestEffortReturnValue:
    """fallback 경로 식별을 caller가 신뢰할 수 있도록 반환값 시그니처 lock."""

    def test_returns_primary_when_exiftool_succeeds(self, tmp_path: Path) -> None:
        jpg = tmp_path / "p.jpg"
        _make_jpeg(jpg)
        with patch(
            "core.metadata_writer.write_windows_exif_fields",
            return_value=True,
        ):
            result = _write_windows_exif_fields_best_effort(
                str(jpg), SAMPLE_META, "/fake/exiftool"
            )
        assert result == "primary"

    def test_returns_fallback_when_exiftool_raises_and_piexif_succeeds(
        self, tmp_path: Path
    ) -> None:
        jpg = tmp_path / "f.jpg"
        _make_jpeg(jpg)
        with (
            patch(
                "core.metadata_writer.write_windows_exif_fields",
                side_effect=XmpWriteError("simulated XP failure"),
            ),
            # piexif direct write는 정상 동작하도록 그대로 둔다.
        ):
            result = _write_windows_exif_fields_best_effort(
                str(jpg), SAMPLE_META, "/fake/exiftool"
            )
        assert result == "fallback"

    def test_returns_fallback_when_exiftool_unavailable(
        self, tmp_path: Path
    ) -> None:
        """exiftool_path=None이면 primary는 시도조차 못 하고 fallback만 남는다."""
        jpg = tmp_path / "n.jpg"
        _make_jpeg(jpg)
        result = _write_windows_exif_fields_best_effort(
            str(jpg), SAMPLE_META, exiftool_path=None
        )
        assert result == "fallback"

    def test_raises_when_both_paths_fail(self, tmp_path: Path) -> None:
        """primary가 raise 하고 piexif fallback도 raise 하면 XmpWriteError 전파."""
        jpg = tmp_path / "bad.jpg"
        # 의도적으로 손상된 JPEG 헤더 → piexif insert 실패 유도.
        jpg.write_bytes(b"\xff\xd8\xff\xd9")
        with patch(
            "core.metadata_writer.write_windows_exif_fields",
            side_effect=XmpWriteError("primary failed"),
        ):
            with pytest.raises(XmpWriteError):
                _write_windows_exif_fields_best_effort(
                    str(jpg), SAMPLE_META, "/fake/exiftool"
                )
