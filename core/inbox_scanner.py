"""
Inbox 폴더 스캐너.

지원 파일 형식을 검색하여 artwork_groups / artwork_files에 등록하고
형식별 처리를 수행한다.

형식별 처리 (v2.4):
  JPEG/PNG/WebP  : AruArchive JSON 읽기 시도 → 없으면 metadata_missing
  BMP            : original 보존 + PNG managed 생성
  animated GIF   : original 보존 + WebP managed 생성
  static GIF     : original 보존 + .aru.json sidecar 생성 (sidecar-only 정책)
  ZIP            : original 등록만 (ugoira 변환 Post-MVP)

xmp_write_failed는 no_metadata_queue에 INSERT하지 않는다 (v2.4 정책).
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from core.constants import XMP_WRITE_FAILED_SKIP_QUEUE, aggregate_metadata_status
from core.format_converter import (
    convert_bmp_to_png,
    convert_gif_to_webp,
    get_file_format,
    is_animated_gif,
)
from core.metadata_reader import read_aru_metadata
from core.thumbnail_manager import generate_thumbnail

logger = logging.getLogger(__name__)

SCAN_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".zip"})
LogFn = Callable[[str], None]


# Status downgrade guard for InboxScanner.reprocess_group.
# reprocess 는 file scan 만 수행한다 (XMP/XP write 는 안 함). 따라서 reprocess
# 결과로 의미 있는 status 를 약화시키면 안 된다.
#
# - ``full``                  : XMP+XP 까지 정상 기록된 상태 — file scan 결과
#                               'json_only' / 'metadata_missing' 로 강등 금지.
# - ``xmp_write_failed``      : XMP write 시도 실패 — 사용자가 명시적으로
#                               xmp_retry / explorer_meta_repair 로 풀어야 한다.
#                               단순 file scan 으로 의미를 덮으면 사용자가
#                               실패 사실을 잃는다.
# - ``metadata_write_failed`` : 동일 — 명시 retry 경로로만 해소되어야 한다.
# - ``source_unavailable``    : Pixiv 404 등 영구 조회 불가. file scan 결과와
#                               의미가 다르므로 보존.
_REPROCESS_PROTECTED_STATUSES: frozenset[str] = frozenset({
    "full",
    "xmp_write_failed",
    "metadata_write_failed",
    "source_unavailable",
})

# reprocess 가 정당하게 강화시킬 수 있는 결과 status. 그 외 (예: 'convert_failed')
# 는 file scan 의 정당한 새 정보이므로 protected status 와 무관하게 적용.
_REPROCESS_DOWNGRADE_RESULT_STATUSES: frozenset[str] = frozenset({
    "json_only",
    "metadata_missing",
})


def _reprocess_should_overwrite_status(current: str, new: str) -> bool:
    """reprocess 결과가 기존 status 를 덮어써도 되는지 판정.

    Returns False 인 경우 caller 는 UPDATE 를 skip 하고 기존 status 를 유지한다.
    """
    if (
        current in _REPROCESS_PROTECTED_STATUSES
        and new in _REPROCESS_DOWNGRADE_RESULT_STATUSES
    ):
        return False
    return True


# ---------------------------------------------------------------------------
# 결과 객체
# ---------------------------------------------------------------------------

@dataclass
class ScanResult:
    scanned: int = 0
    new: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------

def compute_file_hash(path: Path) -> str:
    """SHA-256 파일 해시 반환."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 스캐너
# ---------------------------------------------------------------------------

