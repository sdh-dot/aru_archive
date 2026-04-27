# 문제 해결 가이드

---

## 1. Native Host 연결 실패

### 증상
팝업에서 "연결 테스트" 클릭 시 오류 메시지 표시.

### 원인별 해결

#### install_host.bat 미실행
```bat
build\install_host.bat chrome <extension_id>
```
실행 후 브라우저 **완전 종료 → 재시작**.

#### Extension ID 불일치
확장을 재로드하면 ID가 바뀔 수 있습니다.

1. `chrome://extensions` → 해당 확장 ID 확인
2. 새 ID로 재설치:
   ```bat
   build\install_host.bat chrome <new_extension_id>
   ```

#### allowed_origins PLACEHOLDER 문제
`manifest.json` 내 `allowed_origins`에 실제 ID 대신 `EXTENSION_ID_PLACEHOLDER`가 남아 있으면 연결이 거부됩니다.

확인 방법:
```bat
type "%APPDATA%\AruArchive\NativeHost\manifest_chrome.json"
```
`EXTENSION_ID_PLACEHOLDER`가 보이면 `install_host.bat`을 실제 ID로 재실행합니다.

#### Python 경로 문제
`host.bat` 내에서 `python`을 찾지 못하는 경우:

```bat
type "%APPDATA%\AruArchive\NativeHost\host.bat"
```

가상환경을 사용한다면 `python`을 가상환경 경로로 수정합니다.
```bat
C:\Users\..\.venv\Scripts\python.exe -m native_host.host
```

#### stdout 로그 오염
`native_host/host.py` 또는 import된 모듈이 `print()`로 stdout에 출력하면 브라우저가 JSON 파싱에 실패합니다.

Native Host 로그 확인:
```
%APPDATA%\AruArchive\NativeHost\native_host.log
```

`logger.info()` / `logger.warning()`은 stderr + 파일로만 출력됩니다.

---

## 2. Pixiv 저장 실패

### HTTP 403 (Forbidden)
- **원인 A:** Referer 헤더 누락 — `i.pximg.net` 이미지 서버가 거부
  - 수정: `core/pixiv_downloader.py`의 Referer 설정 확인
- **원인 B:** R-18 / 팔로워 전용 작품 — 쿠키(로그인 세션) 없음
  - **현재 v0.3.0에서 쿠키 자동 수집은 미구현입니다.** 공개 작품만 저장 가능합니다.

### HTTP 404 (Not Found)
- 작품이 삭제되었거나 artwork_id가 잘못된 경우

### Pixiv API 오류 (`network_error`, `pixiv_fetch_error`)
- Pixiv 서버 일시 장애 → 잠시 후 재시도
- Pixiv API 구조 변경 → 어댑터 업데이트 필요

### 저장 작업이 stuck
- `save_jobs` 테이블 확인:
  ```sql
  SELECT * FROM save_jobs ORDER BY started_at DESC LIMIT 5;
  ```
- `status='running'`이 장시간 지속되면 lock 확인:
  ```sql
  SELECT * FROM locks WHERE expires_at > datetime('now');
  ```
- 120초 후 lock이 자동 만료됩니다.

---

## 3. 작업 폴더 문제

### 작업 폴더 설정이 안 됨
- 툴바 `[📁 작업 폴더 설정]` 클릭 후 분류 대상 폴더 선택
- 선택 후 `config.json` 내 `inbox_dir`, `classified_dir`, `managed_dir` 확인

### config.json 없음
```bash
cp config.example.json config.json
# data_dir, inbox_dir, classified_dir, managed_dir, db.path 수정
```

### 분류 대상 폴더 없음
`inbox_dir` 경로가 존재하지 않으면 CoreWorker가 자동 생성합니다.  
수동 생성이 필요한 경우:
```bash
mkdir "D:\PixivInbox"
```

### 폴더 권한 문제
Windows에서 네트워크 드라이브 또는 읽기 전용 경로에 `inbox_dir`을 설정하면 쓰기가 실패합니다.  
로컬 드라이브 경로를 사용하세요.

---

## 4. GUI 실행 문제

### PyQt6 설치 오류
```bash
pip install PyQt6>=6.6.0
```

> ❌ **PySide6는 사용 금지입니다.** 이 프로젝트는 PyQt6 전용입니다.

### requirements.txt 재설치
```bash
pip install -r requirements.txt
```

### QT_QPA_PLATFORM 오류 (헤드리스 환경)
```bash
QT_QPA_PLATFORM=offscreen python main.py
```

### 앱이 시작되지 않음
```bash
python main.py 2>&1 | head -50
```
오류 메시지에서 import 실패 모듈 확인 후 설치합니다.

---

## 5. 메타데이터 문제

### 파일이 `json_only` 상태 (XMP 없음)
현재 v0.3.0에서 XMP 기록은 미구현입니다.  
`json_only` 상태는 AruArchive JSON은 기록되었지만 XMP는 없음을 의미합니다.  
분류는 `json_only` 상태에서도 정상 동작합니다.

### `xmp_write_failed`
XMP 기록 시도 중 실패했습니다. AruArchive JSON은 정상입니다.  
분류 대상에 포함됩니다.

### `metadata_write_failed`
AruArchive JSON 임베딩 자체가 실패했습니다.  
파일 권한 또는 포맷 문제를 확인하세요.  
분류 대상에서 **제외**됩니다.

### ExifTool 미설정
현재 v0.3.0에서 ExifTool XMP 일괄 처리는 미구현입니다.  
ExifTool 없이도 기본 기능은 동작합니다.

---

## 6. 테스트 실패

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -v
```

### GUI 관련 테스트 실패
```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q
```
`QT_QPA_PLATFORM=offscreen`이 설정되어야 headless 환경에서 동작합니다.

### PySide6 관련 ImportError
프로젝트에서 PySide6를 사용하면 안 됩니다.
```bash
grep -r "PySide6" --include="*.py" .
```
결과가 있으면 해당 코드를 PyQt6로 수정하세요.

---

## 7. 외부 사전 소스 접속 불가 (External Dictionary Source Unavailable)

Danbooru 또는 Safebooru에 접속할 수 없는 경우에도 Aru Archive의 핵심 기능은 계속 동작합니다.

### 증상
- `[🌐 웹 사전]` → `[🔍 후보 수집]` 클릭 후 오류 메시지 표시
- "후보 수집에 실패했습니다" 메시지 출력

### 가능한 원인
- 네트워크 오류 또는 사이트 접속 차단
- timeout (기본 15초)
- API 응답 형식 변경

### 해결 방법

1. **다른 source 시도**: source 콤보에서 Danbooru ↔ Safebooru 전환
2. **fallback 옵션 활성화**: "Danbooru 실패 시 Safebooru로 재시도" 체크박스 활성화
3. **로컬 태그 팩 사용**: `[🏷 태그 후보]` 뷰에서 기존 tag_candidates 검토
4. **기존 staged 후보 검토**: 이전에 수집한 staged 항목이 있으면 계속 사용 가능
5. **Pixiv observation 기반 후보**: 저장된 tag_observations에서 자동 생성된 후보 확인

> 외부 사전 접속 실패는 로컬 분류 / Undo / tag_aliases / tag_localizations 기능에
> **영향을 주지 않습니다**.

---

## 8. 로그 파일 위치

| 로그 | 경로 |
|------|------|
| Native Host 실행 로그 | `%APPDATA%\AruArchive\NativeHost\native_host.log` |
| Native Host 설치 로그 | `%APPDATA%\AruArchive\NativeHost\install.log` |
| PyQt6 앱 로그 | `stdout / stderr` (터미널에 출력) |
