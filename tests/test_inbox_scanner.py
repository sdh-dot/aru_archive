"""tests/test_inbox_scanner.py

``InboxScanner.reprocess_group`` 의 회귀 테스트.

핵심 invariant:
- 파일에 임베딩된 Aru JSON 이 있는 group 을 reprocess_group 했을 때
  metadata_sync_status 가 ``metadata_missing`` 으로 강등되지 않아야 한다.
  과거 ``existing_meta=None`` hardcode 버그가 있어 모든 JPEG/PNG/WebP 가
  강제로 metadata_missing 으로 떨어졌다. 본 테스트는 그 회귀를 lock 한다.

테스트 정책:
- 실제 파일 시스템 사용 (tmp_path) — read_aru_metadata 가 real I/O 에 의존
- offscreen Qt 환경 불필요 (UI 없음)
- DB 는 임시 SQLite 파일에서 ``initialize_database`` 로 부트스트랩
"""
from __future__ import annotations

import json
import sqlite3
import struct
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database

    conn = initialize_database(str(tmp_path / "scanner.db"))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_png_with_aru_metadata(path: Path, payload: dict) -> None:
    """Write a minimal PNG file containing an iTXt chunk with Aru JSON.

    PNG signature + IHDR + iTXt(AruArchive=<json>) + IEND.
    Sufficient for ``core.metadata_reader._read_png_itxt`` to extract the dict.
    """
    PNG_SIG = b"\x89PNG\r\n\x1a\n"

    def _chunk(ctype: bytes, data: bytes) -> bytes:
        # length(4) + type(4) + data + crc(4). CRC value is not validated by
        # our reader; we use a zero placeholder.
        return struct.pack(">I", len(data)) + ctype + data + b"\x00\x00\x00\x00"

    # IHDR: 1x1, 8-bit RGB
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    # iTXt: keyword=AruArchive\0 cflag=0 cmethod=0 lang\0 trans\0 text
    text = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    itxt = b"AruArchive\x00\x00\x00\x00\x00" + text
    body = PNG_SIG + _chunk(b"IHDR", ihdr) + _chunk(b"iTXt", itxt) + _chunk(b"IEND", b"")
    path.write_bytes(body)


def _insert_group_with_file(
    conn: sqlite3.Connection,
    *,
    file_path: str,
    file_format: str = "png",
    metadata_embedded: int = 1,
    sync_status: str = "metadata_missing",
) -> tuple[str, str]:
    gid = str(uuid.uuid4())
    fid = str(uuid.uuid4())
    now = _now()
    conn.execute(
        "INSERT INTO artwork_groups "
        "(group_id, source_site, artwork_id, artwork_title, "
        " downloaded_at, indexed_at, metadata_sync_status, tags_json) "
        "VALUES (?, 'pixiv', ?, '제목', ?, ?, ?, '[]')",
        (gid, gid[:12], now, now, sync_status),
    )
    conn.execute(
        "INSERT INTO artwork_files "
        "(file_id, group_id, page_index, file_role, file_path, "
        " file_format, metadata_embedded, file_status, created_at) "
        "VALUES (?, ?, 0, 'original', ?, ?, ?, 'present', ?)",
        (fid, gid, file_path, file_format, metadata_embedded, now),
    )
    conn.commit()
    return gid, fid


def _make_scanner(conn, tmp_path):
    from core.inbox_scanner import InboxScanner

    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    return InboxScanner(
        conn,
        str(data_dir),
        managed_dir=str(tmp_path / "managed"),
        log_fn=lambda *_: None,
    )


# ---------------------------------------------------------------------------
# 1. existing_meta=None hardcode regression
# ---------------------------------------------------------------------------

