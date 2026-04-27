# Native Messaging Protocol v2

브라우저 확장(Chrome / Naver Whale)과 Native Host(`native_host/host.py`) 사이의 통신 규격입니다.

**Protocol Version:** 2  
**Transport:** stdio (4-byte little-endian length prefix + UTF-8 JSON)

## 요청 형식

```json
{
  "action": "save_pixiv_artwork",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "artwork_id": "103192368",
    "page_url": "https://www.pixiv.net/artworks/103192368",
    "preload_data": {}
  }
}
```

## 성공 응답

```json
{
  "success": true,
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "job_id": "uuid",
    "saved": 3,
    "total": 3,
    "failed": 0
  }
}
```

## 오류 응답

```json
{
  "success": false,
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "error": "lock_acquisition_error"
}
```

## 액션 목록

### `ping`

연결 확인용입니다.

응답:

```json
{ "status": "ok" }
```

### `get_config_summary`

현재 설정의 핵심 경로를 요약해서 반환합니다.

응답 예:

```json
{
  "data_dir": "C:/Users/<user>/AruArchive",
  "inbox_dir": "D:/PixivInbox",
  "db_path": "C:/Users/<user>/AruArchive/.runtime/aru.db"
}
```

### `save_pixiv_artwork`

Pixiv 작품을 `inbox_dir`에 저장하고 DB에 기록합니다.

요청 payload:

```json
{
  "artwork_id": "103192368",
  "page_url": "https://www.pixiv.net/artworks/103192368",
  "preload_data": {}
}
```

응답 예:

```json
{
  "job_id": "uuid",
  "saved": 3,
  "total": 3,
  "failed": 0
}
```

오류 예:

- `lock_acquisition_error`
- `pixiv_fetch_error`
- `artwork_restricted`

### `open_main_app`

메인 PyQt6 앱을 실행합니다.

응답:

```json
{ "launched": true }
```

### `get_job_status`

저장 작업 상태와 페이지별 결과를 조회합니다.

요청 payload:

```json
{ "job_id": "uuid" }
```

응답 예:

```json
{
  "status": "completed",
  "progress": {
    "total_pages": 3,
    "saved_pages": 3,
    "failed_pages": 0
  },
  "error_message": null,
  "pages": [
    { "page_index": 0, "status": "saved", "file_path": "D:/PixivInbox/art_p0.jpg" },
    { "page_index": 1, "status": "saved", "file_path": "D:/PixivInbox/art_p1.jpg" },
    { "page_index": 2, "status": "failed", "error_message": "HTTP 403" }
  ]
}
```

`status` 값:

- `running`
- `completed`
- `partial`
- `failed`

## stdout / stderr 규칙

- `stdout`: Native Messaging 응답 JSON 전용
- `stderr`: 디버그 로그
- 로그 파일: `%APPDATA%\AruArchive\NativeHost\native_host.log`

`stdout`에 일반 텍스트가 섞이면 브라우저 쪽 JSON 파싱이 깨질 수 있으므로 금지합니다.

## 연결 정보

- Chrome registry: `HKCU\Software\Google\Chrome\NativeMessagingHosts\net.aru_archive.host`
- Whale registry: `HKCU\Software\Naver\Whale\NativeMessagingHosts\net.aru_archive.host`
- manifest name: `net.aru_archive.host`

자세한 설치 방법은 [docs/extension-setup.md](docs/extension-setup.md) 를 참고하세요.
