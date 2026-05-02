"""Explorer Sidebar 필터 SQL / helper 중앙화 모듈.

기존에 ``app/main_window.py`` 내부에 흩어져 있던 sidebar 카테고리 필터 SQL 을
한 곳에 모아둔다. 이번 모듈 분리는 **동작 보존 refactor** — SQL 의미와 카테고리
매핑은 그대로 유지하며, 향후 사용자 의미 기준 재구성을 안전하게 진행할 수
있도록 단일 진실 원천을 만든다.

이 모듈이 정의하는 invariant (회귀 테스트로 lock):
- ``GALLERY_BASE`` — gallery SELECT base, ``WHERE EXISTS file_status='present'`` 내장
- ``GALLERY_WHERE_BY_CATEGORY`` — 카테고리별 추가 ``AND ...`` 절 (no_metadata 는 의도적으로
  empty string — 호출자가 panel swap 으로 처리)
- ``COUNT_SQL_BY_CATEGORY`` — 카테고리별 COUNT(*) SQL
- ``GALLERY_MISSING_SQL`` — missing 카테고리 전용 (present 필터 미사용, missing exists)
- ``PRESENT_EXISTS_SQL_FRAGMENT`` — present-file EXISTS 절 fragment
- ``MISSING_EXISTS_SQL_FRAGMENT`` — missing-file EXISTS 절 fragment
- ``FAILED_STATUSES_SQL_LIST`` — failed 카테고리에 포함되는 metadata_sync_status 5종의 SQL list 표현

사용처 (read-only):
- ``app.main_window`` 가 import 후 backward-compat 한 underscore 별칭으로 사용
  (기존 테스트와 호출 사이트가 그대로 작동)

이 모듈이 절대 하지 않는 것:
- DB write 또는 schema 변경
- 카테고리 의미 / 매핑 변경 (xmp_write_failed / pending / source_unavailable /
  out_of_sync 위치 모두 기존 그대로)
- no_metadata 의 GALLERY 빈 문자열 정책 변경 (분석에서 확인된 inconsistency 도
  현재 PR 에서 보존 — 향후 별도 PR 에서 다룬다)
- label 변경 (sidebar.py CATEGORIES 미터치)
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Gallery SELECT base — present-file 만 표시
# ---------------------------------------------------------------------------

GALLERY_BASE: str = """
    SELECT
        g.group_id,
        g.artwork_title,
        g.artwork_id,
        g.metadata_sync_status,
        g.status,
        g.source_site,
        (SELECT af.file_format FROM artwork_files af
         WHERE af.group_id = g.group_id AND af.file_role = 'original'
         ORDER BY af.page_index LIMIT 1) AS file_format,
        (SELECT tc.thumb_path
         FROM artwork_files af2
         JOIN thumbnail_cache tc ON tc.file_id = af2.file_id
         WHERE af2.group_id = g.group_id
         ORDER BY af2.page_index LIMIT 1) AS thumb_path,
        (SELECT GROUP_CONCAT(DISTINCT af3.file_role)
         FROM artwork_files af3
         WHERE af3.group_id = g.group_id) AS role_summary
    FROM artwork_groups g
    WHERE EXISTS (
        SELECT 1 FROM artwork_files af_present
        WHERE af_present.group_id = g.group_id
          AND af_present.file_status = 'present'
    )
