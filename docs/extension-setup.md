# Browser Extension 설치 가이드

Chrome 및 Naver Whale에서 Aru Archive 확장을 설치하고 Native Host와 연결하는 절차입니다.

---

## 사전 요구사항

- Python 3.12+ (`python` 명령이 PATH에 있어야 함)
- `pip install -r requirements.txt` 완료
- Chrome 또는 Naver Whale 브라우저

---

## 1단계: 브라우저에 확장 로드

### Chrome

1. 주소창에 `chrome://extensions` 입력
2. 오른쪽 상단 **개발자 모드** 토글 ON
3. **압축 해제된 확장 프로그램 로드** 클릭
4. 프로젝트 내 `extension/` 폴더 선택
5. 확장이 목록에 나타나면 **ID** 복사 (예: `abcdefghijklmnopabcdefghijklmnop`)

### Naver Whale

1. 주소창에 `whale://extensions` 입력
2. **개발자 모드** 토글 ON
3. **압축 해제된 확장 프로그램 로드** 클릭
4. `extension/` 폴더 선택 후 ID 복사

---

## 2단계: Native Host 설치

프로젝트 루트에서 아래 명령 중 하나를 실행합니다.

```bat
:: Chrome 전용
build\install_host.bat chrome <extension_id>

:: Naver Whale 전용
build\install_host.bat whale <extension_id>

:: Chrome + Whale 동시
build\install_host.bat both <extension_id>
```

**예시:**

```bat
build\install_host.bat chrome abcdefghijklmnopabcdefghijklmnop
```

스크립트가 수행하는 작업:
1. `%APPDATA%\AruArchive\NativeHost\host.bat` 생성
2. `build/gen_manifest.py`로 `manifest_chrome.json` / `manifest_whale.json` 생성 (실제 extension ID 포함)
3. Windows 레지스트리 `HKCU\Software\...\NativeMessagingHosts\net.aru_archive.host` 등록
4. 설치 로그: `%APPDATA%\AruArchive\NativeHost\install.log`

> **관리자 권한 불필요** — `HKCU` (현재 사용자) 키에만 등록합니다.

---

## 3단계: 브라우저 재시작

Chrome / Whale을 **완전히 종료**한 뒤 다시 열어야 Native Host 등록이 적용됩니다.

---

## 4단계: 연결 테스트

1. Pixiv 작품 페이지(`https://www.pixiv.net/artworks/...`) 접속
2. 확장 아이콘 클릭 → 팝업 열기
3. **연결 테스트** 버튼 클릭
4. "연결 성공 ✓" 메시지 확인

연결 실패 시 → [Troubleshooting](troubleshooting.md) 참고

---

## 5단계: 저장 테스트

1. Pixiv 공개 작품 페이지에서 팝업 → **저장** 클릭
2. 팝업 상태가 `저장 중… N/M 페이지` 로 업데이트 확인
3. `저장 완료 (N페이지)` 표시 확인
4. PyQt6 앱 → `[💾 저장 작업]` → 해당 job 상태 확인

---

## Extension ID 주의사항

### ID가 바뀌는 경우

개발자 모드 확장은 다음 상황에서 ID가 변경될 수 있습니다.

- 확장을 삭제 후 재로드
- `extension/` 경로가 변경된 경우
- 다른 PC에서 로드한 경우

ID가 바뀌면 Native Host의 `allowed_origins`가 구버전 ID를 참조하여 연결이 거부됩니다.

**해결:** `install_host.bat`을 새 ID로 다시 실행

```bat
build\install_host.bat chrome <new_extension_id>
```

### ID를 미리 확인하는 방법

확장이 로드된 상태에서:
- Chrome: `chrome://extensions` → 해당 확장 카드의 "ID" 항목
- Whale: `whale://extensions` → 해당 확장 카드의 "ID" 항목

---

## 제거 (Uninstall)

```bat
build\uninstall_host.bat
```

Chrome과 Whale 레지스트리 키를 모두 삭제하고 `%APPDATA%\AruArchive\NativeHost` 디렉터리를 제거합니다.

---

## 파일 경로 요약

| 파일 | 경로 |
|------|------|
| 확장 소스 | `extension/` |
| 설치 스크립트 | `build/install_host.bat` |
| Manifest 생성기 | `build/gen_manifest.py` |
| Host 실행 파일 | `%APPDATA%\AruArchive\NativeHost\host.bat` |
| Chrome Manifest | `%APPDATA%\AruArchive\NativeHost\manifest_chrome.json` |
| Whale Manifest | `%APPDATA%\AruArchive\NativeHost\manifest_whale.json` |
| 설치 로그 | `%APPDATA%\AruArchive\NativeHost\install.log` |
| 실행 로그 | `%APPDATA%\AruArchive\NativeHost\native_host.log` |
