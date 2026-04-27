"""
완전 중복(SHA-256) 검사 및 정리 미리보기.

정책:
- SHA-256 hash 동일 파일을 중복 그룹으로 묶는다.
- 각 그룹에서 보존 파일 1개를 추천하고 나머지를 삭제 후보로 선정한다.
- 실제 삭제는 delete_manager.execute_delete_preview()가 담당한다.
- 기본 검사 범위는 inbox_managed (Inbox/Managed의 original/managed 파일).
  Classified 복사본은 기본 제외.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Pixiv ID 파일명 패턴 — {artwork_id}_p{page}.ext
_PIXIV_ID_RE = re.compile(r"^\d+_p\d+\.")

# ---------------------------------------------------------------------------
# scope별 WHERE 절 정의
# ---------------------------------------------------------------------------

# scope → SQL WHERE 조건 (af = artwork_files, g = artwork_groups)
_SCOPE_WHERE: dict[str, str] = {
    # 기본값: Inbox(original) + Managed(managed), Classified 제외
    "inbox_managed": (
        "af.file_status = 'present' "
        "AND af.file_role IN ('original', 'managed')"
    ),
    # Inbox 전용 (original 파일만)
    "inbox_only": (
        "af.file_status = 'present' "
        "AND af.file_role = 'original'"
    ),
    # Managed 전용
    "managed_only": (
        "af.file_status = 'present' "
        "AND af.file_role = 'managed'"
    ),
    # Classified 전용 (고급 작업)
    "classified_only": (
        "af.file_status = 'present' "
        "AND af.file_role = 'classified_copy'"
    ),
    # 전체 Archive — 고급 옵션, 별도 확인 필요
    "all_archive": (
        "af.file_status = 'present'"
    ),
    # 현재 뷰에 보이는 group만 대상으로 하되, 기본 역할 범위는 Inbox/Managed
    "current_view": (
        "af.file_status = 'present' "
        "AND af.file_role IN ('original', 'managed')"
    ),
    # 선택 항목 group만 대상으로 하되, 기본 역할 범위는 Inbox/Managed
    "selected": (
        "af.file_status = 'present' "
        "AND af.file_role IN ('original', 'managed')"
    ),
}

_DEFAULT_SCOPE = "inbox_managed"


def select_duplicate_candidate_files(
    conn: sqlite3.Connection,
    *,
    scope: str = _DEFAULT_SCOPE,
    group_ids: list[str] | None = None,
) -> list[dict]:
    """
    scope 기준으로 중복 검사 대상 파일 목록을 반환한다.

    exact / visual duplicate finder 양쪽에서 재사용.

    scope 값:
      'inbox_managed'  — 기본값. Inbox(original) + Managed(managed)
      'inbox_only'     — Inbox(original)만
      'managed_only'   — Managed(managed)만
      'classified_only'— Classified(classified_copy)만 (고급)
      'all_archive'    — 전체 (Classified 포함, 고급)
      'current_view'   — 현재 보이는 group_ids만
      'selected'       — 선택된 group_ids만
    """
    where = _SCOPE_WHERE.get(scope, _SCOPE_WHERE[_DEFAULT_SCOPE])
    params: list = []

    if scope in {"selected", "current_view"} and not group_ids:
        return []

    if group_ids:
        placeholders = ",".join("?" * len(group_ids))
        where = f"{where} AND af.group_id IN ({placeholders})"
        params.extend(group_ids)

    sql = f"""
        SELECT af.file_id, af.group_id, af.file_path, af.file_role,
               af.file_format, af.file_hash, af.file_size, af.file_status,
               af.page_index,
               g.metadata_sync_status, g.artist_name, g.artwork_id
        FROM artwork_files af
        JOIN artwork_groups g ON g.group_id = af.group_id
        WHERE {where}
        ORDER BY af.file_hash, af.file_id
    """
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def find_exact_duplicates(
    conn: sqlite3.Connection,
    *,
    scope: str = _DEFAULT_SCOPE,
    group_ids: list[str] | None = None,
) -> list[dict]:
    """
    SHA-256 기준 완전 중복 그룹을 찾는다.

    scope:
      'inbox_managed'  — 기본. Classified 제외
      'all_archive'    — 전체 (Classified 포함)
      기타 scope 값은 select_duplicate_candidate_files 참조.

    반환: [{"hash": ..., "files": [{"file_id", "file_path", ...}]}]
    """
    rows = select_duplicate_candidate_files(conn, scope=scope, group_ids=group_ids)

    groups: dict[str, list[dict]] = {}
    for d in rows:
        h = d.get("file_hash")
        if not h:
            continue
        groups.setdefault(h, []).append(d)

    return [
        {"hash": h, "files": files}
        for h, files in groups.items()
        if len(files) >= 2
    ]


def recommend_keep_file(duplicate_group: dict) -> dict:
    """
    중복 그룹에서 보존할 파일을 추천한다.

    우선순위:
    1. original 우선
    2. metadata_sync_status='full' 우선
    3. json_only 우선
    4. metadata_missing은 삭제 후보 우선
    5. classified_copy는 삭제 후보 우선
    6. Pixiv ID 규칙 파일명 우선
    7. 더 큰 파일 크기 우선
    """
    files: list[dict] = duplicate_group.get("files", [])
    if not files:
        return {}
    if len(files) == 1:
        return files[0]

    def _score(f: dict) -> tuple:
        role = f.get("file_role", "")
        sync = f.get("metadata_sync_status", "")
        size = f.get("file_size") or 0
        name = Path(f.get("file_path", "")).name
        pixiv_match = 1 if _PIXIV_ID_RE.match(name) else 0

        role_score = {
            "original":        0,
            "managed":         1,
            "sidecar":         2,
            "classified_copy": 3,
        }.get(role, 2)

        sync_score = {
            "full":             0,
            "json_only":        1,
            "xmp_write_failed": 2,
            "pending":          3,
            "metadata_missing": 4,
        }.get(sync, 3)

        return (role_score, sync_score, -pixiv_match, -size)

    return min(files, key=_score)


def build_exact_duplicate_cleanup_preview(
    conn: sqlite3.Connection,
    duplicate_groups: list[dict],
) -> dict:
    """
    각 중복 그룹에서 보존 1개, 삭제 후보 N개를 선정한다.
    실제 삭제는 수행하지 않는다.

    반환:
    {
        "total_groups": N,
        "total_keep": N,
        "total_delete_candidates": N,
        "groups": [{"hash", "keep_file", "delete_candidates": [...]}],
    }
    """
    result_groups: list[dict] = []
    total_keep = 0
    total_delete = 0

    for dup in duplicate_groups:
        keep = recommend_keep_file(dup)
        if not keep:
            continue
        keep_id = keep.get("file_id")
        delete_candidates = [
            f for f in dup.get("files", [])
            if f.get("file_id") != keep_id
        ]
        total_keep += 1
        total_delete += len(delete_candidates)
        result_groups.append({
            "hash": dup.get("hash", ""),
            "keep_file": keep,
            "delete_candidates": delete_candidates,
        })

    return {
        "total_groups": len(result_groups),
        "total_keep": total_keep,
        "total_delete_candidates": total_delete,
        "groups": result_groups,
    }
