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

class TestReprocessGroupStatusDowngradeGuard:
    """reprocess_group 이 의미 있는 status 를 약화시키지 않는다.

    Wizard "XMP 데이터 입력" 버튼이 InboxScanner.reprocess_group 을 호출해
    기존 ``full`` group 을 ``json_only`` 로 강등시키던 회귀를 차단한다.
    진정한 XMP 재등록은 xmp_retry / explorer_meta_repair 가 담당하며 그
    경로에서만 status 를 ``full`` 로 끌어올린다.
    """

    @staticmethod
    def _make_png_with_aru(tmp_path):
        png_path = tmp_path / "embed.png"
        _write_png_with_aru_metadata(png_path, {
            "schema_version": "1.0",
            "source_site": "pixiv",
            "artwork_id": "12345",
            "tags": ["t1"],
            "series_tags": ["Blue Archive"],
            "character_tags": ["伊落マリー"],
        })
        return png_path

    @staticmethod
    def _setup_group(db, *, file_path, sync_status):
        gid, _ = _insert_group_with_file(
            db, file_path=str(file_path), file_format="png",
            metadata_embedded=1, sync_status=sync_status,
        )
        return gid

    @staticmethod
    def _read_status(db, gid: str) -> str:
        return db.execute(
            "SELECT metadata_sync_status FROM artwork_groups WHERE group_id=?",
            (gid,),
        ).fetchone()["metadata_sync_status"]

    def test_full_status_preserved_after_reprocess(self, db, tmp_path):
        """기존 'full' group 은 reprocess 후에도 그대로 'full' 유지."""
        png = self._make_png_with_aru(tmp_path)
        gid = self._setup_group(db, file_path=png, sync_status="full")
        scanner = _make_scanner(db, tmp_path)
        scanner.reprocess_group(gid)
        assert self._read_status(db, gid) == "full", (
            "reprocess가 기존 'full'을 강등시킴 — Wizard XMP 입력 회귀"
        )

    def test_xmp_write_failed_preserved_after_reprocess(self, db, tmp_path):
        """xmp_write_failed 는 명시 retry 경로로만 해소되어야 한다."""
        png = self._make_png_with_aru(tmp_path)
        gid = self._setup_group(db, file_path=png, sync_status="xmp_write_failed")
        scanner = _make_scanner(db, tmp_path)
        scanner.reprocess_group(gid)
        assert self._read_status(db, gid) == "xmp_write_failed"

    def test_metadata_write_failed_preserved_after_reprocess(self, db, tmp_path):
        png = self._make_png_with_aru(tmp_path)
        gid = self._setup_group(db, file_path=png, sync_status="metadata_write_failed")
        scanner = _make_scanner(db, tmp_path)
        scanner.reprocess_group(gid)
        assert self._read_status(db, gid) == "metadata_write_failed"

    def test_source_unavailable_preserved_after_reprocess(self, db, tmp_path):
        png = self._make_png_with_aru(tmp_path)
        gid = self._setup_group(db, file_path=png, sync_status="source_unavailable")
        scanner = _make_scanner(db, tmp_path)
        scanner.reprocess_group(gid)
        assert self._read_status(db, gid) == "source_unavailable"

    def test_metadata_missing_upgraded_when_aru_metadata_found(self, db, tmp_path):
        """metadata_missing 은 reprocess 가 embedded JSON 발견 시 정당한 강화."""
        png = self._make_png_with_aru(tmp_path)
        gid = self._setup_group(db, file_path=png, sync_status="metadata_missing")
        scanner = _make_scanner(db, tmp_path)
        scanner.reprocess_group(gid)
        # 보호 대상이 아니므로 reprocess 결과 'json_only' 로 갱신.
        assert self._read_status(db, gid) == "json_only"

    def test_pending_upgraded_when_aru_metadata_found(self, db, tmp_path):
        png = self._make_png_with_aru(tmp_path)
        gid = self._setup_group(db, file_path=png, sync_status="pending")
        scanner = _make_scanner(db, tmp_path)
        scanner.reprocess_group(gid)
        assert self._read_status(db, gid) == "json_only"

    def test_full_preserved_when_metadata_lookup_returns_none(self, db, tmp_path):
        """원본에서 임베디드 JSON 을 못 읽어도 기존 'full' 은 유지.

        scanner 의 reprocess 결과는 'metadata_missing' 이지만,
        full 보호 정책에 의해 강등되지 않는다.
        """
        png_path = tmp_path / "blank.png"
        # 유효 PNG 만, Aru iTXt 없음.
        png_path.write_bytes(b"\x89PNG\r\n\x1a\n")
        gid = self._setup_group(db, file_path=png_path, sync_status="full")
        scanner = _make_scanner(db, tmp_path)
        scanner.reprocess_group(gid)
        assert self._read_status(db, gid) == "full"

    def test_helper_unit_decisions(self):
        from core.inbox_scanner import _reprocess_should_overwrite_status
        # 보호 대상 + downgrade-result → False (보존)
        assert _reprocess_should_overwrite_status("full", "json_only") is False
        assert _reprocess_should_overwrite_status("full", "metadata_missing") is False
        assert _reprocess_should_overwrite_status("xmp_write_failed", "json_only") is False
        assert _reprocess_should_overwrite_status("metadata_write_failed", "metadata_missing") is False
        assert _reprocess_should_overwrite_status("source_unavailable", "json_only") is False
        # 보호 대상이지만 결과가 downgrade-result 가 아닌 경우 → True (정당한 강화 가능)
        assert _reprocess_should_overwrite_status("full", "convert_failed") is True
        # 비보호 상태 → 항상 True
        assert _reprocess_should_overwrite_status("metadata_missing", "json_only") is True
        assert _reprocess_should_overwrite_status("pending", "json_only") is True
        assert _reprocess_should_overwrite_status("json_only", "metadata_missing") is True


