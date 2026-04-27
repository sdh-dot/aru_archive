"""
Pixiv 태그 분류 모듈.

이 모듈은 Pixiv 원본 태그를 앱 내부에서 쓰는 3개 버킷으로 나눈다.

- tags: 일반 검색/표시용 태그
- series_tags: 작품/게임/시리즈 기준 분류 경로용 태그
- character_tags: 캐릭터 기준 분류 경로용 태그

분류 결과는 core.metadata_enricher와 app.main_window의 수동 재분류 액션에서
artwork_groups.*_tags_json 및 tags 테이블로 저장된다.

alias 매칭 전략 (2-pass):
  Pass 1 — series direct/normalized 매칭 (character와 독립적으로 수행)
  Pass 2 — character direct/normalized 매칭
           · parent_series를 series_tags에 자동 보강 (inferred_from_character)
           · ambiguous alias(같은 alias → 여러 canonical)는
             series context가 있으면 확정, 없으면 자동 확정 금지

핵심 원칙:
  series_tags가 비어 있어도 character matching을 건너뛰지 않는다.
  character alias의 parent_series로 series를 역추론하는 것은 허용한다.
  series → character 자동 추론은 하지 않는다.
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
# character alias의 series(parent_series)가 있으면 series_tags에 자동 보강한다.
CHARACTER_ALIASES: dict[str, dict] = {
    "伊落マリー":       {"canonical": "伊落マリー", "series": "Blue Archive"},
    "水羽ミモリ":       {"canonical": "水羽ミモリ", "series": "Blue Archive"},
    "陸八魔アル":       {"canonical": "陸八魔アル", "series": "Blue Archive"},
    "リクハチマ・アル": {"canonical": "陸八魔アル", "series": "Blue Archive"},
    "Rikuhachima Aru":  {"canonical": "陸八魔アル", "series": "Blue Archive"},
}


def load_db_aliases(conn) -> tuple[dict[str, str], dict[str, list[dict]]]:
    """DB tag_aliases (enabled=1)에서 시리즈/캐릭터 alias를 로드한다.

    char 결과는 alias → list[{canonical, series}] 형태로 반환한다.
    같은 alias에 여러 canonical이 있으면(parent_series가 다름) ambiguous 처리 대상이다.
    """
    series: dict[str, str] = {}
    chars: dict[str, list[dict]] = {}
    try:
        rows = conn.execute(
            "SELECT alias, canonical, tag_type, parent_series "
            "FROM tag_aliases WHERE enabled = 1"
        ).fetchall()
        for row in rows:
            if row["tag_type"] == "series":
                series[row["alias"]] = row["canonical"]
            elif row["tag_type"] == "character":
                entry = {
                    "canonical": row["canonical"],
                    "series":    row["parent_series"] or "",
                }
                chars.setdefault(row["alias"], []).append(entry)
    except Exception:
        pass
    return series, chars


def _build_normalized_lookup(exact: dict) -> dict[str, str]:
    """
    alias dict의 키를 기반으로 normalized_key → original_alias 매핑을 만든다.
    값의 타입(str 또는 list)은 무관하게 키만 사용한다.
    충돌 시 먼저 등록된 값이 우선한다.
    """
    from core.tag_normalize import normalize_tag_key
    result: dict[str, str] = {}
    for alias in exact:
        nk = normalize_tag_key(alias)
        if nk and nk not in result:
            result[nk] = alias
    return result


def classify_pixiv_tags(raw_tags: list[str], conn=None) -> dict:
    """
    Pixiv 태그 목록을 general / series / character로 분류한다.

    2-pass 매칭:
      Pass 1 — series direct/normalized 매칭 (character와 독립적으로 수행)
      Pass 2 — character direct/normalized 매칭
               · parent_series → series_tags 자동 보강
               · ambiguous alias 처리 (series context 기반 disambiguation)

    conn: sqlite3.Connection (None이면 built-in aliases만 사용)

    Returns:
        {
            "tags":           [...],   # 일반 태그 (original order, deduped)
            "series_tags":    [...],   # canonical series (sorted)
            "character_tags": [...],   # canonical character (sorted)
            "evidence": {
                "series":     [...],   # inferred series evidence entries
                "characters": [...],   # character match evidence entries
            },
            "ambiguous": [...],        # ambiguous alias entries (자동 확정 금지)
        }
    """
    from core.tag_normalize import normalize_tag_key

    # --- alias 로드 ---
    if conn is not None:
        db_series, db_char_groups = load_db_aliases(conn)
        series_aliases: dict[str, str] = dict(SERIES_ALIASES)
        series_aliases.update(db_series)
        # built-in CHARACTER_ALIASES를 list 포맷으로 변환 후 DB와 병합
        char_alias_groups: dict[str, list[dict]] = {
            alias: [info] for alias, info in CHARACTER_ALIASES.items()
        }
        for alias, entries in db_char_groups.items():
            if alias not in char_alias_groups:
                char_alias_groups[alias] = entries
            else:
                existing_canonicals = {e["canonical"] for e in char_alias_groups[alias]}
                for e in entries:
                    if e["canonical"] not in existing_canonicals:
                        char_alias_groups[alias].append(e)
    else:
        series_aliases = dict(SERIES_ALIASES)
        char_alias_groups = {alias: [info] for alias, info in CHARACTER_ALIASES.items()}

    norm_series = _build_normalized_lookup(series_aliases)
    norm_chars  = _build_normalized_lookup(char_alias_groups)

    # ===== Pass 1: Series matching (character와 독립적으로 선행 수행) =====
    series_set: set[str] = set()
    series_classified: set[str] = set()

    for tag in raw_tags:
        if tag in series_aliases:
            series_set.add(series_aliases[tag])
            series_classified.add(tag)
            continue
        nk = normalize_tag_key(tag)
        if nk and nk in norm_series:
            series_set.add(series_aliases[norm_series[nk]])
            series_classified.add(tag)

    # direct series match 스냅샷 — character disambiguation 및 inferred evidence에 사용
    direct_series: frozenset[str] = frozenset(series_set)

    # ===== Pass 2: Character matching (series_set 유무와 무관하게 수행) =====
    character_set: set[str] = set()
    char_classified: set[str] = set()
    evidence_series: list[dict] = []
    evidence_chars:  list[dict] = []
    ambiguous_tags:  list[dict] = []

    for tag in raw_tags:
        if tag in series_classified:
            continue  # 이미 series로 분류된 태그는 건너뜀

        entries: list[dict] | None = None
        match_type = ""

        if tag in char_alias_groups:
            entries    = char_alias_groups[tag]
            match_type = "exact"
        else:
            nk = normalize_tag_key(tag)
            if nk and nk in norm_chars:
                entries    = char_alias_groups[norm_chars[nk]]
                match_type = "normalized"

        if entries is None:
            continue

        if len(entries) == 1:
            # 명확한 단일 매칭
            info        = entries[0]
            canonical   = info["canonical"]
            char_series = info.get("series", "")

            character_set.add(canonical)
            char_classified.add(tag)

            if char_series:
                if char_series not in direct_series:
                    # series direct match가 없음 → character alias로부터 역추론
                    evidence_series.append({
                        "canonical":         char_series,
                        "source":            "inferred_from_character",
                        "matched_character": canonical,
                        "matched_raw_tag":   tag,
                    })
                series_set.add(char_series)

            evidence_chars.append({
                "canonical":     canonical,
                "source":        "tag_aliases",
                "matched_raw_tag": tag,
                "parent_series": char_series,
                "match_type":    match_type,
            })

        else:
            # Ambiguous: 같은 alias → 여러 canonical
            # direct series context로 disambiguation 시도
            matching = [e for e in entries if e.get("series") in direct_series]

            if len(matching) == 1:
                # series context로 단일 확정
                info        = matching[0]
                canonical   = info["canonical"]
                char_series = info.get("series", "")

                character_set.add(canonical)
                char_classified.add(tag)
                # series는 이미 direct_series에 있으므로 inferred evidence 추가 불필요

                evidence_chars.append({
                    "canonical":               canonical,
                    "source":                  "tag_aliases",
                    "matched_raw_tag":         tag,
                    "parent_series":           char_series,
                    "match_type":              match_type,
                    "disambiguated_by_series": True,
                })
            else:
                # 진짜 ambiguous — 자동 확정 금지
                ambiguous_tags.append({
                    "raw_tag": tag,
                    "reason":  "ambiguous_character_alias",
                    "candidates": [
                        {
                            "canonical":     e["canonical"],
                            "parent_series": e.get("series", ""),
                        }
                        for e in entries
                    ],
                })

    # 일반 태그 (series / character로 분류되지 않은 것, original order 유지 + dedup)
    all_classified = series_classified | char_classified
    seen: set[str] = set()
    general: list[str] = []
    for tag in raw_tags:
        if tag not in all_classified and tag not in seen:
            seen.add(tag)
            general.append(tag)

    return {
        "tags":           general,
        "series_tags":    sorted(series_set),
        "character_tags": sorted(character_set),
        "evidence": {
            "series":     evidence_series,
            "characters": evidence_chars,
        },
        "ambiguous": ambiguous_tags,
    }
