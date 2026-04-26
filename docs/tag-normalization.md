# 태그 정규화 시스템

Aru Archive의 태그 후보 생성 및 사용자 승인 기반 정규화 파이프라인입니다.

---

## 1. 핵심 원칙

> **Aru Archive는 Pixiv 태그를 자동으로 확정하지 않습니다.**  
> 관측 데이터와 동시 등장 패턴으로 후보를 생성하고,  
> **사용자가 승인한 후보만** `tag_aliases`로 승격합니다.

이 원칙은 오탐(false positive) 정규화로 인한 분류 오염을 방지합니다.

---

## 2. 구성 요소

### DB 테이블

| 테이블 | 역할 |
|--------|------|
| `tags` | 정규화된 태그 저장 (group_id 연결) |
| `tag_aliases` | raw tag → canonical tag 1:1 매핑 |
| `tag_observations` | 작품별 raw tag / translation 등장 이력 |
| `tag_candidates` | 정규화 후보 큐 (confidence_score 포함) |

### 모듈

| 모듈 | 역할 |
|------|------|
| `core/tag_observer.py` | `record_tag_observations()` — 관측값 기록 |
| `core/tag_candidate_generator.py` | `generate_tag_candidates_for_group()` — 후보 생성 |
| `core/tag_candidate_actions.py` | `accept_candidate()` / `reject_candidate()` |
| `app/views/tag_candidate_view.py` | TagCandidateView — 사용자 승인 UI |

---

## 3. 파이프라인 흐름

```
CoreWorker (저장 시)
  │
  ├─ tag_observer.record_tag_observations()
  │    ↓
  │  tag_observations 테이블에 기록
  │  (source_site, artwork_id, group_id, raw_tag, translated_tag, artist_id)
  │
  └─ tag_candidate_generator.generate_tag_candidates_for_group()
       ↓
     tag_candidates 테이블에 후보 생성
     (raw_tag, suggested_alias, confidence_score, status=pending)


사용자 (TagCandidateView)
  │
  ├─ [승인] → accept_candidate()
  │    ↓
  │  tag_aliases INSERT (raw_tag → canonical_tag)
  │  tag_candidates 상태 → accepted
  │
  └─ [거부] → reject_candidate()
       ↓
     tag_candidates 상태 → rejected (이후 동일 후보 재생성 억제)
```

---

## 4. confidence_score

`tag_candidates.confidence_score`는 0.0 ~ 1.0 범위의 자동 생성 신뢰도 점수입니다.

| 점수 범위 | 의미 |
|-----------|------|
| 0.9 ~ 1.0 | 번역 정보 일치, 높은 신뢰 |
| 0.5 ~ 0.9 | 동시 등장 패턴 기반 추정 |
| 0.0 ~ 0.5 | 약한 패턴, 사용자 검토 필요 |

> blacklist(거부 목록)에 등록된 태그는 `confidence_score`에 관계없이 후보 생성에서 제외됩니다.

---

## 5. tag_aliases 구조

```sql
CREATE TABLE tag_aliases (
    alias_id       TEXT PRIMARY KEY,
    raw_tag        TEXT NOT NULL,          -- 원본 태그 (예: "キャラA")
    canonical_tag  TEXT NOT NULL,          -- 정규화 태그 (예: "CharacterA")
    tag_type       TEXT DEFAULT 'general', -- general | character | series
    source         TEXT DEFAULT 'user',    -- user | auto
    created_at     TEXT NOT NULL
);
```

- `raw_tag → canonical_tag` 1:1 매핑
- `source='user'`: 사용자가 TagCandidateView에서 승인
- `source='auto'`: 향후 자동 승인 기능 (현재 미구현)

---

## 6. tag_candidates 상태값

| status | 의미 |
|--------|------|
| `pending` | 사용자 검토 대기 |
| `accepted` | 승인됨 → `tag_aliases`에 반영 |
| `rejected` | 거부됨 → 동일 패턴 재생성 억제 |
| `superseded` | 더 높은 신뢰도 후보로 대체됨 |

---

## 7. TagCandidateView 사용법

1. PyQt6 Main App → **`[🏷 태그 후보]`** 버튼 클릭
2. 대기 중인 후보 목록 확인 (raw tag, 제안 alias, confidence score)
3. 각 항목에서 **승인** 또는 **거부** 선택
4. 승인된 항목은 즉시 `tag_aliases`에 반영되어 이후 분류에 사용됨

---

## 8. 분류와의 연계

분류 엔진(`core/classifier.py`)은 경로 결정 시 `tag_aliases`를 조회합니다.

```
raw tag "キャラA" → alias 조회 → "CharacterA" → ByCharacter/CharacterA/
```

tag_aliases에 등록되지 않은 태그는 원본 Pixiv 태그 그대로 사용합니다.

---

## 9. Built-in Tag Packs

`resources/tag_packs/` 디렉터리의 JSON 파일에서 시리즈/캐릭터 alias와 로컬라이제이션을 일괄 등록합니다.

```json
{
  "pack_id": "blue_archive",
  "name": "Blue Archive",
  "version": "1.0.0",
  "series": [
    {
      "canonical": "Blue Archive",
      "aliases": ["ブルーアーカイブ", "BlueArchive", "블루 아카이브", ...],
      "localizations": {"ko": "블루 아카이브", "ja": "ブルーアーカイブ", "en": "Blue Archive"}
    }
  ],
  "characters": [
    {
      "canonical": "陸八魔アル",
      "parent_series": "Blue Archive",
      "aliases": ["アル", "Rikuhachima Aru", "아루", ...],
      "localizations": {"ko": "리쿠하치마 아루", ...}
    }
  ]
}
```