class TestReprocessGroupRespectsEmbeddedMetadata:
    """파일에 Aru JSON 이 박혀 있으면 reprocess 후에도 json_only 유지."""

    def test_png_with_aru_metadata_stays_json_only(self, db, tmp_path):
        """PNG 에 임베딩된 Aru JSON 이 있으면 status 가 json_only 로 유지된다.

        과거 reprocess_group 이 _process_by_format 에 existing_meta=None 을
        hardcode 했기 때문에 JPEG/PNG/WebP 분기가 항상 metadata_missing 을
        반환했다. 본 테스트는 그 강등 회귀를 차단한다.
        """
        png_path = tmp_path / "with_meta.png"
        _write_png_with_aru_metadata(png_path, {
            "schema_version": "1.0",
            "source_site": "pixiv",
            "artwork_id": "12345",
            "artwork_title": "테스트",
            "tags": ["일반태그"],
            "series_tags": ["Blue Archive"],
            "character_tags": ["伊落マリー"],
        })

        gid, _ = _insert_group_with_file(
            db, file_path=str(png_path), file_format="png",
            metadata_embedded=1, sync_status="metadata_missing",
        )

        scanner = _make_scanner(db, tmp_path)
        result = scanner.reprocess_group(gid)
        assert result == "new"

        new_status = db.execute(
            "SELECT metadata_sync_status FROM artwork_groups WHERE group_id=?",
            (gid,),
        ).fetchone()["metadata_sync_status"]
        assert new_status == "json_only", (
            f"reprocess 가 status 를 강등시킴: {new_status!r} "
            "— existing_meta=None hardcode 회귀"
        )

    def test_png_without_aru_metadata_returns_metadata_missing(self, db, tmp_path):
        """Aru JSON 이 없는 PNG 는 종전대로 metadata_missing 반환."""
        png_path = tmp_path / "blank.png"
        # PNG signature 만 있고 iTXt 없음 — read_aru_metadata 가 None 반환.
        png_path.write_bytes(b"\x89PNG\r\n\x1a\n")

        gid, _ = _insert_group_with_file(
            db, file_path=str(png_path), file_format="png",
            metadata_embedded=0, sync_status="metadata_missing",
        )

        scanner = _make_scanner(db, tmp_path)
        scanner.reprocess_group(gid)

        new_status = db.execute(
            "SELECT metadata_sync_status FROM artwork_groups WHERE group_id=?",
            (gid,),
        ).fetchone()["metadata_sync_status"]
        assert new_status == "metadata_missing"

    def test_existing_meta_passed_to_process_by_format(self, db, tmp_path, monkeypatch):
        """_process_by_format 호출 시 None 이 아닌 dict 가 전달돼야 한다."""
        from core.inbox_scanner import InboxScanner

        png_path = tmp_path / "probe.png"
        _write_png_with_aru_metadata(png_path, {
            "schema_version": "1.0",
            "source_site": "pixiv",
            "artwork_id": "99999",
            "tags": ["t1"],
        })

        gid, _ = _insert_group_with_file(
            db, file_path=str(png_path), file_format="png",
            metadata_embedded=1, sync_status="metadata_missing",
        )

        captured: dict = {}

        scanner = _make_scanner(db, tmp_path)
        original_pbf = scanner._process_by_format

        def _spy(file_path, file_format, group_id, original_file_id, existing_meta, now):
            captured["existing_meta"] = existing_meta
            return original_pbf(file_path, file_format, group_id, original_file_id, existing_meta, now)

        monkeypatch.setattr(scanner, "_process_by_format", _spy)
        scanner.reprocess_group(gid)

        assert "existing_meta" in captured, "_process_by_format 가 호출되지 않음"
        assert captured["existing_meta"] is not None, (
            "existing_meta 가 여전히 None hardcode 임 — 회귀"
        )
        assert captured["existing_meta"].get("artwork_id") == "99999"

    def test_unreadable_file_falls_back_to_none(self, db, tmp_path, monkeypatch):
        """read_aru_metadata 가 예외를 던져도 reprocess 가 죽지 않는다.

        예외 시 existing_meta=None 으로 두고 형식별 핸들러의 metadata_missing
        분기로 들어가도 무방. 핵심은 reprocess_group 자체가 raise 하지 않는 것.
        """
        png_path = tmp_path / "boom.png"
        png_path.write_bytes(b"\x89PNG\r\n\x1a\n")

        gid, _ = _insert_group_with_file(
            db, file_path=str(png_path), file_format="png",
            metadata_embedded=0, sync_status="metadata_missing",
        )

        # read_aru_metadata 가 예외를 던지도록 monkey-patch.
        import core.inbox_scanner as scanner_mod

        def _raise(*_args, **_kw):
            raise RuntimeError("simulated reader failure")

        monkeypatch.setattr(scanner_mod, "read_aru_metadata", _raise)

        scanner = _make_scanner(db, tmp_path)
        # 예외가 reprocess_group 밖으로 새 나오면 회귀.
        result = scanner.reprocess_group(gid)
        assert result in ("new", "skipped")


# ---------------------------------------------------------------------------
# 2. all_pixiv json_only protection invariant — cross-module integration
# ---------------------------------------------------------------------------

class TestEnrichmentQueueProtectsJsonOnly:
    """build_enrichment_queue all_pixiv 모드가 json_only 를 보호하는지."""

    def test_all_pixiv_excludes_json_only_with_real_file(self, db, tmp_path):
        from core.metadata_enricher import build_enrichment_queue

        png_path = tmp_path / "json_only.png"
        png_path.write_bytes(b"x")

        gid, fid = _insert_group_with_file(
            db, file_path=str(png_path), file_format="png",
            metadata_embedded=1, sync_status="json_only",
        )

        result = build_enrichment_queue(db, mode="all_pixiv")
        assert fid not in result, (
            "json_only group 이 all_pixiv enrichment 대상에 포함됨 — "
            "분류 데이터 손상 회귀"
        )

    def test_all_pixiv_still_includes_metadata_missing(self, db, tmp_path):
        from core.metadata_enricher import build_enrichment_queue

        png_path = tmp_path / "missing.png"
        png_path.write_bytes(b"x")

        gid, fid = _insert_group_with_file(
            db, file_path=str(png_path), file_format="png",
            metadata_embedded=0, sync_status="metadata_missing",
        )

        result = build_enrichment_queue(db, mode="all_pixiv")
        assert fid in result

    def test_all_pixiv_still_includes_failed_statuses(self, db, tmp_path):
        from core.metadata_enricher import build_enrichment_queue

        for idx, status in enumerate(("metadata_write_failed", "xmp_write_failed")):
            png = tmp_path / f"{status}.png"
            png.write_bytes(b"x")
            _insert_group_with_file(
                db, file_path=str(png), file_format="png",
                metadata_embedded=0, sync_status=status,
            )

        result = build_enrichment_queue(db, mode="all_pixiv")
        assert len(result) == 2
