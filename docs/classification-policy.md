# 분류 정책

Aru Archive의 아트워크 파일 분류 규칙입니다.

---

## 1. 기본 원칙

- 분류는 **Inbox 파일을 Classified 디렉터리로 복사**합니다. 원본은 보존됩니다.
- 분류 전 반드시 **미리보기**(`[📋 분류 미리보기]`)로 경로를 확인합니다.
- 분류 실행 후 **Undo**가 가능합니다 (복사본 한정, 보존 기간 내).

---

## 2. 4단계 우선순위 (Tier System)

```
Tier 1: BySeries/{series}/{character}/{filename}
Tier 2: BySeries/{series}/_uncategorized/{filename}
Tier 3: ByCharacter/{character}/{filename}
Tier 4: ByAuthor/{artist}/{filename}   ← fallback
```

### 분류 결정 흐름

```
series 태그 있음?
  └─ yes → character 태그 있음?
                └─ yes → Tier 1: BySeries/{series}/{character}/
                └─ no  → Tier 2: BySeries/{series}/_uncategorized/
  └─ no  → character 태그 있음?
                └─ yes → Tier 3: ByCharacter/{character}/
                └─ no  → Tier 4: ByAuthor/{artist}/   (enable_by_author=true 시)
```

---

## 3. 설정 옵션 (config.json)

```json
{
  "classification": {
    "primary_strategy":              "series_character",
    "enable_series_character":        true,
    "enable_series_uncategorized":    true,
    "enable_character_without_series": true,
    "fallback_by_author":             true,
    "enable_by_author":               false,
    "enable_by_tag":                  false,
    "on_conflict":                    "rename"
  }
}
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `enable_series_character` | `true` | Tier 1 활성화 |
| `enable_series_uncategorized` | `true` | Tier 2 활성화 |
| `enable_character_without_series` | `true` | Tier 3 활성화 |
| `fallback_by_author` | `true` | 위 조건 미충족 시 Tier 4 적용 |
| `enable_by_author` | `false` | ByAuthor를 항상 추가 생성 (주 분류와 별도) |
| `enable_by_tag` | `false` | ByTag 활성화 |
| `on_conflict` | `"rename"` | 경로 충돌 처리: `rename` / `skip` / `overwrite` |

---

## 4. ByAuthor 정책

`ByAuthor`는 **기본적으로 fallback**입니다.

| 설정 | 동작 |
|------|------|
| `fallback_by_author=true` (기본) | series/character 태그가 모두 없을 때만 `ByAuthor/` 사용 |
| `enable_by_author=true` | series/character 분류와 **별도로** 항상 `ByAuthor/`에도 복사 |

> `enable_by_author`를 활성화하면 동일 파일이 두 경로에 복사됩니다.

---

## 5. ByTag 정책

`ByTag`는 **기본 비활성**입니다.

| 설정 | 동작 |
|------|------|
| `enable_by_tag=false` (기본) | ByTag 분류 없음 |
| `enable_by_tag=true` | `ByTag/{tag}/{filename}` 경로에 일반 태그별 복사 수행 |

> 태그 수가 많으면 디렉터리 구조가 크게 확장될 수 있습니다.

---

## 6. 충돌 처리 (`on_conflict`)

| 값 | 동작 |
|----|------|
| `rename` (기본) | `{filename}_1.ext`, `{filename}_2.ext` 순으로 번호 추가 |
| `skip` | 이미 파일이 있으면 복사 건너뜀 |
| `overwrite` | 기존 파일 덮어씀 |

---

## 7. 태그 정규화와 분류

분류 시 `tag_aliases` 테이블을 통해 태그가 정규화됩니다.

```
raw tag "캐릭터A" → alias "CharacterA" → ByCharacter/CharacterA/
```

태그 정규화 상세 → [tag-normalization.md](tag-normalization.md) 참고

---

## 8. 분류 가능 상태

`artwork_files.metadata_sync_status`가 다음 값인 파일만 분류 대상입니다.

```
full | json_only | xmp_write_failed
```

`pending` 또는 `metadata_write_failed` 상태 파일은 분류 미리보기에서 제외됩니다.

---

## 9. copy_records 및 Undo

분류 실행 시 `copy_records`에 복사 이력이, `undo_entries`에 안전 Undo 정보가 기록됩니다.

| 항목 | 내용 |
|------|------|
| 보존 기간 | `undo_retention_days` (기본 7일) |
| Undo 대상 | Classified 복사본만 삭제 (원본·managed 보호) |
| 검증 | dest 파일 SHA-256 해시 + mtime 일치 여부 확인 후 삭제 |

Undo 상세 정책 → [architecture.md — Undo 흐름](ARCHITECTURE.md) 참고

---

## 10. 다국어 폴더명 (Localized Folder Names)

폴더명을 `folder_locale` 설정에 따라 현지화할 수 있습니다. 메타데이터의 canonical 태그값은 변경되지 않으며, 복사 경로(폴더명)만 현지화됩니다.

```json
{
  "classification": {
    "folder_locale":               "ko",
    "fallback_locale":             "canonical",
    "enable_localized_folder_names": true
  }
}
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `folder_locale` | `"ko"` | 폴더명에 사용할 언어: `canonical` / `ko` / `ja` / `en` |
| `fallback_locale` | `"canonical"` | 현지화 데이터 없을 때 사용할 언어 |
| `enable_localized_folder_names` | `true` | 현지화 비활성화 시 항상 canonical 사용 |