"""


# ---------------------------------------------------------------------------
# Reusable SQL fragments
# ---------------------------------------------------------------------------

PRESENT_EXISTS_SQL_FRAGMENT: str = (
    "EXISTS ("
    "SELECT 1 FROM artwork_files af_present "
    "WHERE af_present.group_id = g.group_id "
    "AND af_present.file_status = 'present'"
    ")"
)

# present-only base 의 WHERE 조건을 missing 으로 뒤집은 미러 fragment.
MISSING_EXISTS_SQL_FRAGMENT: str = (
    "EXISTS ("
    "SELECT 1 FROM artwork_files af_missing "
    "WHERE af_missing.group_id = g.group_id "
    "AND af_missing.file_status = 'missing'"
    ")"
)


# ---------------------------------------------------------------------------
# Missing 카테고리 전용 Gallery SQL
# GALLERY_BASE 는 present 필터를 내장하므로 missing 카테고리에는 사용 불가.
# ---------------------------------------------------------------------------

GALLERY_MISSING_SQL: str = """
    SELECT
        g.group_id,
        g.artwork_title,
        g.artwork_id,
        g.metadata_sync_status,
        g.status,
        g.source_site,
        (SELECT af.file_format FROM artwork_files af
         WHERE af.group_id = g.group_id AND af.file_role = 'original'
         ORDER BY af.page_index LIMIT 1) AS file_format,
        (SELECT tc.thumb_path
         FROM artwork_files af2
         JOIN thumbnail_cache tc ON tc.file_id = af2.file_id
         WHERE af2.group_id = g.group_id
         ORDER BY af2.page_index LIMIT 1) AS thumb_path,
        (SELECT GROUP_CONCAT(DISTINCT af3.file_role)
         FROM artwork_files af3
         WHERE af3.group_id = g.group_id) AS role_summary
    FROM artwork_groups g
    WHERE {missing_exists}
    ORDER BY g.indexed_at DESC
""".format(missing_exists=MISSING_EXISTS_SQL_FRAGMENT)


# ---------------------------------------------------------------------------
# failed 카테고리에 포함되는 metadata_sync_status 5종 — IN(...) SQL list 형식
# ---------------------------------------------------------------------------

FAILED_STATUSES_SQL_LIST: str = (
    "'file_write_failed','convert_failed','metadata_write_failed',"
    "'db_update_failed','needs_reindex'"
)


# ---------------------------------------------------------------------------
# 카테고리별 Gallery WHERE 추가 절
# ---------------------------------------------------------------------------
# 주의:
# - "no_metadata" 는 의도적으로 빈 문자열. 호출자가 panel swap (NoMetadataView)
#   으로 처리하므로 GALLERY 자체는 사용되지 않는다. 향후 의미 변경 PR 에서 별도로
#   재정의 가능.
# - "missing" 은 GALLERY_MISSING_SQL 별도 사용.

GALLERY_WHERE_BY_CATEGORY: dict[str, str] = {
    "all":         "",
    "inbox":       "AND g.status = 'inbox'",
    "managed": (
        "AND EXISTS ("
        "  SELECT 1 FROM artwork_files af "
        "  WHERE af.group_id = g.group_id AND af.file_role = 'managed'"
        ")"
    ),
    "no_metadata": "",
    "warning":     "AND g.metadata_sync_status IN ('xmp_write_failed', 'json_only')",
    "failed":      f"AND g.metadata_sync_status IN ({FAILED_STATUSES_SQL_LIST})",
}


# ---------------------------------------------------------------------------
# 카테고리별 COUNT(*) SQL
# ---------------------------------------------------------------------------

COUNT_SQL_BY_CATEGORY: dict[str, str] = {
    "all": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE {PRESENT_EXISTS_SQL_FRAGMENT}"
    ),
    "inbox": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE {PRESENT_EXISTS_SQL_FRAGMENT} AND g.status = 'inbox'"
    ),
    "managed": (
        "SELECT COUNT(DISTINCT g.group_id) FROM artwork_groups g "
        "JOIN artwork_files af ON af.group_id = g.group_id "
        f"WHERE af.file_role = 'managed' AND {PRESENT_EXISTS_SQL_FRAGMENT}"
    ),
    "no_metadata": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE g.metadata_sync_status = 'metadata_missing' "
        f"AND {PRESENT_EXISTS_SQL_FRAGMENT}"
    ),
    "warning": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE g.metadata_sync_status IN ('xmp_write_failed', 'json_only') "
        f"AND {PRESENT_EXISTS_SQL_FRAGMENT}"
    ),
    "failed": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE g.metadata_sync_status IN ({FAILED_STATUSES_SQL_LIST}) "
        f"AND {PRESENT_EXISTS_SQL_FRAGMENT}"
    ),
    "missing": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE {MISSING_EXISTS_SQL_FRAGMENT}"
    ),
}
