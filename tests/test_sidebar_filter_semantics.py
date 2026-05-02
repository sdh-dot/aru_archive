"""Sidebar 의미 기반 카테고리 분할 — 부분 → 전체 invariant.

본 테스트는 sidebar semantic refactor 의 cross-module invariant 을 lock 한다:

1. ``WORK_TARGET_STATUSES`` 와 ``core.classifier.CLASSIFIABLE_STATUSES`` 는 동일해야
   한다. 한쪽만 변경되면 분류 가능한 작품의 sidebar 표시가 어긋난다.
2. ``METADATA_SYNC_STATUSES`` (전체 12종) 가 work_target / failed / other /
   metadata_missing 4개 그룹으로 **빠짐없이, 겹치지 않게** 분할된다.
3. CATEGORIES 순서는 task spec 으로 고정 — 시각적 우선순위 변경은 의도적 변경이
   필요하다.
"""
from __future__ import annotations

from app.widgets.sidebar import CATEGORIES
from app.widgets.sidebar_filters import (
    FAILED_STATUSES_SQL_LIST,
    OTHER_STATUSES_SQL_LIST,
    WORK_TARGET_STATUSES,
    WORK_TARGET_STATUSES_SQL_LIST,
)
from core.classifier import CLASSIFIABLE_STATUSES
from core.constants import METADATA_SYNC_STATUSES


def _parse_sql_list(sql_list: str) -> set[str]:
    """``"'a','b','c'"`` 형식의 IN-list 문자열을 set 으로 파싱."""
    return {part.strip().strip("'") for part in sql_list.split(",") if part.strip()}


# ---------------------------------------------------------------------------
# 분류기 ↔ sidebar work_target 일치
# ---------------------------------------------------------------------------

class TestClassifiableParity:
    def test_work_target_statuses_equals_classifiable_statuses(self):
        """sidebar work_target ≡ classifier CLASSIFIABLE_STATUSES.

        한쪽만 변경되면 사용자에게는 work_target 으로 보이지만 분류기는 거부하거나
        그 반대 상황이 생긴다.
        """
        assert WORK_TARGET_STATUSES == CLASSIFIABLE_STATUSES

    def test_work_target_sql_list_matches_frozenset(self):
        """SQL list 와 frozenset 이 동일한 원소를 표현해야 한다."""
        assert _parse_sql_list(WORK_TARGET_STATUSES_SQL_LIST) == WORK_TARGET_STATUSES


# ---------------------------------------------------------------------------
# 전체 상태 분할 — 빠짐없이, 겹치지 않게
# ---------------------------------------------------------------------------

class TestStatusPartition:
    def test_partition_covers_all_metadata_sync_statuses(self):
        work_target = _parse_sql_list(WORK_TARGET_STATUSES_SQL_LIST)
        failed = _parse_sql_list(FAILED_STATUSES_SQL_LIST)
        other = _parse_sql_list(OTHER_STATUSES_SQL_LIST)
        unregistered = {"metadata_missing"}

        union = work_target | failed | other | unregistered
        all_statuses = set(METADATA_SYNC_STATUSES)

        missing = all_statuses - union
        assert not missing, (
            f"sidebar 분할에서 누락된 상태: {missing}. "
            "core.constants.METADATA_SYNC_STATUSES 에 새 상태가 추가되었다면 "
            "sidebar_filters.py 의 work_target / failed / other / unregistered "
            "중 하나에 명시적으로 분류해야 한다."
        )

    def test_partition_groups_are_disjoint(self):
        work_target = _parse_sql_list(WORK_TARGET_STATUSES_SQL_LIST)
        failed = _parse_sql_list(FAILED_STATUSES_SQL_LIST)
        other = _parse_sql_list(OTHER_STATUSES_SQL_LIST)
        unregistered = {"metadata_missing"}

        groups = {
            "work_target": work_target,
            "failed": failed,
            "other": other,
            "unregistered": unregistered,
        }
        for a_name, a in groups.items():
            for b_name, b in groups.items():
                if a_name >= b_name:
                    continue
                overlap = a & b
                assert not overlap, (
                    f"{a_name} ∩ {b_name} 비어 있어야 함: {overlap}"
                )

    def test_no_unknown_status_in_partition(self):
        """분할 그룹의 모든 원소가 METADATA_SYNC_STATUSES 에 존재해야 한다."""
        union = (
            _parse_sql_list(WORK_TARGET_STATUSES_SQL_LIST)
            | _parse_sql_list(FAILED_STATUSES_SQL_LIST)
            | _parse_sql_list(OTHER_STATUSES_SQL_LIST)
        )
        unknown = union - set(METADATA_SYNC_STATUSES)
        assert not unknown, (
            f"sidebar 분할에 unknown 상태: {unknown}. "
            "core.constants.METADATA_SYNC_STATUSES 와 일치해야 한다."
        )


# ---------------------------------------------------------------------------
# Sidebar 카테고리 순서 — task spec 고정
# ---------------------------------------------------------------------------

class TestCategoryOrderLock:
    EXPECTED_ORDER: list[str] = [
        "all", "work_target", "unregistered", "failed", "other",
        "no_metadata", "inbox", "managed", "missing",
    ]

    def test_categories_in_spec_order(self):
        keys = [k for k, _ in CATEGORIES]
        assert keys == self.EXPECTED_ORDER, (
            "sidebar 카테고리 순서는 task spec 으로 고정되어 있다. "
            "변경하려면 의도된 결정이어야 한다."
        )

    def test_warning_key_absent(self):
        keys = {k for k, _ in CATEGORIES}
        assert "warning" not in keys
