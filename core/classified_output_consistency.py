"""classified_output_consistency.py — read-only 진단 도구.

분류 규칙 / tag pack / localization 등이 시간에 따라 바뀌면, 과거에 분류
실행으로 만들어진 ``Classified/...`` 폴더 구조와 현재 규칙으로 만들어질
expected destination 이 어긋날 수 있다 (예: ``트릭컬`` 옛 폴더 vs 새 설정의
``트릭컬 리바이브`` 폴더).

본 모듈은 그런 group 을 사용자에게 **보여주기만** 한다.
- DB 에 어떠한 UPDATE/INSERT/DELETE 도 하지 않는다.
- 파일 시스템에 어떠한 read 외 동작 (rename/move/delete) 도 하지 않는다.
- expected destination 계산은 build_classify_preview 를 그대로 호출해
  classifier 의 실제 정책 (sanitize / localization / fallback / multi-dest)
  과 100% 일치시킨다.
- 비교는 "파일 존재 여부" 가 아니라 "DB 의 classified_copy row 와 expected
  dest_path" 를 path normalization 후 비교한다.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


__all__ = [
    "ClassifiedOutputConsistencyItem",
    "ClassifiedOutputConsistencySummary",
    "ClassifiedOutputConsistencyReport",
    "build_classified_output_consistency_report",
]


@dataclass(frozen=True)
class ClassifiedOutputConsistencyItem:
    group_id: str
    artwork_id: Optional[str]
    title: Optional[str]
    source_path: Optional[str]
    status: str
    """consistent | legacy_extra | missing_expected | legacy_and_missing | unverifiable"""
    current_destinations: tuple[str, ...]
    existing_classified_copies: tuple[str, ...]
    legacy_extra_paths: tuple[str, ...]
    missing_expected_paths: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class ClassifiedOutputConsistencySummary:
    groups_scanned: int
    groups_consistent: int
    groups_with_legacy_extra: int
    groups_with_missing_expected: int
    groups_unverifiable: int
    legacy_file_count: int
    missing_expected_count: int


@dataclass(frozen=True)
class ClassifiedOutputConsistencyReport:
    summary: ClassifiedOutputConsistencySummary
    items: tuple[ClassifiedOutputConsistencyItem, ...]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _normalize_path_for_compare(path: str) -> str:
    """Windows-안전 경로 비교용 normalization.

    - 빈 문자열은 그대로 반환 (set 에서 NULL/빈 dest_path 가 자기 자신과만 일치).
    - ``Path(...).resolve(strict=False)`` 로 절대화 + slash 정규화.
    - ``casefold()`` 로 대소문자 차이 제거.
    - 실제 파일 존재 여부는 강제하지 않는다 (resolve strict=False).
    """
    if not path:
        return ""
    try:
        return str(Path(path).resolve(strict=False)).casefold()
    except Exception:
        return path.casefold()


def _fetch_present_classified_copies_by_group(
    conn: sqlite3.Connection,
    group_id: str,
) -> list[str]:
    """group 의 file_role='classified_copy' AND file_status='present' 인 file_path 목록.

    원본 display 그대로 반환. 정렬: file_path ASC.
    """
    rows = conn.execute(
        "SELECT file_path FROM artwork_files "
        "WHERE group_id = ? AND file_role = 'classified_copy' "
        "  AND file_status = 'present' "
        "ORDER BY file_path",
        (group_id,),
    ).fetchall()
    out: list[str] = []
    for r in rows:
        # row factory 가 sqlite3.Row 든 tuple 이든 모두 처리
        try:
            out.append(r["file_path"])
        except Exception:
            out.append(r[0])
    return out


def _list_groups_with_present_classified_copies(
    conn: sqlite3.Connection,
    *,
    limit: Optional[int] = None,
) -> list[str]:
    sql = (
        "SELECT DISTINCT group_id FROM artwork_files "
        "WHERE file_role = 'classified_copy' AND file_status = 'present' "
        "ORDER BY group_id"
    )
    if limit is not None and limit > 0:
        sql = sql + f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()
    out: list[str] = []
    for r in rows:
        try:
            out.append(r["group_id"])
        except Exception:
            out.append(r[0])
    return out


def _fetch_group_meta(conn, group_id: str) -> dict:
    row = conn.execute(
        "SELECT group_id, artwork_id, artwork_title FROM artwork_groups "
        "WHERE group_id = ?",
        (group_id,),
    ).fetchone()
    if row is None:
        return {"group_id": group_id, "artwork_id": None, "artwork_title": None}
    try:
        return {
            "group_id": row["group_id"],
            "artwork_id": row["artwork_id"],
            "artwork_title": row["artwork_title"],
        }
    except Exception:
        return {"group_id": row[0], "artwork_id": row[1], "artwork_title": row[2]}


# ---------------------------------------------------------------------------
# main report builder
# ---------------------------------------------------------------------------

def build_classified_output_consistency_report(
    conn: sqlite3.Connection,
    *,
    config: dict,
    group_ids: Optional[Sequence[str]] = None,
    scope: str = "all_classified",
    include_consistent: bool = False,
    include_unverifiable: bool = True,
    limit: Optional[int] = None,
) -> ClassifiedOutputConsistencyReport:
    """현재 분류 규칙 vs 저장된 classified_copy 경로 정합성 보고.

    Parameters
    ----------
    conn:
        sqlite3 connection. SELECT 만 사용한다.
    config:
        ``build_classify_preview`` 가 사용하는 동일 형태의 config dict.
    group_ids:
        명시 group 만 검사. None 이면 ``scope`` 사용.
    scope:
        ``all_classified`` (기본): present classified_copy 가 있는 group 전체.
        그 외 값은 무시되고 ``all_classified`` 로 동작.
    include_consistent:
        True 면 정상 group 도 items 에 포함. False (기본) 면 summary 에만 반영.
    include_unverifiable:
        True (기본) 면 build_classify_preview 가 None 인 group 도 items 에 포함.
    limit:
        scope='all_classified' 일 때 검사 group 상한.

    Returns
    -------
    ClassifiedOutputConsistencyReport — items 는 항상 frozen dataclass.
    """
    from core.classifier import build_classify_preview

    # 1) 검사 대상 group_id 결정
    if group_ids is not None:
        target_ids: list[str] = [g for g in group_ids if g]
    else:
        target_ids = _list_groups_with_present_classified_copies(conn, limit=limit)

    items: list[ClassifiedOutputConsistencyItem] = []
    n_consistent = 0
    n_legacy = 0
    n_missing = 0
    n_unverifiable = 0
    legacy_file_count = 0
    missing_expected_count = 0

    for gid in target_ids:
        meta = _fetch_group_meta(conn, gid)
        existing = _fetch_present_classified_copies_by_group(conn, gid)
        existing_norm = {_normalize_path_for_compare(p): p for p in existing}

        notes: list[str] = []
        try:
            preview = build_classify_preview(conn, gid, config)
        except Exception as exc:
            preview = None
            notes.append(f"preview 실패: {exc}")

        if preview is None:
            n_unverifiable += 1
            if include_unverifiable:
                items.append(
                    ClassifiedOutputConsistencyItem(
                        group_id=gid,
                        artwork_id=meta["artwork_id"],
                        title=meta["artwork_title"],
                        source_path=None,
                        status="unverifiable",
                        current_destinations=tuple(),
                        existing_classified_copies=tuple(existing),
                        legacy_extra_paths=tuple(),
                        missing_expected_paths=tuple(),
                        notes=tuple(notes) if notes else (
                            "현재 분류 미리보기를 생성할 수 없음 "
                            "(metadata_sync_status / source / classified_dir 확인)",
                        ),
                    )
                )
            continue

        # 2) expected dest 추출
        dests = preview.get("destinations") or []
        current = [d.get("dest_path", "") for d in dests if d.get("dest_path")]
        current_norm = {_normalize_path_for_compare(p): p for p in current}

        legacy = sorted(
            existing_norm[k] for k in (existing_norm.keys() - current_norm.keys())
        )
        missing = sorted(
            current_norm[k] for k in (current_norm.keys() - existing_norm.keys())
        )

        if not legacy and not missing:
            status = "consistent"
            n_consistent += 1
            if not include_consistent:
                continue
        elif legacy and missing:
            status = "legacy_and_missing"
            n_legacy += 1
            n_missing += 1
            legacy_file_count += len(legacy)
            missing_expected_count += len(missing)
        elif legacy:
            status = "legacy_extra"
            n_legacy += 1
            legacy_file_count += len(legacy)
        else:
            status = "missing_expected"
            n_missing += 1
            missing_expected_count += len(missing)

        items.append(
            ClassifiedOutputConsistencyItem(
                group_id=gid,
                artwork_id=meta["artwork_id"],
                title=meta["artwork_title"],
                source_path=preview.get("source_path"),
                status=status,
                current_destinations=tuple(current),
                existing_classified_copies=tuple(existing),
                legacy_extra_paths=tuple(legacy),
                missing_expected_paths=tuple(missing),
                notes=tuple(notes),
            )
        )

    summary = ClassifiedOutputConsistencySummary(
        groups_scanned=len(target_ids),
        groups_consistent=n_consistent,
        groups_with_legacy_extra=n_legacy,
        groups_with_missing_expected=n_missing,
        groups_unverifiable=n_unverifiable,
        legacy_file_count=legacy_file_count,
        missing_expected_count=missing_expected_count,
    )
    return ClassifiedOutputConsistencyReport(summary=summary, items=tuple(items))