class TestReregistrationPipelineConsistency:
    """진정한 재등록 경로 (xmp_retry / explorer_meta_repair) 가
    write_xmp_metadata_with_exiftool 의 clear-first 옵션을 사용한다 — PR #116
    회귀 invariant. PR #116 직후 main 에 있어야 하므로 source-grep 으로 lock."""

    def test_xmp_retry_uses_clear_first(self):
        import inspect
        import core.xmp_retry as mod
        src = inspect.getsource(mod)
        assert "clear_windows_xp_fields_before_write=True" in src

    def test_explorer_meta_repair_uses_clear_first(self):
        import inspect
        import core.explorer_meta_repair as mod
        src = inspect.getsource(mod)
        assert "clear_windows_xp_fields_before_write=True" in src

    def test_inbox_scanner_does_not_call_xmp_writer(self):
        """InboxScanner 는 file scan 모듈 — XMP write 호출하지 않는다.

        Wizard 'XMP 데이터 입력' 이 InboxScanner 를 거쳐 결과적으로 XMP
        재등록 pipeline 을 우회하므로, status 는 보존되고 XMP write 는
        명시 경로만 수행하는 분리가 유지된다.
        """
        import inspect
        import core.inbox_scanner as mod
        src = inspect.getsource(mod)
        assert "write_xmp_metadata_with_exiftool" not in src
        assert "write_windows_exif_fields" not in src


class TestEnrichmentQueueProtectsJsonOnly:
    """build_enrichment_queue all_pixiv 모드가 json_only 를 보호하는지."""

    def test_all_pixiv_excludes_json_only_with_real_file(self, db, tmp_path):
        from core.metadata_enricher import build_enrichment_queue

        png_path = tmp_path / "json_only.png"
        png_path.write_bytes(b"x")

        _, fid = _insert_group_with_file(
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

        _, fid = _insert_group_with_file(
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
