"""
분류 실행 idempotency 테스트.

핵심 invariant:
- 같은 source/group/destination 재실행 → skipped, 오류 아님
- 물리 파일이 있고 DB record 없으면 + 같은 hash → 파일 재사용, DB record 생성
- 다른 group/source가 같은 destination 점유 → ValueError (conflict error)
- copy_records 중복 INSERT 없음
- batch 재실행 시 copied/skipped 집계 정확
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from db.database import initialize_database


# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    conn = initialize_database(str(tmp_path / "idempotency.db"))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _insert_group(
    conn: sqlite3.Connection,
    *,
    group_id: str,
    series: list[str] | None = None,
    character: list[str] | None = None,
) -> None:
    now = _now()
    conn.execute(
        "INSERT INTO artwork_groups "
        "(group_id, source_site, artwork_id, artwork_title, artist_name,"
        " downloaded_at, indexed_at, metadata_sync_status,"
        " tags_json, series_tags_json, character_tags_json) "
        "VALUES (?, 'pixiv', ?, 'test', 'artist_x', ?, ?, 'json_only', '[]', ?, ?)",
        (
            group_id, group_id[:12], now, now,
            json.dumps(series or [], ensure_ascii=False),
            json.dumps(character or [], ensure_ascii=False),
        ),
    )
    conn.commit()


def _insert_source_file(
    conn: sqlite3.Connection, group_id: str, path: Path, content: bytes = b"\xff\xd8\xff\xe0" * 256
) -> str:
    """실제 파일과 artwork_files record를 같이 생성한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    fid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO artwork_files "
        "(file_id, group_id, page_index, file_role, file_path,"
        " file_format, file_size, metadata_embedded, file_status, created_at) "
        "VALUES (?, ?, 0, 'original', ?, 'jpg', ?, 0, 'present', ?)",
        (fid, group_id, str(path), len(content), _now()),
    )
    conn.commit()
    return fid


def _base_config(classified_dir: Path, on_conflict: str = "rename") -> dict:
    return {
        "classified_dir": str(classified_dir),
        "undo_retention_days": 7,
        "classification": {
            "enable_series_character":         True,
            "enable_series_uncategorized":     True,
            "enable_character_without_series": False,
            "fallback_by_author":              True,
            "enable_by_author":                False,
            "enable_by_tag":                   False,
            "on_conflict":                     on_conflict,
            "folder_locale":                   "canonical",
            "allow_multi_destination":         True,
        },
    }


# ---------------------------------------------------------------------------
# 기본 idempotency — execute_classify_preview
# ---------------------------------------------------------------------------

