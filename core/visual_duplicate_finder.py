"""
시각적 중복(perceptual hash) 검사.

pHash(Perceptual Hash) 기반으로 유사 이미지 후보를 찾는다.
Pillow로 구현하며, 이미지 파일이 아닌 경우는 건너뛴다.

정책:
- 자동 삭제 금지 — 사용자 확인 후 delete_manager에 위임한다.
- 같은 그룹 내 파일끼리는 비교하지 않는다.
- 기본 검사 범위는 inbox_managed (Classified 제외).
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"})


def _flatten_grayscale_pixels(img) -> list[int]:
    """Return grayscale pixel values without relying on Pillow's deprecated getdata()."""
    return list(img.tobytes())


# ---------------------------------------------------------------------------
# pHash 계산
# ---------------------------------------------------------------------------

def compute_perceptual_hash(file_path: str, hash_size: int = 8) -> Optional[str]:
    """
    이미지 파일의 pHash(perceptual hash)를 계산한다.
    Pillow 기반. 이미지를 hash_size×hash_size 그레이스케일로 축소하여
    평균값과 비교한다.

    반환: 64비트 16진수 문자열 (hash_size=8 기준) 또는 None(실패 시).
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow 미설치 — 시각적 중복 검사 불가")
        return None

    try:
        with Image.open(file_path) as img:
            # RGBA → RGB 변환
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            # hash_size+1 크기로 축소, 그레이스케일
            small = img.resize((hash_size + 1, hash_size), Image.LANCZOS)
            gray = small.convert("L")
            pixels = _flatten_grayscale_pixels(gray)

        # 수평 gradient 비교 (pHash)
        bits: list[int] = []
        for row in range(hash_size):
            for col in range(hash_size):
                idx = row * (hash_size + 1) + col
                bits.append(1 if pixels[idx] > pixels[idx + 1] else 0)

        # 비트 배열 → 16진수 문자열
        value = 0
        for bit in bits:
            value = (value << 1) | bit
        return format(value, f"0{hash_size * hash_size // 4}x")
    except Exception as exc:
        logger.debug("pHash 계산 실패 (%s): %s", file_path, exc)
        return None


def hamming_distance(hash_a: str, hash_b: str) -> int:
    """두 16진수 해시의 Hamming distance를 반환한다."""
    try:
        a = int(hash_a, 16)
        b = int(hash_b, 16)
        xor = a ^ b
        return bin(xor).count("1")
    except (ValueError, TypeError):
        return 64  # 비교 불가 → 최대값 반환


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def find_visual_duplicates(
    conn: sqlite3.Connection,
    *,
    threshold: int = 6,
    scope: str = "inbox_managed",
    group_ids: list[str] | None = None,
) -> list[dict]:
    """
    perceptual hash 기반 유사 이미지 후보 그룹을 찾는다.
    자동 삭제하지 않는다.

    threshold: Hamming distance 임계값 (기본 6 — 64비트 기준)
    scope: 검사 범위. 기본 'inbox_managed' (Classified 제외).
           'all_archive'로 변경하면 Classified 포함.
    반환: [{"files": [...], "distance": N}]
    """
    from core.duplicate_finder import select_duplicate_candidate_files

    rows = select_duplicate_candidate_files(conn, scope=scope, group_ids=group_ids)

    # pHash 계산 (이미지 확장자만)
    hashed: list[tuple[dict, str]] = []
    for d in rows:
        fp = d.get("file_path", "")
        ext = Path(fp).suffix.lower()
        if ext not in _IMAGE_EXTS:
            continue
        ph = compute_perceptual_hash(fp)
        if ph:
            hashed.append((d, ph))

    # O(n²) 비교 — 소규모 아카이브 전용
    groups: list[dict] = []
    used: set[int] = set()

    for i, (di, hi) in enumerate(hashed):
        if i in used:
            continue
        cluster = [di]
        max_dist = 0
        for j, (dj, hj) in enumerate(hashed):
            if i == j or j in used:
                continue
            # 같은 group끼리는 비교 안 함
            if di.get("group_id") == dj.get("group_id"):
                continue
            dist = hamming_distance(hi, hj)
            if dist <= threshold:
                cluster.append(dj)
                used.add(j)
                max_dist = max(max_dist, dist)
        if len(cluster) >= 2:
            used.add(i)
            groups.append({
                "files": cluster,
                "distance": max_dist,
            })

    return groups
