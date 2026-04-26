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
