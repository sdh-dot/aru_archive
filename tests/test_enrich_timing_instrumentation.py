"""enrich_timing instrumentation 회귀 테스트.

검증 대상:
- core.metadata_enricher._is_timing_enabled 게이트
- enrich_file_from_pixiv 결과 dict의 옵셔널 timings 키
- enrich_timing logger 출력
- core.metadata_writer.write_xmp_metadata_with_exiftool의 exiftool_call 로그

외부 의존:
- 실제 Pixiv 네트워크 호출 금지 (MagicMock adapter)
- 실제 exiftool binary 호출 금지 (subprocess.run 패치)
- 실제 이미지: io.BytesIO + PIL로 합성한 1×1 JPEG
"""
from __future__ import annotations

import io
import logging
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 픽스처 / 헬퍼 (test_metadata_enricher.py 패턴 재사용)
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    db_path = str(tmp_path / "timing_test.db")
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
    page_index: int = 0,
) -> None:
    now = "2024-01-01T00:00:00+00:00"
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path, file_format, created_at)
           VALUES (?, ?, ?, 'original', ?, ?, ?)""",
        (file_id, group_id, page_index, file_path, file_format, now),
    )
    conn.commit()


def _make_jpeg(path: Path) -> Path:
    """1×1 JPEG (piexif가 EXIF 삽입 가능한 최소 형태)."""
    from PIL import Image as PILImage
    buf = io.BytesIO()
    PILImage.new("RGB", (1, 1), (128, 64, 32)).save(buf, format="JPEG")
    path.write_bytes(buf.getvalue())
    return path


def _make_adapter(body: dict) -> MagicMock:
    """fetch_metadata + to_aru_metadata mock된 adapter."""
    from core.models import AruMetadata
    adapter = MagicMock()
    adapter.fetch_metadata.return_value = body
    meta = AruMetadata(
        artwork_id=body.get("illustId", "123"),
        artwork_title=body.get("title", "Test"),
        artist_id="999",
        artist_name="Artist",
        artist_url="https://www.pixiv.net/users/999",
        tags=["tag1"],
        downloaded_at=datetime.now(timezone.utc).isoformat(),
        _provenance={
            "source": "pixiv_ajax_api", "confidence": "high",
            "captured_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    adapter.to_aru_metadata.return_value = meta
    return adapter


# ---------------------------------------------------------------------------
# Test 1 — 비활성 default: timings 키 없음
# ---------------------------------------------------------------------------

class TestTimingDisabled:
    def test_timing_disabled_no_timings_key(
        self,
        db: sqlite3.Connection,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """env 미설정 시 result에 timings 키 부재 + enrich_timing 로그 0건."""
        # 활성화 env가 우연히 켜져 있을 가능성 차단
        monkeypatch.delenv("ARU_ENRICH_TIMING", raising=False)
        monkeypatch.delenv("ARU_ARCHIVE_DEV_MODE", raising=False)

        img = _make_jpeg(tmp_path / "12345678_p0.jpg")
        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, "12345678")
        _insert_file(db, fid, gid, str(img), "jpg")

        body = {
            "illustId": "12345678", "title": "T", "userId": "1",
            "userName": "U", "pageCount": 1, "illustType": 0,
            "tags": {"tags": []},
        }
        adapter = _make_adapter(body=body)

        from core.metadata_enricher import enrich_file_from_pixiv
        with caplog.at_level(logging.INFO, logger="core.metadata_enricher"):
            result = enrich_file_from_pixiv(db, fid, adapter=adapter)

        assert result["status"] == "success"
        # timings 키가 없거나 빈 dict (스펙: 비활성 시 추가하지 않음)
        timings = result.get("timings")
        assert timings is None or timings == {}, (
            f"timing 비활성인데 timings 키가 채워짐: {timings}"
        )
        # enrich_timing 로그도 0건이어야 함
        # 메시지 시작 패턴으로 매칭 (basetemp 경로에 우연히 토큰 포함될 가능성 차단)
        assert not any(
            r.getMessage().startswith("enrich_timing ")
            for r in caplog.records
        ), "timing 비활성인데 enrich_timing 로그가 출력됨"


# ---------------------------------------------------------------------------
# Test 2 — env 활성화: timings dict + 9 stage + total
# ---------------------------------------------------------------------------

_EXPECTED_STAGES = (
    "db_lookup",
    "parse_filename",
    "pixiv_fetch",
    "to_aru_meta",
    "write_aru",
    "write_xmp",
    "db_update",
    "tag_observe_candidate",
    "total",
)


class TestTimingEnabled:
    def test_timing_enabled_via_env_attaches_timings(
        self,
        db: sqlite3.Connection,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """ARU_ENRICH_TIMING=1 시 timings dict + 9 stage 키 + 0 이상 값 + 로그 출력."""
        monkeypatch.setenv("ARU_ENRICH_TIMING", "1")

        img = _make_jpeg(tmp_path / "98765432_p0.jpg")
        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, "98765432")
        _insert_file(db, fid, gid, str(img), "jpg")

        body = {
            "illustId": "98765432", "title": "Timing Test", "userId": "777",
            "userName": "TimingArtist", "pageCount": 1, "illustType": 0,
            "tags": {"tags": [{"tag": "ts"}]},
        }
        adapter = _make_adapter(body=body)

        from core.metadata_enricher import enrich_file_from_pixiv
        with caplog.at_level(logging.INFO, logger="core.metadata_enricher"):
            result = enrich_file_from_pixiv(db, fid, adapter=adapter)

        assert result["status"] == "success"
        # timings dict + 9 stage 키 모두 존재 + 값 ≥ 0
        timings = result.get("timings")
        assert isinstance(timings, dict) and timings, (
            "timing 활성인데 timings 키가 부재 또는 빈 dict"
        )
        for stage in _EXPECTED_STAGES:
            assert stage in timings, f"{stage} 키 누락: {sorted(timings.keys())}"
            assert timings[stage] >= 0.0, (
                f"{stage} 값이 음수: {timings[stage]}"
            )

        # enrich_timing 로그 1건 이상 출력
        # 메시지 시작 패턴으로 매칭 (basetemp 경로에 우연히 enrich_timing 토큰이 포함될 수 있음)
        timing_logs = [
            r for r in caplog.records
            if r.getMessage().startswith("enrich_timing ")
        ]
        assert len(timing_logs) >= 1, (
            "enrich_timing 로그가 출력되지 않음"
        )

        # basename만 노출되고 절대 경로는 노출되지 않아야 함
        msg = timing_logs[0].getMessage()
        assert "98765432_p0.jpg" in msg
        # 절대 경로의 디렉터리 부분이 들어가 있으면 실패
        # (Windows: tmp_path가 보통 C:\... 또는 E:\... drive 포함)
        parent_str = str(img.parent)
        assert parent_str not in msg, (
            f"enrich_timing 로그에 절대 경로가 노출됨: parent={parent_str!r} msg={msg!r}"
        )

        # 9 stage가 키-값 형태로 메시지에 포함되어 있는지 (느슨한 검증)
        for stage_label in (
            "db_lookup=", "parse=", "fetch=", "aru_meta=",
            "write_aru=", "write_xmp=", "db_update=", "tag_post=", "total=",
        ):
            assert stage_label in msg, (
                f"로그 메시지에 stage 라벨 부재: {stage_label!r} msg={msg!r}"
            )


# ---------------------------------------------------------------------------
# Test 3 — exiftool_call 로그 (subprocess.run 모킹)
# ---------------------------------------------------------------------------

class TestExiftoolCallLog:
    def test_exiftool_call_log_emitted(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """write_xmp_metadata_with_exiftool 호출 시 exiftool_call 로그 1건 + key 필드 포함."""
        monkeypatch.setenv("ARU_ENRICH_TIMING", "1")

        # 실제 ExifTool 호출 차단: validate + subprocess.run 모두 mock
        from core import metadata_writer

        fake_completed = MagicMock()
        fake_completed.returncode = 0
        fake_completed.stdout = b""
        fake_completed.stderr = b""

        # validate_exiftool_path가 True를 반환해 통과시키도록 패치
        # (core.exiftool 모듈에 정의되어 있고 metadata_writer 함수가 from-import)
        from core import exiftool as exiftool_mod
        monkeypatch.setattr(
            exiftool_mod, "validate_exiftool_path", lambda _path: True
        )
        # subprocess.run을 모킹해 실제 binary 실행 0건
        run_mock = MagicMock(return_value=fake_completed)
        monkeypatch.setattr(metadata_writer.subprocess, "run", run_mock)

        # 더미 metadata + 가짜 exiftool 경로
        fake_path = str(tmp_path / "fake_exiftool.exe")
        # 빈 파일이라도 만들어 두면 caller 측 다른 검증이 통과 (validate는 위에서 mock으로 우회)
        Path(fake_path).write_bytes(b"")
        target_file = str(tmp_path / "12345678_p0.jpg")
        _make_jpeg(Path(target_file))

        meta = {
            "artwork_title": "Test",
            "artist_name": "Tester",
            "tags": ["a", "b"],
            "series_tags": [],
            "character_tags": [],
        }

        with caplog.at_level(logging.INFO, logger="core.metadata_writer"):
            ok = metadata_writer.write_xmp_metadata_with_exiftool(
                target_file, meta, exiftool_path=fake_path,
            )

        assert ok is True, "subprocess.run mock이 success를 반환했는데 함수가 False 반환"
        assert run_mock.called, "subprocess.run이 호출되지 않음"

        # exiftool_call 로그 1건 이상
        # 주의: pytest basetemp 경로에 test 함수명이 들어가 다른 로그 메시지의 path 부분에
        #       "exiftool_call" 토큰이 우연히 포함될 수 있어, 메시지 시작 패턴으로 매칭한다.
        ex_logs = [
            r for r in caplog.records
            if r.getMessage().startswith("exiftool_call ")
        ]
        assert len(ex_logs) >= 1, "exiftool_call 로그가 출력되지 않음"

        msg = ex_logs[0].getMessage()
        # 핵심 key=value 필드 포함 검증 (느슨한 매칭)
        assert "elapsed=" in msg, f"elapsed 필드 부재: {msg!r}"
        assert "args=" in msg, f"args 필드 부재: {msg!r}"
        assert "timeout=false" in msg, f"timeout=false 필드 부재: {msg!r}"
        assert "success=true" in msg, f"success=true 필드 부재: {msg!r}"
        # basename만 노출 (절대 경로 부재)
        assert "12345678_p0.jpg" in msg
        parent_str = str(Path(target_file).parent)
        assert parent_str not in msg, (
            f"exiftool_call 로그에 절대 경로 노출: parent={parent_str!r} msg={msg!r}"
        )
