"""
시각적 중복 그룹에서 keep/delete 후보를 자동 선택하는 pure decision policy.

이 모듈은 file system을 변경하지 않으며 DB / UI / 외부 자원도 호출하지
않는다. 결과(VisualDuplicateDecision)는 사용자 확정 전 단계의 후보일
뿐이며, 실제 파일 삭제는 core/delete_manager 흐름에서만 수행된다.

선택 규칙 (우선순위 순):
1. 해상도(width × height) 큰 파일 keep
2. 동일 해상도 → webp 우선
3. 동일 조건 → 파일명 stem에 "(N)" 복제 suffix 없는 쪽 우선
4. 그래도 동률 → file_size 큰 쪽 우선
5. 완전 동률 → filename 알파벳 첫 번째

해상도가 item dict에 포함되어 있지 않으면 (`_width` / `_height` 키 부재)
PIL.Image.open(file_path).size로 on-demand 측정하며, 측정 실패 시
(0, 0)으로 안전 fallback한다. PIL 예외는 외부로 던지지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


# 파일명 stem 끝의 "(숫자)" 복제 suffix 패턴.
# 매칭 예: "image (1)", "image(2)", "image (10)"
# 비매칭: "Picture (Final)" (digits 요구), "(123)image" (끝이 아님)
_COPY_SUFFIX_RE = re.compile(r"\s*\(\d+\)\s*$")


@dataclass(frozen=True)
class VisualDuplicateDecision:
    """단일 파일에 대한 자동 keep/delete 선택 결과 (불변)."""
    file_id:  str
    decision: str    # "keep" 또는 "delete"
    reason:   str    # UI/로그용 한 줄 설명
    score:    tuple  # build_visual_duplicate_keep_score 결과 (디버깅 / 투명성)


# ---------------------------------------------------------------------------
# 단위 helper (테스트 가능)
# ---------------------------------------------------------------------------

def has_copy_suffix(filename: str) -> bool:
    """파일명 stem 끝에 '(숫자)' 복제 suffix가 있으면 True.

    예:
        image.jpg              → False
        image (1).jpg          → True
        image(10).png          → True
        Picture (Final).jpg    → False  (digits 요구)
    """
    return bool(_COPY_SUFFIX_RE.search(Path(filename).stem))


def _safe_dimensions(file_path: str) -> tuple[int, int]:
    """Pillow로 (width, height)를 읽는다. 실패 시 (0, 0).

    PIL ImportError / 파일 부재 / 손상 이미지 모두 silent fallback.
    file system 쓰기 0건, 외부로 예외 전파 0건.
    """
    if not file_path:
        return (0, 0)
    try:
        from PIL import Image
    except ImportError:
        return (0, 0)
    try:
        with Image.open(file_path) as img:
            w, h = img.size
        return int(w), int(h)
    except Exception:
        return (0, 0)


def _resolve_dimensions(item: dict) -> tuple[int, int]:
    """item의 _width/_height 우선, 없으면 file_path에서 측정."""
    w = item.get("_width") or 0
    h = item.get("_height") or 0
    if w and h:
        return int(w), int(h)
    return _safe_dimensions(item.get("file_path", "") or "")


def _resolve_extension(item: dict) -> str:
    """item['file_format'] 우선, 없으면 Path(file_path).suffix."""
    ext = item.get("file_format")
    if ext:
        return str(ext).lower().lstrip(".")
    fp = item.get("file_path", "") or ""
    return Path(fp).suffix.lower().lstrip(".")


def build_visual_duplicate_keep_score(item: dict) -> tuple:
    """
    오름차순 정렬 시 첫 항목이 keep 후보가 되는 score tuple을 만든다.
    각 sub-key는 'lower wins' 의미.

    Sub-key (5단계):
        0. -pixels       (해상도 큰 쪽이 작은 키 → 우선)
        1. ext_pref       (webp=0, 그 외=1)
        2. copy_flag      (no suffix=0, has suffix=1)
        3. -file_size     (큰 쪽 우선)
        4. filename lower (알파벳 정렬 tie-breaker)
    """
    file_path = item.get("file_path", "") or ""
    filename  = Path(file_path).name
    ext       = _resolve_extension(item)
    file_size = int(item.get("file_size") or 0)
    width, height = _resolve_dimensions(item)
    pixels = width * height

    ext_pref  = 0 if ext == "webp" else 1
    copy_flag = 1 if has_copy_suffix(filename) else 0

    return (-pixels, ext_pref, copy_flag, -file_size, filename.lower())


# ---------------------------------------------------------------------------
# 그룹 단위 decision
# ---------------------------------------------------------------------------

def decide_visual_duplicate_group(
    items: list[dict],
) -> list[VisualDuplicateDecision]:
    """단일 duplicate group에서 keep 1개 + 나머지 delete로 분류한다.

    빈 그룹 → [].
    1개 그룹 → keep 1개.
    2개 이상 → 정책상 1순위가 keep, 나머지는 delete.

    file system은 절대 변경하지 않는다.
    """
    if not items:
        return []

    if len(items) == 1:
        item = items[0]
        score = build_visual_duplicate_keep_score(item)
        return [VisualDuplicateDecision(
            file_id=item.get("file_id", "") or "",
            decision="keep",
            reason="단일 항목 그룹",
            score=score,
        )]

    sorted_items = sorted(items, key=build_visual_duplicate_keep_score)
    keep_item   = sorted_items[0]
    keep_score  = build_visual_duplicate_keep_score(keep_item)

    decisions: list[VisualDuplicateDecision] = []
    for idx, item in enumerate(sorted_items):
        score = build_visual_duplicate_keep_score(item)
        if idx == 0:
            decisions.append(VisualDuplicateDecision(
                file_id=item.get("file_id", "") or "",
                decision="keep",
                reason=_keep_reason(score),
                score=score,
            ))
        else:
            decisions.append(VisualDuplicateDecision(
                file_id=item.get("file_id", "") or "",
                decision="delete",
                reason=_delete_reason(score, keep_score, item),
                score=score,
            ))
    return decisions


def decide_visual_duplicate_groups(
    groups: Iterable[dict],
) -> list[list[VisualDuplicateDecision]]:
    """find_visual_duplicates 출력 (list[{"files", "distance"}])을 받아
    그룹별 결정 리스트를 반환한다.
    """
    return [
        decide_visual_duplicate_group(g.get("files", []) or [])
        for g in groups
    ]


# ---------------------------------------------------------------------------
# reason 생성 (사람이 읽을 수 있는 짧은 설명)
# ---------------------------------------------------------------------------

def _keep_reason(score: tuple) -> str:
    """우선순위가 어떤 단계에서 결정되었는지 한 줄 설명.

    score 형식: (-pixels, ext_pref, copy_flag, -file_size, filename_lower)
    """
    pixels    = -score[0]
    ext_pref  = score[1]
    copy_flag = score[2]
    file_size = -score[3]
    if pixels > 0:
        return f"가장 높은 해상도 ({pixels:,} px)"
    if ext_pref == 0:
        return "webp 형식 우선"
    if copy_flag == 0:
        return "(N) 복제 suffix 없음"
    if file_size > 0:
        return "파일 크기 우선"
    return "파일명 알파벳 첫 번째"


def _delete_reason(
    score: tuple,
    keep_score: tuple,
    item: dict,
) -> str:
    """item이 왜 delete 후보가 되었는지 한 줄 설명."""
    item_pixels = -score[0]
    keep_pixels = -keep_score[0]
    if item_pixels < keep_pixels:
        return (
            f"keep 후보보다 낮은 해상도 "
            f"({item_pixels:,} < {keep_pixels:,} px)"
        )
    filename = Path(item.get("file_path", "") or "").name
    if has_copy_suffix(filename):
        return "복제 suffix '(N)' 포함"
    item_ext  = _resolve_extension(item)
    if item_ext != "webp" and keep_score[1] == 0:
        return "webp 형식이 keep 후보"
    return "동률 — keep 후보가 정책상 우선"