class TestExecuteIdempotency:
    def test_second_run_returns_skipped_not_error(self, db: sqlite3.Connection, tmp_path: Path) -> None:
        """동일 그룹을 두 번 execute_classify_preview 하면 두 번째는 status=skipped."""
        from core.classifier import build_classify_preview, execute_classify_preview

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=["Blue Archive"], character=["陸八魔アル"])
        src = tmp_path / "inbox" / "img.jpg"
        _insert_source_file(db, gid, src)
        classified = tmp_path / "Classified"
        cfg = _base_config(classified)

        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None

        # 1차 실행
        r1 = execute_classify_preview(db, preview, cfg)
        assert r1["status"] == "ok"
        assert r1["copied"] >= 1
        assert r1["error"] is None

        # 2차 실행 — 오류가 아닌 skipped
        r2 = execute_classify_preview(db, preview, cfg)
        assert r2["status"] == "skipped"
        assert r2["copied"] == 0
        assert r2["skipped"] >= 1
        assert r2["error"] is None

    def test_no_duplicate_artwork_files_record(self, db: sqlite3.Connection, tmp_path: Path) -> None:
        """두 번 실행해도 classified_copy record는 1개만 존재한다."""
        from core.classifier import build_classify_preview, execute_classify_preview

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=["Blue Archive"], character=["陸八魔アル"])
        src = tmp_path / "inbox" / "img.jpg"
        _insert_source_file(db, gid, src)
        cfg = _base_config(tmp_path / "Classified")
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None

        execute_classify_preview(db, preview, cfg)
        execute_classify_preview(db, preview, cfg)

        rows = db.execute(
            "SELECT COUNT(*) AS cnt FROM artwork_files "
            "WHERE group_id = ? AND file_role = 'classified_copy'",
            (gid,),
        ).fetchone()
        assert rows["cnt"] == 1

    def test_no_duplicate_copy_records(self, db: sqlite3.Connection, tmp_path: Path) -> None:
        """두 번 실행해도 copy_records는 1개만 존재한다 (두 번째 실행에서 파일 복사 skip)."""
        from core.classifier import build_classify_preview, execute_classify_preview

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=["Blue Archive"], character=["陸八魔アル"])
        src = tmp_path / "inbox" / "img.jpg"
        _insert_source_file(db, gid, src)
        cfg = _base_config(tmp_path / "Classified")
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None

        r1 = execute_classify_preview(db, preview, cfg)
        execute_classify_preview(db, preview, cfg)

        dest_path = Path(preview["destinations"][0]["dest_path"])
        rows = db.execute(
            "SELECT COUNT(*) AS cnt FROM copy_records WHERE dest_path = ?",
            (str(dest_path),),
        ).fetchone()
        # copy_records는 실제 파일 복사(1차)에서만 INSERT됨
        assert rows["cnt"] == 1

    def test_file_not_duplicated_on_filesystem(self, db: sqlite3.Connection, tmp_path: Path) -> None:
        """두 번 실행해도 _1.jpg 같은 중복 파일이 생기지 않는다."""
        from core.classifier import build_classify_preview, execute_classify_preview

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=["Blue Archive"], character=["陸八魔アル"])
        src = tmp_path / "inbox" / "img.jpg"
        _insert_source_file(db, gid, src)
        classified = tmp_path / "Classified"
        cfg = _base_config(classified)
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None

        execute_classify_preview(db, preview, cfg)
        execute_classify_preview(db, preview, cfg)

        # dest 폴더에 _1.jpg 같은 중복 파일이 없어야 한다
        dest_dir = Path(preview["destinations"][0]["dest_path"]).parent
        jpg_files = list(dest_dir.glob("*.jpg"))
        assert len(jpg_files) == 1, f"중복 파일 발생: {jpg_files}"


# ---------------------------------------------------------------------------
# 물리 파일 있음 + DB record 없음 (이전 run에서 DB 기록 실패 케이스)
# ---------------------------------------------------------------------------

class TestPhysicalFileWithoutDbRecord:
    def test_file_exists_same_hash_reused(self, db: sqlite3.Connection, tmp_path: Path) -> None:
        """물리 파일이 있고 hash가 같으면 복사 없이 DB record를 생성한다."""
        from core.classifier import build_classify_preview, execute_classify_preview

        gid = str(uuid.uuid4())
        content = b"\xff\xd8\xff\xe0" * 512
        _insert_group(db, group_id=gid, series=["Blue Archive"], character=["陸八魔アル"])
        src = tmp_path / "inbox" / "img.jpg"
        _insert_source_file(db, gid, src, content)
        cfg = _base_config(tmp_path / "Classified")
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None

        # 물리 파일을 미리 같은 내용으로 복사 (DB record 없음)
        dest_path = Path(preview["destinations"][0]["dest_path"])
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(content)

        # artwork_files에 classified_copy record 없음을 확인
        existing = db.execute(
            "SELECT COUNT(*) AS cnt FROM artwork_files WHERE file_path = ? AND file_role = 'classified_copy'",
            (str(dest_path),),
        ).fetchone()
        assert existing["cnt"] == 0

        # 실행 → 오류 없음, DB record 생성됨
        r = execute_classify_preview(db, preview, cfg)
        assert r["error"] is None
        assert r["copied"] == 1  # 파일 재사용도 "복사 완료"로 집계

        after = db.execute(
            "SELECT COUNT(*) AS cnt FROM artwork_files WHERE file_path = ? AND file_role = 'classified_copy'",
            (str(dest_path),),
        ).fetchone()
        assert after["cnt"] == 1

        # copy_records는 파일 복사가 실제로 발생하지 않았으므로 생성 안 됨 (undo 제외)
        cr = db.execute(
            "SELECT COUNT(*) AS cnt FROM copy_records WHERE dest_path = ?",
            (str(dest_path),),
        ).fetchone()
        assert cr["cnt"] == 0

    def test_file_exists_different_hash_uses_conflict_policy(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """물리 파일이 있지만 hash가 다르면 on_conflict 정책을 적용한다."""
        from core.classifier import build_classify_preview, execute_classify_preview

        gid = str(uuid.uuid4())
        src_content = b"\xff\xd8\xff\xe0" * 512
        _insert_group(db, group_id=gid, series=["Blue Archive"], character=["陸八魔アル"])
        src = tmp_path / "inbox" / "img.jpg"
        _insert_source_file(db, gid, src, src_content)
        cfg = _base_config(tmp_path / "Classified", on_conflict="rename")
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None

        # 다른 내용의 파일을 dest에 미리 배치
        dest_path = Path(preview["destinations"][0]["dest_path"])
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"\x00\x11\x22\x33" * 512)  # 다른 내용

        # on_conflict="rename" → _1.jpg 이름으로 복사됨, 오류 아님
        r = execute_classify_preview(db, preview, cfg)
        assert r["error"] is None
        assert r["copied"] == 1

        # 새 이름 파일이 생겼어야 함
        dest_dir = dest_path.parent
        jpg_files = list(dest_dir.glob("*.jpg"))
        assert len(jpg_files) == 2  # 기존 + 새로 복사된 것


