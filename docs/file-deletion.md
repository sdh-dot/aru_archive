# Aru Archive — 파일 삭제 정책

## 원칙

Aru Archive의 삭제는 **휴지통 이동이 아닌 영구 삭제**입니다.
한 번 삭제된 파일은 복구할 수 없습니다.

---

## 삭제 절차

모든 삭제는 다음 7단계를 거칩니다.

1. **대상 수집** — group_ids 또는 file_ids 지정
2. **DB/메타데이터/파일 상태 점검** — `build_delete_preview()` 호출
3. **미리보기 생성** — 파일 목록, 위험도, 경고, 빈 그룹 수 계산
4. **사용자 강한 확인** — `DeletePreviewDialog` 표시
5. **파일 영구 삭제** — `execute_delete_preview(confirmed=True)` 호출
6. **DB 상태 갱신** — `artwork_files.file_status = 'deleted'`
7. **감사 기록** — `delete_batches` / `delete_records` 테이블에 기록

---

## 삭제 전 점검 항목

`build_delete_preview()`가 수행하는 점검:

| 항목 | 설명 |
|------|------|
| 파일 존재 여부 | 디스크에 실제 파일이 있는지 확인 |
| DB 경로 일치 | `artwork_files.file_path`와 일치하는지 확인 |
| file_role | original / managed / sidecar / classified_copy |
| metadata_sync_status | full / json_only / pending 등 |
| AruArchive JSON | `.json` 사이드카 존재 여부 |
| 삭제 후 잔여 파일 | group에 다른 present 파일이 남는지 확인 |
| group empty 여부 | 삭제 후 group이 빈 상태가 되는지 확인 |

---

## 위험도 기준

| 위험도 | 조건 |
|--------|------|
| **High** | original 파일 포함 / 삭제 후 group이 empty가 됨 |
| **Medium** | managed 또는 sidecar 포함 |
| **Low** | classified_copy만 삭제 |

---

## 강한 확인 (High Risk)

`risk = 'high'`인 경우 DeletePreviewDialog에서 **DELETE**를 직접 입력해야 삭제가 허용됩니다.

```
선택한 항목에는 original 파일이 포함되어 있습니다.
이 작업은 파일을 영구 삭제하며 복구할 수 없습니다.

계속하려면 DELETE를 입력하세요.
```

---

## DB 기록

### delete_batches

삭제 작업 단위(batch) 기록.

| 컬럼 | 설명 |
|------|------|
| delete_batch_id | UUID |
| operation_type | manual_delete / exact_duplicate_cleanup / visual_duplicate_cleanup |
| total_files | 대상 파일 수 |
| deleted_files | 실제 삭제된 수 |
| failed_files | 실패한 수 |
| skipped_files | 건너뛴 수 |
| created_at | 실행 시각 |
| summary_json | 요약 JSON |

### delete_records

파일 단위 기록.

| 컬럼 | 설명 |
|------|------|
| delete_id | UUID |
| delete_batch_id | FK → delete_batches |
| file_id | FK → artwork_files |
| original_path | 삭제된 파일 경로 |
| file_role | original / managed / sidecar / classified_copy |
| delete_reason | 삭제 사유 |
| result_status | deleted / failed / skipped |
| error_message | 실패 시 오류 메시지 |

---

## 주의사항

- `execute_delete_preview(confirmed=False)`는 아무 작업도 수행하지 않습니다.
- 파일 삭제 후 `.json` 사이드카도 함께 삭제를 시도합니다.
- `artwork_files.file_status`는 `'deleted'`로 갱신되지만, row 자체는 제거하지 않습니다.
- 삭제 후 썸네일 / 갤러리 / 카운터는 호출 측(MainWindow)이 갱신해야 합니다.