### 적용 순서

앱 시작 / DB 초기화 시 `seed_builtin_tag_packs(conn)` 가 자동 호출됩니다.

```
resources/tag_packs/*.json
  → seed_tag_pack() — INSERT OR IGNORE into tag_aliases, tag_localizations
  → source = "built_in_pack:{pack_id}"
```

`INSERT OR IGNORE` 이므로 중복 시드는 무해합니다.

### 4단계 alias 매칭 (tag_classifier)

`classify_pixiv_tags()` 가 raw Pixiv 태그를 분류할 때 적용하는 순서:

1. **DB alias 정확 매칭** — `tag_aliases (enabled=1)` 우선
2. **built-in alias 정확 매칭** — `SERIES_ALIASES`, `CHARACTER_ALIASES`
3. **DB alias 정규화 매칭** — `normalize_tag_key()` 적용
4. **built-in alias 정규화 매칭**

`normalize_tag_key()` 는 NFKC → casefold → 공백/중점/하이픈/슬래시 제거를 수행합니다.  
`ＢｌｕｅＡｒｃｈｉｖｅ` (전각), `Blue Archive`, `BlueArchive` 가 모두 `"bluearchive"` 로 매핑됩니다.

---

## 10. 분류 실패 원인 (Classification Failure Candidates)

시리즈/캐릭터 태그가 없거나 불완전한 그룹을 일괄 분류 미리보기 시 자동으로 감지하고 후보를 생성합니다.

### 실패 유형

| 유형 | 조건 | classification_reason |
|------|------|----------------------|
| `series_uncategorized` | series 태그 있음, character 태그 없음 | `series_detected_but_character_missing` |
| `author_fallback` | series / character 태그 모두 없음 | `series_and_character_missing` |

### 후보 생성 규칙

```
series_uncategorized → suggested_type='character', score=0.35, parent_series=series_context
author_fallback      → suggested_type='general',   score=0.20
```

후보는 `source="classification_failure"` 로 `tag_candidates`에 저장됩니다.  
**자동 확정 금지** — 사용자가 TagCandidateView에서 직접 승인해야 `tag_aliases`에 반영됩니다.

### TagCandidateView 소스 필터

`[🏷 태그 후보]` 뷰에서 **소스 필터** 콤보박스로 `classification_failure` 항목만 표시할 수 있습니다.

---

## 11. 외부 사전 (External Dictionary Sources)

Danbooru 등 외부 사전에서 캐릭터/시리즈 후보를 가져와 스테이징할 수 있습니다.

### 흐름

```
[🌐 웹 사전] 버튼 → DictionaryImportView
  │
  ├─ 시리즈 이름 입력 → [🔍 가져오기]
  │    ↓
  │  DanbooruSourceAdapter.fetch_character_candidates()
  │    ↓
  │  import_external_entries() → external_dictionary_entries (status='staged')
  │
  ├─ 사용자가 항목 선택 → [✅ 승인]
  │    ↓
  │  accept_external_entry()
  │    ↓
  │  tag_aliases INSERT (alias 있을 때)
  │  tag_localizations INSERT (locale + display_name 있을 때)
  │  status → 'accepted'
  │
  └─ [❌ 거부] / [⏭ 무시] → status='rejected' / 'ignored'
```

### external_dictionary_entries 상태값

| status | 의미 |
|--------|------|
| `staged` | 검토 대기 |
| `accepted` | 승인됨 → `tag_aliases` / `tag_localizations`에 반영 |
| `rejected` | 거부됨 |
| `ignored` | 무시됨 (재검토 가능) |

### confidence_score 구성 (외부 사전)

| 조건 | 가중치 |
|------|--------|
| base | +0.20 |
| Danbooru category가 character/copyright | +0.35 |
| parent series 확인됨 | +0.25 |
| Pixiv observation 일치 | +0.20 |
| Danbooru alias 관계 존재 | +0.15 |
| Danbooru implication 정보 | +0.15 |
| localization 후보 존재 | +0.10 |
| alias 너무 짧음 (≤3자) | −0.30 |
| 여러 series에서 동시 등장 | −0.40 |
| general blacklist 태그 | −0.50 |

### 관련 모듈

| 모듈 | 역할 |
|------|------|
| `core/dictionary_sources/danbooru_source.py` | Danbooru API 어댑터 |
| `core/dictionary_sources/matcher.py` | Pixiv 태그 ↔ Danbooru 후보 매칭 |
| `core/external_dictionary.py` | CRUD + 승격 서비스 |
| `app/views/dictionary_import_view.py` | 외부 사전 가져오기 UI |

---

## 12. 주의사항

- 자동 승인은 구현되어 있지 않습니다. 모든 alias 생성에는 사용자 확인이 필요합니다.
- `reject_candidate()`로 거부한 항목은 동일 `(raw_tag, suggested_alias)` 쌍에 대해 재생성되지 않습니다.
- 이미 `tag_aliases`에 등록된 raw_tag에 대한 중복 후보는 생성되지 않습니다.
- 외부 사전 후보는 사용자 승인 없이 `tag_aliases`/`tag_localizations`에 자동 반영되지 않습니다.
