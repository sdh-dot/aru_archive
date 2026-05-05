"""
수동 분류 보정(override) 관리.

classification_overrides 테이블에 group별 수동 series/character 지정을 저장하고
preview item에 적용한다.

정책:
- 한 group에 active override는 최대 1개 (enabled=1)
- set_override_for_group: 기존 override를 비활성화하고 새 override 삽입
- clear_override_for_group: enabled=0 으로 soft delete
- apply_override_to_preview_item: preview destinations를 재계산해 반환
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.folder_localization import resolve_category_folder, resolve_uncategorized_folder
from core.path_utils import sanitize_path_component
from core.tag_localizer import resolve_display_name_with_info


def get_override_for_group(
    conn: sqlite3.Connection,
    group_id: str,
) -> Optional[dict]:
    """
    group_id에 대한 활성 override를 반환한다.

    없으면 None.
    반환 dict: {override_id, group_id, series_canonical, character_canonical,
                folder_locale, reason, source, enabled, created_at, updated_at}
    """
    row = conn.execute(
        "SELECT * FROM classification_overrides "
        "WHERE group_id = ? AND enabled = 1 "
        "ORDER BY created_at DESC LIMIT 1",
        (group_id,),
    ).fetchone()
    return dict(row) if row else None


def set_override_for_group(
    conn: sqlite3.Connection,
    *,
    group_id: str,
    series_canonical: Optional[str],
    character_canonical: Optional[str],
    folder_locale: Optional[str] = None,
    reason: Optional[str] = None,
) -> str:
    """
    group_id에 수동 override를 저장한다.

    기존 활성 override가 있으면 비활성화(enabled=0)한 뒤 새 레코드를 삽입한다.

    반환: 새 override_id
    """
    now = datetime.now(timezone.utc).isoformat()

    # 기존 활성 override 비활성화
    conn.execute(
        "UPDATE classification_overrides SET enabled = 0, updated_at = ? "
        "WHERE group_id = ? AND enabled = 1",
        (now, group_id),
    )

    override_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO classification_overrides
           (override_id, group_id, series_canonical, character_canonical,
            folder_locale, reason, source, enabled, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 'manual', 1, ?, ?)""",
        (
            override_id, group_id,
            series_canonical, character_canonical,
            folder_locale, reason,
            now, now,
        ),
    )
    conn.commit()
    return override_id


def clear_override_for_group(conn: sqlite3.Connection, group_id: str) -> None:
    """group_id의 모든 활성 override를 비활성화(soft delete)한다."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE classification_overrides SET enabled = 0, updated_at = ? "
        "WHERE group_id = ? AND enabled = 1",
        (now, group_id),
    )
    conn.commit()


def apply_override_to_preview_item(
    conn: sqlite3.Connection,
    preview_item: dict,
    override: dict,
    *,
    config: Optional[dict] = None,
) -> dict:
    """
    preview_item의 destinations를 override 기준으로 재계산해 반환한다.

    rule_type → "manual_override"
    경고 메시지 → "manual_override" 추가

    config가 없으면 기존 destinations의 경로에서 classified_dir를 추론한다.
    """
    import copy
    result = copy.deepcopy(preview_item)

    classified_dir = _extract_classified_dir(preview_item, config)
    if not classified_dir:
        return result

    series    = override.get("series_canonical") or ""
    character = override.get("character_canonical") or ""
    locale    = override.get("folder_locale") or preview_item.get("folder_locale") or "canonical"
    filename  = Path(preview_item.get("source_path", "")).name

    use_locale = locale != "canonical" and conn is not None

    def _display(canonical: str, tag_type: str, parent: str = "") -> tuple[str, bool]:
        if not use_locale or not canonical:
            return canonical, False
        return resolve_display_name_with_info(
            conn, canonical, tag_type,
            parent_series=parent or None,
            locale=locale,
            fallback_locale="canonical",
        )

    base = Path(classified_dir)
    new_dests: list[dict] = []

    # PR #122: 카테고리 폴더 (BySeries / ByCharacter) 도 folder_name_language /
    # folder_locale 에 따라 로컬라이즈된다. config 가 별도로 전달되면 거기에서
    # folder_name_language 를 우선 읽고, 없으면 override 의 folder_locale 사용.
    cat_lang = (
        ((config or {}).get("folder_name_language") or "").strip()
        or locale
    )
    by_series_label    = resolve_category_folder("by_series",    cat_lang)
    by_character_label = resolve_category_folder("by_character", cat_lang)
    uncategorized_label = resolve_uncategorized_folder(cat_lang)

    if series and character:
        s_display, s_fb = _display(series, "series")
        c_display, c_fb = _display(character, "character", series)
        folder = (
            base
            / by_series_label
            / sanitize_path_component(s_display)
            / sanitize_path_component(c_display)
        )
        new_dests.append({
            "rule_type":           "manual_override",
            "dest_path":           str(folder / filename),
            "conflict":            "none",
            "will_copy":           True,
            "series_canonical":    series,
            "series_display":      s_display,
            "character_canonical": character,
            "character_display":   c_display,
            "locale":              locale,
            "used_fallback":       s_fb or c_fb,
            "override_note":       "manual_override",
        })
    elif series:
        s_display, s_fb = _display(series, "series")
        folder = (
            base
            / by_series_label
            / sanitize_path_component(s_display)
            / uncategorized_label
        )
        new_dests.append({
            "rule_type":        "manual_override",
            "dest_path":        str(folder / filename),
            "conflict":         "none",
            "will_copy":        True,
            "series_canonical": series,
            "series_display":   s_display,
            "locale":           locale,
            "used_fallback":    s_fb,
            "override_note":    "manual_override",
        })
    elif character:
        c_display, c_fb = _display(character, "character")
        folder = base / by_character_label / sanitize_path_component(c_display)
        new_dests.append({
            "rule_type":           "manual_override",
            "dest_path":           str(folder / filename),
            "conflict":            "none",
            "will_copy":           True,
            "character_canonical": character,
            "character_display":   c_display,
            "locale":              locale,
            "used_fallback":       c_fb,
            "override_note":       "manual_override",
        })

    if new_dests:
        result["destinations"] = new_dests
        result["estimated_copies"] = sum(1 for d in new_dests if d["will_copy"])

    return result


def _extract_classified_dir(preview_item: dict, config: Optional[dict]) -> str:
    """config 또는 기존 destinations에서 classified_dir를 추론한다.

    PR #122: 카테고리 폴더가 ko / ja / en 으로 로컬라이즈될 수 있으므로
    ``CATEGORY_FOLDER_LABELS`` 의 모든 locale 라벨을 marker 후보로 사용한다.
    """
    if config:
        # PR #122: output_dir 가 설정돼 있으면 그것을 우선 (사용자 친화적 alias).
        return config.get("output_dir") or config.get("classified_dir", "")

    from core.folder_localization import CATEGORY_FOLDER_LABELS
    markers: set[str] = set()
    for labels in CATEGORY_FOLDER_LABELS.values():
        for label in labels.values():
            markers.add(f"/{label}/")

    for dest in preview_item.get("destinations", []):
        p = dest.get("dest_path", "")
        if not p:
            continue
        p_norm = p.replace("\\", "/")
        for marker in markers:
            idx = p_norm.find(marker)
            if idx >= 0:
                return p[:idx]
    return ""