# ---------------------------------------------------------------------------
# 다른 그룹의 destination 점유 → conflict error
# ---------------------------------------------------------------------------

class TestConflictWithAnotherGroup:
    def test_different_group_same_dest_raises(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """다른 그룹이 같은 destination을 점유하면 ValueError가 발생한다."""
        from core.classifier import build_classify_preview, execute_classify_preview

        classified = tmp_path / "Classified"
        cfg = _base_config(classified)

        # 그룹 A
        gid_a = str(uuid.uuid4())
        _insert_group(db, group_id=gid_a, series=["Blue Archive"], character=["陸八魔アル"])
        src_a = tmp_path / "inbox" / "a.jpg"
        _insert_source_file(db, gid_a, src_a)
        preview_a = build_classify_preview(db, gid_a, cfg)
        assert preview_a is not None
        execute_classify_preview(db, preview_a, cfg)

        # 그룹 B — A와 동일한 destination path를 DB에 직접 심음
        gid_b = str(uuid.uuid4())
        _insert_group(db, group_id=gid_b, series=["Blue Archive"], character=["陸八魔アル"])
        src_b = tmp_path / "inbox" / "b.jpg"
        fid_b = _insert_source_file(db, gid_b, src_b)

        # 그룹 B의 preview를 수동으로 구성하되, dest_path를 A와 같게 강제
        dest_a = preview_a["destinations"][0]["dest_path"]
        # B의 dest_path에 해당하는 물리 파일 삭제 (A가 이미 파일 생성)
        preview_b = {
            "group_id":       gid_b,
            "source_file_id": fid_b,
            "source_path":    str(src_b),
            "destinations": [
                {
                    "will_copy": True,
                    "rule_type": "series_character",
                    "dest_path": dest_a,
                    "conflict":  None,
                    "used_fallback": False,
                }
            ],
        }

        with pytest.raises(ValueError, match="already registered for another group"):
            execute_classify_preview(db, preview_b, cfg)

    def test_error_message_contains_path(self, db: sqlite3.Connection, tmp_path: Path) -> None:
        """conflict error 메시지에 destination path가 포함된다."""
        from core.classifier import build_classify_preview, execute_classify_preview

        classified = tmp_path / "Classified"
        cfg = _base_config(classified)

        gid_a = str(uuid.uuid4())
        _insert_group(db, group_id=gid_a, series=["Blue Archive"], character=["陸八魔アル"])
        src_a = tmp_path / "inbox" / "a.jpg"
        _insert_source_file(db, gid_a, src_a)
        preview_a = build_classify_preview(db, gid_a, cfg)
        assert preview_a is not None
        execute_classify_preview(db, preview_a, cfg)

        gid_b = str(uuid.uuid4())
        _insert_group(db, group_id=gid_b, series=["Blue Archive"], character=["陸八魔アル"])
        src_b = tmp_path / "inbox" / "b.jpg"
        fid_b = _insert_source_file(db, gid_b, src_b)

        dest_a = preview_a["destinations"][0]["dest_path"]
        preview_b = {
            "group_id": gid_b, "source_file_id": fid_b, "source_path": str(src_b),
            "destinations": [
                {"will_copy": True, "rule_type": "series_character",
                 "dest_path": dest_a, "conflict": None, "used_fallback": False}
            ],
        }

        with pytest.raises(ValueError) as exc_info:
            execute_classify_preview(db, preview_b, cfg)
        assert str(Path(dest_a)) in str(exc_info.value) or dest_a in str(exc_info.value)


# ---------------------------------------------------------------------------
# batch 재실행 집계 정확성
# ---------------------------------------------------------------------------

class TestBatchIdempotency:
    def test_batch_second_run_no_error(self, db: sqlite3.Connection, tmp_path: Path) -> None:
        """batch를 두 번 실행해도 오류 없이 skipped 집계."""
        from core.classifier import build_classify_preview
        from core.batch_classifier import build_classify_batch_preview, execute_classify_batch

        classified = tmp_path / "Classified"
        cfg = _base_config(classified)

        gids = []
        for i in range(3):
            gid = str(uuid.uuid4())
            _insert_group(db, group_id=gid, series=["Blue Archive"], character=["陸八魔アル"])
            src = tmp_path / "inbox" / f"img{i}.jpg"
            _insert_source_file(db, gid, src, b"\xff\xd8\xff\xe0" * (i + 1) * 64)
            gids.append(gid)

        batch = build_classify_batch_preview(db, gids, cfg)

        # 1차 실행
        r1 = execute_classify_batch(db, batch, cfg)
        assert r1["success"] is True
        assert r1["copied"] == 3
        assert r1["failed_groups"] == 0

        # 2차 실행 — 모두 skipped, 오류 없음
        r2 = execute_classify_batch(db, batch, cfg)
        assert r2["success"] is True
        assert r2["status"] == "completed"   # "failed" 아님
        assert r2["copied"] == 0
        assert r2["skipped"] == 3
        assert r2["failed_groups"] == 0
        assert r2["error"] is None

    def test_batch_mixed_new_and_existing(self, db: sqlite3.Connection, tmp_path: Path) -> None:
        """이미 분류된 그룹과 새 그룹이 섞인 batch → 새 것만 copied, 기존은 skipped."""
        from core.batch_classifier import build_classify_batch_preview, execute_classify_batch

        classified = tmp_path / "Classified"
        cfg = _base_config(classified)

        # 그룹 A: 이미 분류됨
        gid_a = str(uuid.uuid4())
        _insert_group(db, group_id=gid_a, series=["Blue Archive"], character=["陸八魔アル"])
        src_a = tmp_path / "inbox" / "a.jpg"
        _insert_source_file(db, gid_a, src_a, b"\xff\xd8\xff\xe0" * 128)

        batch_a = build_classify_batch_preview(db, [gid_a], cfg)
        execute_classify_batch(db, batch_a, cfg)  # A를 먼저 분류

        # 그룹 B: 새로운 그룹 (다른 캐릭터 태그로 다른 dest)
        gid_b = str(uuid.uuid4())
        _insert_group(db, group_id=gid_b, series=["Blue Archive"], character=["天雨リン"])
        src_b = tmp_path / "inbox" / "b.jpg"
        _insert_source_file(db, gid_b, src_b, b"\x89PNG\r\n" * 128)

        # A + B 함께 batch 실행
        batch_ab = build_classify_batch_preview(db, [gid_a, gid_b], cfg)
        r = execute_classify_batch(db, batch_ab, cfg)

        assert r["success"] is True
        assert r["failed_groups"] == 0
        # B는 copied, A는 skipped
        assert r["copied"] == 1
        assert r["skipped"] == 1

    def test_batch_group_results_schema(self, db: sqlite3.Connection, tmp_path: Path) -> None:
        """group_results에 status/message/error 필드가 있다."""
        from core.batch_classifier import build_classify_batch_preview, execute_classify_batch

        classified = tmp_path / "Classified"
        cfg = _base_config(classified)

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=["Blue Archive"], character=["陸八魔アル"])
        src = tmp_path / "inbox" / "img.jpg"
        _insert_source_file(db, gid, src)

        batch = build_classify_batch_preview(db, [gid], cfg)
        execute_classify_batch(db, batch, cfg)  # 1차 실행

        r = execute_classify_batch(db, batch, cfg)  # 2차 실행 → skipped
        gr = r["group_results"][0]
        assert "status"  in gr
        assert "message" in gr
        assert "error"   in gr
        assert gr["status"]  == "skipped"
        assert gr["error"]   is None