### 현지화 데이터 우선순위

```
DB (tag_localizations) → BUILTIN → fallback_locale DB → fallback_locale BUILTIN → canonical
```

현지화 데이터가 없으면 canonical 이름으로 폴더를 생성하고 미리보기에 `⚠ fallback` 표시합니다.

### 내장 데이터 (Blue Archive)

내장 로컬라이제이션은 앱 시작 및 DB 초기화 시 자동으로 추가됩니다.

| canonical | ko | ja | en |
|-----------|----|----|-----|
| Blue Archive | 블루 아카이브 | ブルーアーカイブ | Blue Archive |
| 陸八魔アル | 리쿠하치마 아루 | — | — |
| 砂狼シロコ | 스나오카미 시로코 | — | — |
| (외 7개 캐릭터) | | | |

---

## 11. 분류 실패 원인 표시 (Classification Failure Display)

일괄 분류 미리보기에서 series/character 태그가 불완전한 그룹을 자동으로 감지합니다.

### 실패 유형

| 유형 | 조건 | 경고 표시 |
|------|------|-----------|
| `series_uncategorized` | series 태그 있음, character 태그 없음 | `series_uncategorized (시리즈명)` |
| `author_fallback` | series / character 모두 없음 | `author_fallback` |

### 미리보기 요약

```
대상: N개 작품  분류 가능: M개  ...  ⚠ 미분류: series_uncategorized=X / author_fallback=Y  후보 생성: Z건
```

### 일괄 분류 전 태그 재분류

`BatchClassifyDialog`의 **"미리보기 생성 전 태그 재분류 실행"** 체크박스를 활성화하면  
미리보기 생성 전 `retag_groups_from_existing_tags()`가 실행됩니다.

- 기존 `tags_json`을 기반으로 `classify_pixiv_tags(conn=conn)` 재실행
- `series_tags_json`, `character_tags_json`, tags 테이블만 갱신
- 원본 `tags_json` 변경 없음

이 옵션은 태그 팩 업데이트 후 기존 작품을 재분류할 때 유용합니다.

---

## 12. 외부 사전으로 분류 개선 (External Dictionary Import)

외부 사전(Danbooru 등)에서 캐릭터·시리즈 후보를 가져와 alias를 등록하면, 이후 분류에 즉시 반영됩니다.

### 사용 방법

1. 툴바 **`[🌐 웹 사전]`** 버튼 클릭 → DictionaryImportView 열림
2. 소스(Danbooru) 선택 후 시리즈 이름 입력
3. **`[🔍 가져오기]`** — Danbooru에서 캐릭터 후보를 수집하고 `staged` 상태로 저장
4. 테이블에서 항목을 선택 후 **`[✅ 승인]`** — `tag_aliases` / `tag_localizations`에 반영
5. 불필요한 항목은 **`[❌ 거부]`** 또는 **`[⏭ 무시]`**

### 승인 후 태그 재분류

DictionaryImportView의 **"승인 후 현재 목록 태그 재분류 실행"** 체크박스를 활성화하면  
승인 직후 갤러리에 표시된 그룹에 대해 `retag_groups_from_existing_tags()`가 실행됩니다.

> 원본 `tags_json`은 변경하지 않습니다. `series_tags_json`, `character_tags_json`, `tags` 테이블만 갱신합니다.

### 단일 미리보기와의 연계

**`[📋 분류 미리보기]`** 버튼(단일 선택)을 클릭하면 미리보기 생성 직전에  
`retag_groups_from_existing_tags()`가 자동 실행됩니다.  
tag_aliases 업데이트 직후 개별 작품 미리보기를 확인할 때 유용합니다.

---

## 13. 일괄 분류 (Batch Classification)

`[📋 일괄 분류]` 버튼으로 여러 작품을 한 번에 분류할 수 있습니다.

### 대상 범위 (scope)

| 값 | 설명 |
|----|------|
| `selected` | 갤러리에서 Ctrl+Click으로 선택한 항목 |
| `current_filter` | 현재 사이드바 카테고리 표시 중인 전체 항목 |
| `all_classifiable` | DB 전체 분류 가능 항목 |

### 기존 복사본 처리 정책

