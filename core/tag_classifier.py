"""
Pixiv 태그 분류 모듈.

이 모듈은 Pixiv 원본 태그를 앱 내부에서 쓰는 3개 버킷으로 나눈다.

- tags: 일반 검색/표시용 태그
- series_tags: 작품/게임/시리즈 기준 분류 경로용 태그
- character_tags: 캐릭터 기준 분류 경로용 태그

분류 결과는 core.metadata_enricher와 app.main_window의 수동 재분류 액션에서
artwork_groups.*_tags_json 및 tags 테이블로 저장된다.
"""
from __future__ import annotations

# 시리즈 별칭은 사용자가 Pixiv에서 실제로 마주치는 표기 차이를 canonical명으로 묶는다.
# 분류 폴더명에는 canonical명이 사용되므로, 여기의 값 변경은 파일 경로 정책에도 영향을 준다.
SERIES_ALIASES: dict[str, str] = {
    "ブルーアーカイブ": "Blue Archive",
    "ブルアカ":         "Blue Archive",
    "BlueArchive":      "Blue Archive",
    "Blue Archive":     "Blue Archive",
    "블루 아카이브":    "Blue Archive",
    "블아":             "Blue Archive",
}

# 캐릭터 별칭은 canonical 캐릭터명과 소속 시리즈를 함께 가진다.
# 캐릭터가 식별되면 series_tags에도 소속 시리즈를 자동 보강한다.
CHARACTER_ALIASES: dict[str, dict] = {
    "伊落マリー":       {"canonical": "伊落マリー", "series": "Blue Archive"},
    "水羽ミモリ":       {"canonical": "水羽ミモリ", "series": "Blue Archive"},
    "陸八魔アル":       {"canonical": "陸八魔アル", "series": "Blue Archive"},
    "リクハチマ・アル": {"canonical": "陸八魔アル", "series": "Blue Archive"},
    "Rikuhachima Aru":  {"canonical": "陸八魔アル", "series": "Blue Archive"},
}


def load_db_aliases(conn) -> tuple[dict[str, str], dict[str, dict]]:
    """DB tag_aliases (enabled=1)에서 시리즈/캐릭터 alias를 로드한다."""
    series: dict[str, str] = {}
    chars: dict[str, dict] = {}
    try:
        rows = conn.execute(
            "SELECT alias, canonical, tag_type, parent_series "
            "FROM tag_aliases WHERE enabled = 1"
        ).fetchall()
        for row in rows:
            if row["tag_type"] == "series":
                series[row["alias"]] = row["canonical"]
            elif row["tag_type"] == "character":
                chars[row["alias"]] = {
                    "canonical": row["canonical"],
                    "series":    row["parent_series"] or "",
                }
    except Exception:
        pass
    return series, chars


def classify_pixiv_tags(raw_tags: list[str], conn=None) -> dict:
    """
    Pixiv 태그 목록을 general / series / character로 분류한다.

    - SERIES_ALIASES(+ DB aliases)에 있는 태그 → series_tags (canonical명)
    - CHARACTER_ALIASES(+ DB aliases)에 있는 태그 → character_tags (canonical명) + 연관 series 자동 추가
    - 그 외 → tags (일반 태그, 원본 순서 유지·중복 제거)

    conn: sqlite3.Connection (None이면 built-in aliases만 사용)

    Returns:
        {"tags": [...], "series_tags": [...], "character_tags": [...]}
    """
    series_aliases = dict(SERIES_ALIASES)
    char_aliases   = dict(CHARACTER_ALIASES)
    if conn is not None:
        db_series, db_chars = load_db_aliases(conn)
        series_aliases.update(db_series)
        char_aliases.update(db_chars)

    series_set: set[str] = set()
    character_set: set[str] = set()
    classified_raw: set[str] = set()

    for tag in raw_tags:
        if tag in series_aliases:
            series_set.add(series_aliases[tag])
            classified_raw.add(tag)
        elif tag in char_aliases:
            info = char_aliases[tag]
            character_set.add(info["canonical"])
            if info.get("series"):
                series_set.add(info["series"])
            classified_raw.add(tag)

    seen: set[str] = set()
    general: list[str] = []
    for tag in raw_tags:
        if tag not in classified_raw and tag not in seen:
            seen.add(tag)
            general.append(tag)

    return {
        "tags":           general,
        "series_tags":    sorted(series_set),
        "character_tags": sorted(character_set),
    }
