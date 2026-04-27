# Aru Archive — 중복 이미지 관리

---

## 중복의 종류

### 1. 완전 중복 (Exact Duplicate)
- **기준**: SHA-256 hash 동일
- **처리**: 자동 보존 추천 후 사용자 확인 → `DeletePreviewDialog` → 영구 삭제

### 2. 시각적 중복 (Visual Duplicate)
- **기준**: Perceptual hash (pHash) Hamming distance ≤ threshold (기본: 6)
- **처리**: 사용자 비교 확인 후 삭제 대상 선택 → `DeletePreviewDialog` → 영구 삭제
- **자동 삭제 금지** — 반드시 사용자 확인 후 삭제

---

## Duplicate Scan Scope

By default, Aru Archive scans only **Inbox** and **Managed** files for duplicates.

### 지원 scope 값

| scope | 대상 | 설명 |
|-------|------|------|
| `inbox_managed` | Inbox(original) + Managed(managed) | **기본값**. Classified 제외 |
| `inbox_only` | Inbox(original)만 | |
| `managed_only` | Managed(managed)만 | |
| `classified_only` | Classified(classified_copy)만 | 고급 — 복사본 정리용 |
| `all_archive` | 전체 (Classified 포함) | 고급 — 별도 확인 필요 |
| `current_view` | 현재 화면에 보이는 group_ids만 | 현재 카테고리 필터 기준 |
| `selected` | group_ids 지정 항목만 | 갤러리 다중 선택 기준 |

### 기본 제외 대상

기본 scope(`inbox_managed`)에서 다음 파일은 제외됩니다.

| 제외 조건 | 이유 |
|----------|------|
| `file_role = 'classified_copy'` | 분류 복사본과 원본의 오탐 방지 |
| `file_role = 'sidecar'` | 메타데이터 파일은 중복 검사 불필요 |
| `file_status = 'deleted'` | 이미 삭제됨 |
| `file_status = 'missing'` | 실물 없음 |
| Classified 폴더 파일 | classified_copy role로 제외됨 |

### Classified 복사본을 제외하는 이유

```text
Inbox/original.jpg          ← 원본 (original role)
Classified/BySeries/.../original.jpg  ← 분류 결과 복사본 (classified_copy role)
```

두 파일은 SHA-256이 같지만 서로 다른 역할을 가집니다.
기본 scope에서 Classified를 포함하면 사용자가 원하지 않는 오탐이 발생합니다.

### all_archive 고급 옵션

`all_archive` scope는 다음 두 조건이 모두 충족되어야 실행됩니다.

1. `config.json`의 `duplicates.allow_all_archive_scan = true`
2. 실행 전 경고 다이얼로그에서 사용자 확인

```json
{
  "duplicates": {
    "default_scope": "inbox_managed",
    "allow_all_archive_scan": false
  }
}
```

---

## 완전 중복 정리 흐름

```
[🧬 완전 중복 검사]
  → find_exact_duplicates(conn, scope="inbox_managed")
  → build_exact_duplicate_cleanup_preview(conn, dup_groups)
  → 결과 메시지 표시 (그룹 수, 삭제 후보 수, 검사 범위)
  → DeletePreviewDialog 표시
  → execute_delete_preview(confirmed=True)
```

### 보존 파일 추천 기준

우선순위 (낮을수록 보존 우선):

| 순위 | 조건 |
|------|------|
| 1 | `file_role = 'original'` |
| 2 | `metadata_sync_status = 'full'` |
| 3 | `metadata_sync_status = 'json_only'` |
| 4 | Pixiv ID 규칙 파일명 (`{id}_p{n}.ext`) |
| 5 | 더 큰 파일 크기 |
| — | `classified_copy`: 삭제 후보 우선 |
| — | `metadata_missing`: 삭제 후보 우선 |

---

## 시각적 중복 검토 흐름

```
[👁 시각적 중복 검사]
  → find_visual_duplicates(conn, threshold=6, scope="inbox_managed")
  → VisualDuplicateReviewDialog 표시
    - 이미지 미리보기 비교
    - [이 파일 유지] / [이 파일 삭제] / [그룹에서 제외]
    - [다음 그룹] / [삭제 미리보기로 이동]
  → DeletePreviewDialog 표시 (재확인)
  → execute_delete_preview(confirmed=True)
```

### pHash 알고리즘

- Pillow 기반 구현
- 이미지를 9×8 그레이스케일로 축소
- 수평 gradient 비교 (64비트)
- Hamming distance ≤ 6 → 유사 이미지 그룹화
- 같은 group 내 파일끼리는 비교하지 않음

---

## 최종 삭제

모든 삭제 경로는 공통 `delete_manager`를 사용합니다.

```python
from core.delete_manager import build_delete_preview, execute_delete_preview

preview = build_delete_preview(conn, file_ids=delete_file_ids, reason="exact_duplicate_cleanup")
result  = execute_delete_preview(conn, preview, confirmed=True)
```

삭제 결과는 `delete_batches` / `delete_records` 테이블에 기록됩니다.
자세한 삭제 정책은 [file-deletion.md](file-deletion.md)를 참조하세요.

---

## Workflow Wizard 연결

작업 마법사 **Step 3: 메타데이터 확인** 패널에 중복 검사 섹션이 포함됩니다.

```
중복 검사 (선택 사항)
[🧬 완전 중복 검사]  [👁 시각적 중복 검사]
검사 범위: Inbox / Managed
```

- 기본 scope는 `inbox_managed`로 고정 (Wizard에서는 변경 불가)
- 전체 Archive 검사가 필요한 경우 툴바 버튼 + config에서 `allow_all_archive_scan: true` 설정

이 단계는 선택 사항으로, 건너뛰어도 이후 단계 진행에 영향을 주지 않습니다.

---

## config.json 중복 검사 설정

```json
{
  "duplicates": {
    "default_scope": "inbox_managed",
    "max_exact_files_per_run": 1000,
    "max_visual_files_per_run": 300,
    "visual_hash_batch_size": 50,
    "show_progress_every": 25,
    "allow_all_archive_scan": false
  }
}
```

| 키 | 설명 |
|----|------|
| `default_scope` | 기본 검사 범위 (`inbox_managed` 권장) |
| `max_exact_files_per_run` | 완전 중복 검사 최대 대상 파일 수 |
| `max_visual_files_per_run` | 시각적 중복 검사 최대 대상 파일 수 |
| `allow_all_archive_scan` | `true`로 변경 시 전체 Archive 검사 허용 (경고 후 실행) |