| 정책 | 동작 |
|------|------|
| `keep_existing` | 기존 복사본 유지, 새 경로에 추가 복사 가능 |
| `skip_existing` | 같은 목적지 파일이 이미 있으면 건너뜀 |

### 워크플로

1. `[📋 일괄 분류]` 클릭 → BatchClassifyDialog 열림
2. 범위 / 폴더명 언어 / 정책 설정 후 `[미리보기 생성]` 클릭
3. 요약 및 목록 확인 후 `[▶ 실행]` 클릭
4. `undo_entries`에 `classify_batch` 레코드 1개 + 복사본마다 `copy_records` 생성
5. `[🕘 작업 로그]`에서 일괄 분류 이력 및 Undo 가능

---

## 14. 권장 워크플로우 (작업 마법사)

초보 사용자는 툴바 **[🧭 작업 마법사]** 를 사용하는 것을 권장합니다.

```
Step 1  작업 폴더 설정
Step 2  Inbox 스캔
Step 3  메타데이터 상태 확인  ← metadata_missing 파악
Step 4  (필요 시) Pixiv 메타데이터 보강
Step 5  사전 검토 — 후보 태그 승인 / 외부 사전 import
Step 6  태그 재분류  ← Step 5에서 alias 변경 시 필수
Step 7  분류 미리보기 생성 → 위험도 확인
Step 8  분류 실행
Step 9  결과 확인 / Undo
```

자세한 설명: [workflow-wizard.md](workflow-wizard.md)

---

## 15. Fallback 순서 (Fallback Order)

분류 엔진은 다음 순서로 분류를 결정합니다.

| 순위 | 조건 | 분류 경로 |
|------|------|-----------|
| 1 | Series + Character 모두 있음 | `BySeries/{series}/{character}/` |
| 2 | Character만 있고 parent_series가 있음 (inferred) | `BySeries/{inferred_series}/{character}/` |
| 3 | Series만 있음 (character 없음) | `BySeries/{series}/_uncategorized/` |
| 4 | Series / Character 모두 없음 | `ByAuthor/{artist}/` (fallback) |
| 5 | Ambiguous character alias (series context 없음) | author_fallback 또는 review candidate 생성 |

### 핵심 원칙

- `author_fallback`으로 가기 전에 **character alias의 parent_series inference**가 먼저 수행됩니다.
- series raw tag가 없어도 character alias의 `parent_series`가 있으면 **Tier 1 분류**가 가능합니다.
- series → character 자동 추론은 **금지**됩니다.

### Inference 흐름 요약

```
raw tags: ["ワカモ(正月)"]
  └─ tag_aliases에 ワカモ(正月) → 狐坂ワカモ / Blue Archive
        ↓
  character_tags: ["狐坂ワカモ"]
  series_tags:    ["Blue Archive"]   ← inferred from character
        ↓
  BySeries/블루 아카이브/코사카 와카모/
```

자세한 내용: [tag-normalization.md — Character-to-Series Inference](tag-normalization.md#15-character-to-series-inference)

---

> **alias 변경 → 태그 재분류 필수 원칙**  
> `tag_aliases`에 새 항목을 추가하거나 기존 alias를 변경한 후에는  
> Step 6 "태그 재분류"를 실행해야 `series_tags_json` / `character_tags_json`이 갱신됩니다.  
> 재분류 없이 분류를 실행하면 이전 alias 상태로 폴더가 생성됩니다.

---

## Manual Classification Overrides

When metadata tags are incomplete, Aru Archive does **not** infer character identity from the artwork title alone by default.

### Title-only candidate policy

```
title: マリーちゃん
raw_tags: ブルーアーカイブ10000users入り, チャイナドレス
```

- `マリーちゃん` is a title hint, not a tag — automatic character confirmation is **prohibited**.
- The preview shows the item as `author_fallback` or `series_uncategorized`.
- The user can manually assign a character in the preview.

### How to use manual overrides

1. Open **일괄 분류** (BatchClassifyDialog) and generate a preview.
2. Select a failure row (`author_fallback` / `series_uncategorized` / `series_detected_character_missing`).
3. Click **[수동 분류 지정]**.
4. Enter series canonical and/or character canonical in the dialog.
5. The preview row is immediately updated with `rule_type = manual_override`.
6. Click **[▶ 실행]** — the override destination is used for the actual file copy.

### Storage

Manual overrides are stored per artwork group in the `classification_overrides` table:

```sql
classification_overrides(
    override_id, group_id,
    series_canonical, character_canonical,
    folder_locale, reason, source, enabled,
    created_at, updated_at
)
```

- Override takes precedence over automatic classification at preview-generation time.
- Removing an override (via **[수동 지정 해제]**) re-runs automatic classification.
- User dictionary alias registration from an override is **not** automatic — it is a separate action (TODO).
