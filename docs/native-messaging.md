# Native Messaging Protocol v2

브라우저 확장(Chrome / Naver Whale)과 Native Host(`native_host/host.py`) 사이의 통신 규격입니다.

**Protocol Version:** 2  
**Transport:** stdio (4-byte little-endian length prefix + UTF-8 JSON)

---

## 1. 메시지 형식

### 요청 (Extension → Native Host)

```json
{
  "action":     "save_pixiv_artwork",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "artwork_id":   "103192368",
    "page_url":     "https://www.pixiv.net/artworks/103192368",
    "preload_data": {}
  }
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `action` | string | 수행할 작업 이름 |
| `request_id` | string | 요청 추적용 고유 ID (UUID v4 권장) |
| `payload` | object | 액션별 파라미터 (없으면 `{}`) |

### 성공 응답 (Native Host → Extension)

```json
{
  "success":    true,
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "job_id": "uuid",
    "saved":  3,
    "total":  3,
    "failed": 0
  }
}
```

### 오류 응답

```json
{
  "success":    false,
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "error":      "lock_acquisition_error"
}
```

---

## 2. 액션 목록

### `ping`

연결 확인. payload 없음.

**응답 data:**
```json
{ "status": "ok" }
```

---

### `get_config_summary`

현재 로드된 `config.json` 주요 값을 반환. payload 없음.

**응답 data:**
```json
{
  "data_dir":  "D:/AruArchive",
  "inbox_dir": "D:/AruArchive/Inbox",
  "db_path":   "D:/AruArchive/.runtime/aru.db"
}
```

---

### `save_pixiv_artwork`

Pixiv 작품을 Inbox에 저장하고 DB에 기록합니다.

**요청 payload:**
```json
{
  "artwork_id":   "103192368",
  "page_url":     "https://www.pixiv.net/artworks/103192368",
  "preload_data": {}
}
```

| 필드 | 필수 | 설명 |
|------|------|------|
| `artwork_id` | ✅ | Pixiv 작품 ID |
| `page_url` | 선택 | 현재 페이지 URL |
| `preload_data` | 선택 | 페이지 preload JSON (API 실패 시 fallback) |

**응답 data:**
```json
{
  "job_id": "uuid",
  "saved":  3,
  "total":  3,
  "failed": 0
}
```

**오류 코드:**
| error | 의미 |
|-------|------|
| `lock_acquisition_error` | 동일 artwork_id 저장 진행 중 |
| `pixiv_fetch_error` | Pixiv API 접근 실패 |
| `artwork_restricted` | 로그인 또는 팔로워 권한 필요 |

---

### `open_main_app`

PyQt6 Main App을 새 콘솔 창으로 실행합니다. payload 없음.

**응답 data:**
```json
{ "launched": true }
```

---

### `get_job_status`

저장 작업 상태와 페이지별 진행 결과를 조회합니다.

**요청 payload:**
```json
{ "job_id": "uuid" }
```

**응답 data:**
```json
{
  "status": "completed",
  "progress": {
    "total_pages":  3,
    "saved_pages":  3,
    "failed_pages": 0
  },
  "error_message": null,
  "pages": [
    { "page_index": 0, "status": "saved",  "file_path": "D:/AruArchive/Inbox/art_p0.jpg" },
    { "page_index": 1, "status": "saved",  "file_path": "D:/AruArchive/Inbox/art_p1.jpg" },
    { "page_index": 2, "status": "failed", "error_message": "HTTP 403" }
  ]
}
```

`status` 값: `running` | `completed` | `partial` | `failed`

**오류 코드:**
| error | 의미 |
|-------|------|
| `missing job_id` | payload에 job_id 누락 |
| `job_not_found` | 해당 job_id 없음 |

---

## 3. 오류 처리 규칙

| 상황 | 동작 |
|------|------|
| JSON 파싱 실패 | `{"success": false, "request_id": "", "error": "protocol_error: malformed JSON"}` 반환 후 루프 계속 |
| 알 수 없는 action | `{"success": false, "error": "unknown_action: <action>"}` |
| 예외 발생 | `{"success": false, "error": "<exception message>"}` |
| EOF (브라우저 종료) | 루프 종료 |

---

## 4. stdout / stderr 정책

| 출력 대상 | 내용 |
|-----------|------|
| **stdout** | Native Messaging 응답 JSON **전용** — 다른 출력 절대 금지 |
| **stderr** | 디버그 로그 (INFO 레벨 이상) |
| **파일** | `%APPDATA%\AruArchive\NativeHost\native_host.log` (DEBUG 레벨) |

> stdout에 일반 텍스트나 `print()`가 섞이면 브라우저가 JSON 파싱에 실패하고 연결이 끊깁니다.

---

## 5. request_id 규칙

- Extension → Native Host: 단조 증가 카운터 (`String(++_reqCounter)`)
- Native Host → Extension: 요청의 `request_id`를 그대로 반환
- 브라우저 측은 `_pending Map<request_id, {resolve, reject}>`으로 콜백을 관리합니다

---

## 6. 연결 방식

| 항목 | 값 |
|------|-----|
| 등록 위치 (Chrome) | `HKCU\Software\Google\Chrome\NativeMessagingHosts\net.aru_archive.host` |
| 등록 위치 (Whale) | `HKCU\Software\Naver\Whale\NativeMessagingHosts\net.aru_archive.host` |
| manifest `name` | `net.aru_archive.host` |
| 실행 방식 | `host.bat` → `python -m native_host.host` |

설치: [`docs/extension-setup.md`](extension-setup.md) 참고
