"""Explorer Sidebar 필터 SQL / helper 중앙화 모듈.

기존에 ``app/main_window.py`` 내부에 흩어져 있던 sidebar 카테고리 필터 SQL 을
한 곳에 모아둔다. 본 모듈은 이제 **사용자 행동 의미 기반** 카테고리 분할을 정의
한다 (PR #91 동작 보존 → semantic refactor 단계).

이 모듈이 정의하는 invariant (회귀 테스트로 lock):
- ``GALLERY_BASE`` — gallery SELECT base, ``WHERE EXISTS file_status='present'`` 내장
- ``GALLERY_WHERE_BY_CATEGORY`` — 카테고리별 추가 ``AND ...`` 절
  (no_metadata 는 의도적으로 빈 문자열 — 호출자가 panel swap 으로 처리)
- ``COUNT_SQL_BY_CATEGORY`` — 카테고리별 COUNT(*) SQL
  (no_metadata 는 ``no_metadata_queue WHERE resolved = 0`` 카운트로 일치)
- ``GALLERY_MISSING_SQL`` — missing 카테고리 전용 (present 필터 미사용, missing exists)
- ``PRESENT_EXISTS_SQL_FRAGMENT`` / ``MISSING_EXISTS_SQL_FRAGMENT`` — 재사용 fragment
- ``WORK_TARGET_STATUSES`` / ``WORK_TARGET_STATUSES_SQL_LIST`` — 분류 가능한 3종 상태
  (``core.classifier.CLASSIFIABLE_STATUSES`` 와 동일해야 함)
- ``OTHER_STATUSES_SQL_LIST`` — 분류 불가 + 비실패 3종 (pending/out_of_sync/source_unavailable)
- ``FAILED_STATUSES_SQL_LIST`` — 5종 실패 상태

카테고리 의미 (사용자 관점):
- all          : 라이브러리 내 모든 present 파일
- work_target  : 사용자가 분류/관리할 수 있는 상태 (full / json_only / xmp_write_failed)
- unregistered : metadata 가 등록되지 않은 그룹 (metadata_missing) — present 기반 그룹 카운트
- failed       : 5종 실패 상태 — 사용자 재처리 필요
- other        : pending / out_of_sync / source_unavailable — 자동 처리 대기
- no_metadata  : NoMetadataView panel — ``no_metadata_queue WHERE resolved = 0``
- inbox        : 미분류 수신함
- managed      : ``file_role = 'managed'`` 보유
- missing      : DB 등록 + 현재 누락 (별도 SQL)

사용처 (read-only):
- ``app.main_window`` 가 import 후 backward-compat 한 underscore 별칭으로 사용
  (기존 테스트와 호출 사이트가 그대로 작동)

이 모듈이 절대 하지 않는 것:
- DB write 또는 schema 변경
- ``no_metadata`` panel swap 회로 변경 (key/label 만 라우팅, 본 모듈 영역 외부)
- label 변경 (sidebar.py CATEGORIES 가 담당)
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
# 상태 그룹 — IN(...) SQL list 형식
# ---------------------------------------------------------------------------

# 분류/관리 가능한 상태. core.classifier.CLASSIFIABLE_STATUSES 와 일치해야 한다
# (회귀 테스트: tests/test_sidebar_filter_semantics.py).
WORK_TARGET_STATUSES: frozenset[str] = frozenset(
    {"full", "json_only", "xmp_write_failed"}
)
WORK_TARGET_STATUSES_SQL_LIST: str = (
    "'full','json_only','xmp_write_failed'"
)

# 분류 불가이면서 실패도 아닌 "기타" 상태. 사용자가 즉시 행동할 필요 없는 분류.
OTHER_STATUSES_SQL_LIST: str = (
    "'pending','out_of_sync','source_unavailable'"
)

# 5종 실패 상태 — 사용자가 재처리 / 재등록 검토 필요.
FAILED_STATUSES_SQL_LIST: str = (
    "'file_write_failed','convert_failed','metadata_write_failed',"
    "'db_update_failed','needs_reindex'"
)


# ---------------------------------------------------------------------------
# 카테고리별 Gallery WHERE 추가 절
# ---------------------------------------------------------------------------
# 주의:
# - "no_metadata" 는 의도적으로 빈 문자열. 호출자가 panel swap (NoMetadataView)
#   으로 처리하므로 GALLERY 자체는 사용되지 않는다.
# - "missing" 은 GALLERY_MISSING_SQL 별도 사용 (이 dict 에 키 없음).

GALLERY_WHERE_BY_CATEGORY: dict[str, str] = {
    "all":          "",
    "inbox":        "AND g.status = 'inbox'",
    "managed": (
        "AND EXISTS ("
        "  SELECT 1 FROM artwork_files af "
        "  WHERE af.group_id = g.group_id AND af.file_role = 'managed'"
        ")"
    ),
    "work_target":  f"AND g.metadata_sync_status IN ({WORK_TARGET_STATUSES_SQL_LIST})",
    "unregistered": "AND g.metadata_sync_status = 'metadata_missing'",
    "failed":       f"AND g.metadata_sync_status IN ({FAILED_STATUSES_SQL_LIST})",
    "other":        f"AND g.metadata_sync_status IN ({OTHER_STATUSES_SQL_LIST})",
    "no_metadata":  "",
}


# ---------------------------------------------------------------------------
# 카테고리별 COUNT(*) SQL
# ---------------------------------------------------------------------------
# no_metadata 는 NoMetadataView 의 데이터 소스 (no_metadata_queue) 와 일치하도록
# 큐 기반 카운트로 정의. 그 외는 artwork_groups 기반 + present-only 필터.

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
    "work_target": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE g.metadata_sync_status IN ({WORK_TARGET_STATUSES_SQL_LIST}) "
        f"AND {PRESENT_EXISTS_SQL_FRAGMENT}"
    ),
    "unregistered": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE g.metadata_sync_status = 'metadata_missing' "
        f"AND {PRESENT_EXISTS_SQL_FRAGMENT}"
    ),
    "failed": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE g.metadata_sync_status IN ({FAILED_STATUSES_SQL_LIST}) "
        f"AND {PRESENT_EXISTS_SQL_FRAGMENT}"
    ),
    "other": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE g.metadata_sync_status IN ({OTHER_STATUSES_SQL_LIST}) "
        f"AND {PRESENT_EXISTS_SQL_FRAGMENT}"
    ),
    "no_metadata": (
        "SELECT COUNT(*) FROM no_metadata_queue WHERE resolved = 0"
    ),
    "missing": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE {MISSING_EXISTS_SQL_FRAGMENT}"
    ),
}