class InboxScanner:
    """
    Inbox 디렉토리를 순회하여 파일을 DB에 등록하고 형식별 처리를 수행한다.

    Args:
        conn:      SQLite 연결 (WAL 모드 기대)
        data_dir:  아카이브 루트 (썸네일 경로 기준)
        log_fn:    UI 로그 콜백. 없으면 표준 logger 사용.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        data_dir: str,
        managed_dir: str = "",
        log_fn: Optional[LogFn] = None,
    ):
        self.conn = conn
        self.data_dir = data_dir
        self.managed_dir = managed_dir
        self.log_fn: LogFn = log_fn or (lambda msg: logger.info(msg))

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def scan(self, inbox_dir: str) -> ScanResult:
        """inbox_dir 전체 스캔. ScanResult 반환."""
        result = ScanResult()
        inbox_path = Path(inbox_dir)

        if not inbox_path.exists():
            self.log_fn(f"[WARN] Inbox 폴더 없음: {inbox_dir}")
            return result

        self.log_fn(f"[INFO] 이미지 스캔 시작: {inbox_dir}")

        files = sorted(
            f for f in inbox_path.iterdir()
            if f.is_file() and f.suffix.lower() in SCAN_EXTENSIONS
        )

        if not files:
            self.log_fn("[INFO] 스캔 가능한 파일이 없습니다.")
            return result

        for file_path in files:
            result.scanned += 1
            try:
                outcome = self._process_file(file_path)
                if outcome == "skipped":
                    result.skipped += 1
                else:
                    result.new += 1
            except Exception as exc:  # noqa: BLE001
                result.failed += 1
                msg = f"{file_path.name}: {exc}"
                result.errors.append(msg)
                self.log_fn(f"[ERROR] 처리 실패 — {msg}")

        self.log_fn(
            f"[INFO] 스캔 완료 — 발견: {result.scanned}, "
            f"신규: {result.new}, 스킵: {result.skipped}, 실패: {result.failed}"
        )
        return result

    def process_single_file(self, file_path: Path) -> str:
        """단일 파일 처리 (수동 테스트 버튼용). 'new' | 'skipped' 반환."""
        return self._process_file(file_path)

    def reprocess_group(self, group_id: str) -> str:
        """
        기존 그룹의 파일을 재처리한다 (DB 재색인 버튼용).
        original 파일을 찾아 형식별 처리를 다시 수행하고 상태를 갱신한다.

        파일에 이미 임베딩된 Aru JSON metadata 가 있으면 그것을 읽어
        ``_process_by_format`` 에 전달한다. 그렇게 해야 JPEG/PNG/WebP 핸들러가
        ``existing_meta`` 분기로 들어가 ``json_only`` 를 반환하고, 정상적으로
        보강된 group 의 metadata_sync_status 가 metadata_missing 으로
        강등되는 것을 막을 수 있다.

        Status 보존 정책 (downgrade guard):
            reprocess 는 file scan 만 수행하고 XMP/XP write 는 하지 않는다.
            따라서 reprocess 결과 (``json_only`` / ``metadata_missing``) 가
            의미 있는 상태 (``full`` / ``xmp_write_failed`` /
            ``metadata_write_failed`` / ``source_unavailable``) 를 덮어쓰는
            것은 status 의미에 어긋난다.

            예: 사용자가 Wizard "XMP 데이터 입력" 을 누르면 이 함수가 호출되며,
                기존 ``full`` 인 group 도 reprocess 결과 ``json_only`` 로
                덮였다. 이 때문에 full → json_only 로 보이지 않는 강등이 발생.
                ``_REPROCESS_STATUS_DOWNGRADE_GUARD`` 가 그 강등을 차단한다.

            진정한 XMP 재등록 (status 를 명시적으로 ``full`` 로 끌어올리는
            동작) 은 ``core.xmp_retry`` / ``core.explorer_meta_repair`` 가
            담당하며, 그 경로는 그대로 동작한다.
        """
        row = self.conn.execute(
            "SELECT file_path, file_format, file_id FROM artwork_files "
            "WHERE group_id=? AND file_role='original' LIMIT 1",
            (group_id,),
        ).fetchone()
        if not row:
            return "skipped"

        file_path = Path(row["file_path"])
        file_format = row["file_format"]
        original_file_id = row["file_id"]
        now = datetime.now(timezone.utc).isoformat()

        existing_meta: dict | None = None
        if file_format not in ("bmp", "zip"):
            try:
                existing_meta = read_aru_metadata(str(file_path), file_format)
            except Exception:
                existing_meta = None

        page_status = self._process_by_format(
            file_path, file_format, group_id, original_file_id, existing_meta, now
        )

        # downgrade guard — 기존 status 를 reprocess 결과가 약화시키는 것을 차단.
        current_row = self.conn.execute(
            "SELECT metadata_sync_status FROM artwork_groups WHERE group_id=?",
            (group_id,),
        ).fetchone()
        current_status = current_row["metadata_sync_status"] if current_row else None
        if current_status and not _reprocess_should_overwrite_status(
            current_status, page_status,
        ):
            self.log_fn(
                f"[INFO] reprocess: status 보존 "
                f"({current_status!r} 유지, reprocess 결과 {page_status!r} 미적용): "
                f"{file_path.name}"
            )
            page_status = current_status
        else:
            self.conn.execute(
                "UPDATE artwork_groups SET metadata_sync_status=? WHERE group_id=?",
                (page_status, group_id),
            )
        self.conn.commit()

        thumb_src = self._find_thumb_source(group_id, file_path)
        if thumb_src:
            try:
                file_hash = compute_file_hash(thumb_src)
                generate_thumbnail(
                    self.conn, str(thumb_src), self.data_dir,
                    original_file_id, file_hash,
                )
            except Exception as e:
                self.log_fn(f"[WARN] 썸네일 재생성 실패: {file_path.name}: {e}")

        return "new"

    # ------------------------------------------------------------------
    # 내부: 파일 처리
    # ------------------------------------------------------------------

    def _process_file(self, file_path: Path) -> str:
        # 경로 기준 중복
        if self.conn.execute(
            "SELECT 1 FROM artwork_files WHERE file_path=?", (str(file_path),)
        ).fetchone():
            self.log_fn(f"[INFO] 스킵 (이미 등록): {file_path.name}")
            return "skipped"

        file_format = get_file_format(str(file_path))
        file_hash = compute_file_hash(file_path)
        file_size = file_path.stat().st_size
        now = datetime.now(timezone.utc).isoformat()

        # hash 기준 중복 (original 한정)
        if self.conn.execute(
            "SELECT 1 FROM artwork_files WHERE file_hash=? AND file_role='original'",
            (file_hash,),
        ).fetchone():
            self.log_fn(f"[INFO] 스킵 (동일 내용): {file_path.name}")
            return "skipped"

        self.log_fn(f"[INFO] {file_format.upper()} 발견: {file_path.name}")

        # 기존 AruArchive JSON 읽기 시도 (BMP/ZIP 제외)
        existing_meta: dict | None = None
        if file_format not in ("bmp", "zip"):
            try:
                existing_meta = read_aru_metadata(str(file_path), file_format)
            except Exception:
                pass

        # ID 결정
        group_id = str(uuid.uuid4())
        file_id = str(uuid.uuid4())

        if existing_meta and existing_meta.get("artwork_id"):
            artwork_id = str(existing_meta["artwork_id"])
            source_site = str(existing_meta.get("source_site", "local"))
            artwork_title = str(existing_meta.get("artwork_title", file_path.stem))
            artist_name = str(existing_meta.get("artist_name", ""))
            tags_json = json.dumps(existing_meta.get("tags", []), ensure_ascii=False)
        else:
            artwork_id = file_hash[:16]
            source_site = "local"
            artwork_title = file_path.stem
            artist_name = ""
            tags_json = "[]"

        # artwork_groups INSERT
        try:
            self.conn.execute(
                """INSERT INTO artwork_groups
                   (group_id, source_site, artwork_id, artwork_title, artist_name,
                    artwork_kind, total_pages, downloaded_at, indexed_at,
                    status, metadata_sync_status, tags_json, schema_version)
                   VALUES (?, ?, ?, ?, ?, 'single_image', 1, ?, ?, 'inbox', 'pending', ?, '1.0')""",
                (group_id, source_site, artwork_id, artwork_title, artist_name,
                 now, now, tags_json),
            )
        except sqlite3.IntegrityError:
            # UNIQUE(artwork_id, source_site) 충돌 → 기존 group 재사용
            row = self.conn.execute(
                "SELECT group_id FROM artwork_groups WHERE source_site=? AND artwork_id=?",
                (source_site, artwork_id),
            ).fetchone()
            if row:
                group_id = row["group_id"]
            else:
                raise

        # artwork_files INSERT (original)
        self.conn.execute(
            """INSERT INTO artwork_files
               (file_id, group_id, page_index, file_role, file_path,
                file_format, file_hash, file_size, metadata_embedded, file_status, created_at)
               VALUES (?, ?, 0, 'original', ?, ?, ?, ?, ?, 'present', ?)""",
            (file_id, group_id, str(file_path), file_format, file_hash,
             file_size, 1 if existing_meta else 0, now),
        )
        self.conn.commit()

        # 형식별 처리
        page_status = self._process_by_format(
            file_path, file_format, group_id, file_id, existing_meta, now
        )

        # group 상태 갱신 (단일 파일 → 집계 = 파일 상태)
        self.conn.execute(
            "UPDATE artwork_groups SET metadata_sync_status=? WHERE group_id=?",
            (page_status, group_id),
        )
        self.conn.commit()

        # 썸네일 생성
        thumb_src = self._find_thumb_source(group_id, file_path)
        if thumb_src:
            try:
                generate_thumbnail(
                    self.conn, str(thumb_src), self.data_dir, file_id, file_hash
                )
            except Exception as e:
                self.log_fn(f"[WARN] 썸네일 생성 실패: {file_path.name}: {e}")

        return "new"

    def _process_by_format(
        self,
        file_path: Path,
        file_format: str,
        group_id: str,
        original_file_id: str,
        existing_meta: dict | None,
        now: str,
    ) -> str:
        """형식별 처리 → metadata_sync_status 반환."""
        if file_format == "bmp":
            return self._handle_bmp(file_path, group_id, original_file_id, now)

        if file_format == "gif":
            if is_animated_gif(str(file_path)):
                return self._handle_animated_gif(file_path, group_id, original_file_id, now)
            return self._handle_static_gif(file_path, group_id, original_file_id, now)

        if file_format == "zip":
            self.log_fn(f"[INFO] ZIP 등록 (ugoira 변환 Post-MVP): {file_path.name}")
            return "pending"

        # JPEG / PNG / WebP
        if existing_meta:
            self.log_fn(f"[INFO] AruArchive JSON 발견: {file_path.name}")
            return "json_only"

        self.log_fn(f"[INFO] 메타데이터 없음 → 큐 등록: {file_path.name}")
        self._enqueue_no_metadata(file_path, group_id, "manual_add", now)
        return "metadata_missing"

    # ------------------------------------------------------------------
    # 내부: 형식별 핸들러
    # ------------------------------------------------------------------

    def _handle_bmp(
        self, file_path: Path, group_id: str, original_file_id: str, now: str
    ) -> str:
        try:
            dest_dir = self.managed_dir or str(file_path.parent)
            Path(dest_dir).mkdir(parents=True, exist_ok=True)
            png_path_str = convert_bmp_to_png(str(file_path), dest_dir)
            png_path = Path(png_path_str)
            self.log_fn(f"[INFO] PNG managed 생성: {png_path.name}")

            managed_id = str(uuid.uuid4())
            managed_hash = compute_file_hash(png_path)
            self.conn.execute(
                """INSERT INTO artwork_files
                   (file_id, group_id, page_index, file_role, file_path,
                    file_format, file_hash, file_size, metadata_embedded,
                    file_status, created_at, source_file_id)
                   VALUES (?, ?, 0, 'managed', ?, 'png', ?, ?, 0, 'present', ?, ?)""",
                (managed_id, group_id, png_path_str, managed_hash,
                 png_path.stat().st_size, now, original_file_id),
            )
            self.conn.commit()
            return "metadata_missing"

        except Exception as e:
            self.log_fn(f"[ERROR] BMP 변환 실패: {file_path.name}: {e}")
            self._enqueue_no_metadata(file_path, group_id, "bmp_convert_failed", now)
            return "convert_failed"

    def _handle_animated_gif(
        self, file_path: Path, group_id: str, original_file_id: str, now: str
    ) -> str:
        try:
            dest_dir = self.managed_dir or str(file_path.parent)
            Path(dest_dir).mkdir(parents=True, exist_ok=True)
            webp_path_str = convert_gif_to_webp(str(file_path), dest_dir)
            webp_path = Path(webp_path_str)
            self.log_fn(f"[INFO] WebP managed 생성: {webp_path.name}")

            managed_id = str(uuid.uuid4())
            managed_hash = compute_file_hash(webp_path)
            self.conn.execute(
                """INSERT INTO artwork_files
                   (file_id, group_id, page_index, file_role, file_path,
                    file_format, file_hash, file_size, metadata_embedded,
                    file_status, created_at, source_file_id)
                   VALUES (?, ?, 0, 'managed', ?, 'webp', ?, ?, 0, 'present', ?, ?)""",
                (managed_id, group_id, webp_path_str, managed_hash,
                 webp_path.stat().st_size, now, original_file_id),
            )
            self.conn.commit()
            return "metadata_missing"

        except Exception as e:
            self.log_fn(f"[ERROR] animated GIF 변환 실패: {file_path.name}: {e}")
            self._enqueue_no_metadata(file_path, group_id, "managed_file_create_failed", now)
            return "convert_failed"

    def _handle_static_gif(
        self, file_path: Path, group_id: str, original_file_id: str, now: str
    ) -> str:
        sidecar_path = Path(str(file_path) + ".aru.json")

        if not sidecar_path.exists():
            try:
                minimal = {
                    "schema_version": "1.0",
                    "source_site": "local",
                    "artwork_id": "",
                    "original_filename": file_path.name,
                }
                sidecar_path.write_text(
                    json.dumps(minimal, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                self.log_fn(f"[INFO] sidecar 생성: {sidecar_path.name}")
            except Exception as e:
                self.log_fn(f"[ERROR] sidecar 생성 실패: {file_path.name}: {e}")
                self._enqueue_no_metadata(file_path, group_id, "metadata_write_failed", now)
                return "metadata_write_failed"
        else:
            self.log_fn(f"[INFO] 기존 sidecar 발견: {sidecar_path.name}")

        return self._register_sidecar(sidecar_path, group_id, original_file_id, now)

    def _register_sidecar(
        self, sidecar_path: Path, group_id: str, source_file_id: str, now: str
    ) -> str:
        try:
            sidecar_id = str(uuid.uuid4())
            sidecar_hash = compute_file_hash(sidecar_path)
            self.conn.execute(
                """INSERT OR IGNORE INTO artwork_files
                   (file_id, group_id, page_index, file_role, file_path,
                    file_format, file_hash, file_size, metadata_embedded,
                    file_status, created_at, source_file_id)
                   VALUES (?, ?, 0, 'sidecar', ?, 'json', ?, ?, 1, 'present', ?, ?)""",
                (sidecar_id, group_id, str(sidecar_path), sidecar_hash,
                 sidecar_path.stat().st_size, now, source_file_id),
            )
            self.conn.commit()
        except Exception as e:
            self.log_fn(f"[WARN] sidecar DB 등록 실패: {sidecar_path.name}: {e}")
        return "json_only"

    # ------------------------------------------------------------------
    # 내부: no_metadata_queue
    # ------------------------------------------------------------------

    def _enqueue_no_metadata(
        self,
        file_path: Path,
        group_id: Optional[str],
        fail_reason: str,
        now: str,
    ) -> None:
        """no_metadata_queue INSERT. xmp_write_failed는 스킵 (v2.4 정책)."""
        if fail_reason == "xmp_write_failed" and XMP_WRITE_FAILED_SKIP_QUEUE:
            return
        self.conn.execute(
            """INSERT INTO no_metadata_queue
               (queue_id, file_path, source_site, detected_at, fail_reason, resolved)
               VALUES (?, ?, 'local', ?, ?, 0)""",
            (str(uuid.uuid4()), str(file_path), now, fail_reason),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # 내부: 썸네일 소스
    # ------------------------------------------------------------------

    def _find_thumb_source(self, group_id: str, original_path: Path) -> Optional[Path]:
        """managed 우선, 없으면 original 반환."""
        managed = self.conn.execute(
            "SELECT file_path FROM artwork_files WHERE group_id=? AND file_role='managed' LIMIT 1",
            (group_id,),
        ).fetchone()
        if managed:
            p = Path(managed["file_path"])
            if p.exists():
                return p
        if original_path.exists():
            return original_path
        return None
