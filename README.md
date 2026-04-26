# Aru Archive

개인 아트워크 아카이브 관리 도구.
Pixiv 등 소스에서 수집한 파일을 메타데이터 기반으로 분류·관리합니다.

**플랫폼:** Windows 11 · Python 3.12+ · PyQt6 · SQLite

---

## 설치

```bash
pip install -r requirements.txt
```

---

## 실행

```bash
# GUI 모드 (기본)
python main.py

# 설정 파일 지정
python main.py --config path/to/config.json

# 헤드리스 서버 모드
python main.py --headless
```

---

## 테스트

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q
```

---

## 수동 테스트 절차

### Pixiv 메타데이터 보강 수동 테스트

1. `python main.py` 실행
2. 상단 툴바 [📁 Archive Root 선택] 클릭 → 아카이브 루트 폴더 선택
3. [🔍 Inbox 스캔] 클릭 → Pixiv 파일명 형식(`{artwork_id}_p{n}.ext`)의 파일 스캔
4. 갤러리에서 `⏳ Pending` 또는 `❓ NoMeta` 상태 파일 선택
5. 우측 상세 패널 → [🌐 Pixiv 메타데이터 가져오기] 클릭
6. 로그 패널에서 fetch 진행 상황 확인
7. 완료 후 상세 패널 Status가 `🟡 JSON Only`로 변경되었는지 확인
8. 제목·작가·태그가 상세 패널에 표시되는지 확인

---

### 분류 엔진 수동 테스트

1. `python main.py` 실행
2. 상단 툴바 [📁 Archive Root 선택] 클릭 → 아카이브 루트 폴더 선택
3. [🔍 Inbox 스캔] 클릭
4. Pixiv 메타데이터 가져오기로 파일 Status를 `json_only` 상태로 만들기
5. 갤러리에서 `🟡 JSON Only` 상태 파일 선택
6. 상단 툴바 [📋 분류 미리보기] 클릭
7. 다이얼로그에서 복사 예정 경로 확인:
   - `Classified/ByAuthor/{artist_name}/filename`
   - `Classified/BySeries/{series_tag}/filename` (시리즈 태그가 있는 경우)
   - `Classified/ByCharacter/{char_tag}/filename` (캐릭터 태그가 있는 경우)
8. [실행] 클릭
9. 로그 패널에서 복사 결과 확인:
   ```
   [INFO] Copied: ...ByAuthor/작가명/file.jpg
   [INFO] Classification completed: N copied, 0 skipped
   ```
10. 파일 시스템에서 `Classified/` 폴더에 파일이 복사되었는지 확인
11. 갤러리 카드 상태가 `classified`로 변경되었는지 확인
12. 좌측 카테고리 카운터가 갱신되었는지 확인

#### DB 확인 (선택)

SQLite 브라우저 또는 sqlite3 CLI로 확인:

```sql
-- 분류 기록 확인
SELECT * FROM copy_records ORDER BY copied_at DESC LIMIT 10;

-- classified_copy 파일 확인
SELECT file_path, file_role, created_at
FROM   artwork_files
WHERE  file_role = 'classified_copy'
ORDER  BY created_at DESC LIMIT 10;

-- undo 항목 확인
SELECT entry_id, operation_type, undo_status, performed_at
FROM   undo_entries
ORDER  BY performed_at DESC LIMIT 5;
```

---

## config.json 예시

```json
{
  "data_dir": "F:/AruArchive",
  "inbox_dir": "F:/AruArchive/Inbox",
  "classified_dir": "F:/AruArchive/Classified",
  "undo_retention_days": 7,
  "db": {
    "path": "F:/AruArchive/.runtime/aru.db"
  },
  "classification": {
    "enable_by_author":    true,
    "enable_by_series":    true,
    "enable_by_character": true,
    "enable_by_tag":       false,
    "on_conflict":         "rename"
  }
}
```

---

## 분류 정책

| 조건 | 동작 |
|------|------|
| `full` / `json_only` / `xmp_write_failed` | 분류 가능 |
| `metadata_missing` / `pending` / 실패 계열 | 분류 제외 |
| BMP original | 직접 분류 금지 (PNG managed 생성 후 재시도) |
| managed 파일 존재 | managed 우선 복사 |
| `on_conflict=rename` | `filename_1.ext`, `filename_2.ext` … |
| `on_conflict=skip` | 기존 파일 유지, 복사 생략 |
