"""
썸네일 캐시 관리 (Hybrid path 방식).
실제 파일: {data_dir}/.thumbcache/{file_id[0:2]}/{file_id}.webp
DB: thumbnail_cache 테이블 (경로 인덱스만, BLOB 없음)

썸네일 소스 우선순위:
- BMP original → PNG managed가 있으면 managed 기준 (호출자가 managed file_path 전달)
- animated GIF original → WebP managed가 있으면 managed 기준
- static GIF → original 기준 (sidecar-only 정책)
- ugoira → WebP managed 기준
- JPEG/PNG/native WebP → original 기준
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from PIL import Image

THUMBCACHE_DIR = ".thumbcache"
THUMBNAIL_QUALITY = 85


def get_thumb_path(data_dir: str, file_id: str) -> Path:
    """
    {data_dir}/.thumbcache/{file_id[0:2]}/{file_id}.webp 경로 반환.
    파일 존재 여부는 확인하지 않는다.
    """
    prefix = file_id[:2]
    return Path(data_dir) / THUMBCACHE_DIR / prefix / f"{file_id}.webp"


def generate_thumbnail(
    conn: sqlite3.Connection,
    file_path: str,
    data_dir: str,
    file_id: str,
    source_hash: str,
    size: tuple[int, int] = (256, 256),
) -> str:
    """
    썸네일 파일을 생성하고 thumbnail_cache 테이블에 INSERT OR REPLACE한다.
    생성된 썸네일의 절대 경로(str)를 반환한다.

    file_path: 썸네일 소스 파일 경로
      - BMP: PNG managed 경로를 전달할 것 (managed가 없으면 original 경로)
      - animated GIF: WebP managed 경로 전달
      - static GIF: original GIF 경로 전달
      - ugoira: WebP managed 경로 전달
      - 기타: original 경로 전달

    호출자가 적절한 소스 파일을 선택하여 전달한다.
    """
    thumb_path = get_thumb_path(data_dir, file_id)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.open(file_path)
    img.thumbnail(size, Image.LANCZOS)
    img.save(str(thumb_path), format="WEBP", quality=THUMBNAIL_QUALITY)

    thumb_size_str = f"{size[0]}x{size[1]}"
    file_size = thumb_path.stat().st_size

    conn.execute(
        """
        INSERT OR REPLACE INTO thumbnail_cache
            (file_id, thumb_path, thumb_size, source_hash, file_size, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            str(thumb_path),
            thumb_size_str,
            source_hash,
            file_size,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    return str(thumb_path)


def invalidate_thumbnail(
    conn: sqlite3.Connection,
    data_dir: str,
    file_id: str,
) -> None:
    """썸네일 파일 삭제 후 thumbnail_cache 레코드 제거."""
    row = conn.execute(
        "SELECT thumb_path FROM thumbnail_cache WHERE file_id=?", (file_id,)
    ).fetchone()
    if row:
        Path(row["thumb_path"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM thumbnail_cache WHERE file_id=?", (file_id,))
        conn.commit()


def purge_orphan_thumbnails(conn: sqlite3.Connection, data_dir: str) -> int:
    """
    DB에 없는 고아 썸네일 파일을 삭제하고 삭제 개수를 반환한다.
    주기적으로 실행하여 .thumbcache 디렉토리를 정리한다 (권장: 주 1회).
    """
    thumb_dir = Path(data_dir) / THUMBCACHE_DIR
    if not thumb_dir.exists():
        return 0

    deleted = 0
    for webp in thumb_dir.rglob("*.webp"):
        file_id = webp.stem
        row = conn.execute(
            "SELECT 1 FROM thumbnail_cache WHERE file_id=?", (file_id,)
        ).fetchone()
        if not row:
            webp.unlink(missing_ok=True)
            deleted += 1
    return deleted


def needs_regeneration(
    conn: sqlite3.Connection,
    file_id: str,
    current_hash: str,
) -> bool:
    """
    파일 hash가 변경되어 썸네일 재생성이 필요한지 확인한다.
    캐시가 없거나 hash가 다르면 True 반환.
    """
    row = conn.execute(
        "SELECT source_hash FROM thumbnail_cache WHERE file_id=?", (file_id,)
    ).fetchone()
    if not row:
        return True
    return row["source_hash"] != current_hash
