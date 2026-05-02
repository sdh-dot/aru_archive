# Aru Archive 임시 배포판 안내

> 이 문서는 공식 installer / 스토어 배포 전, 테스트 및 초기 사용자 배포를 위한
> ZIP 패키지 사용자 가이드입니다.
> 빌드 절차 자체는 [Windows Build Packaging Guide](windows_build_guide.md)를 참고하세요.

작성일: 2026-05-02
대상 사용자: 임시 배포판을 받은 일반 사용자 + 배포자

---

## 1. 배포판 성격

> 이 임시 배포판은 테스트 및 초기 사용자 배포를 위한 ZIP 패키지입니다.
> Windows 설치 프로그램, 코드 서명, 자동 업데이트는 아직 제공되지 않습니다.

반드시 알아두실 점:

- 이 배포판은 **공식 installer 또는 Store 배포 전의 임시 ZIP 배포판**입니다.
- **자동 업데이트가 제공되지 않습니다.** 새 버전이 나오면 사용자가 새 ZIP을 내려받아 교체해야 합니다.
- 사용자 DB와 원본 이미지 파일은 **앱 실행 파일과 별도 폴더**에서 관리됩니다.
- 배포판 교체 전에는 **기존 작업 폴더와 DB 백업을 권장**합니다.
- 정식 Chrome Web Store / Naver Whale Store 배포 및 Inno Setup 인스톨러는 **후속 작업** 입니다.

---

## 2. 산출물 구성

배포자가 일반적으로 함께 전달하는 파일 (예시):

| 파일 | 설명 | 필수 여부 |
|---|---|---|
| `AruArchive-v0.6.3-win-x64.zip` | 실행 파일 + 필요한 리소스 (ExifTool 포함) | **필수** |
| `AruArchive-v0.6.3-win-x64.sha256` | 위 ZIP의 SHA256 체크섬 | **필수** |
| `aru-source-captioner-v0.1.0.zip` | 브라우저 확장 (Ruliweb 출처 캡션) | 선택 |
| `README_FIRST.txt` | 짧은 설치 안내 또는 본 문서 링크 | 선택 |

> 실제 ZIP / SHA256 / 확장 ZIP 파일은 git 에 포함하지 않습니다 — `.gitignore` 의 `release/`, `dist/`, `browser-extension/**/*.zip` 으로 차단됩니다.

---

## 3. SHA256 체크섬 확인법

### Windows PowerShell

```powershell
Get-FileHash .\AruArchive-v0.6.3-win-x64.zip -Algorithm SHA256
```

출력 예:

```
Algorithm   Hash                                                              Path
---------   ----                                                              ----
SHA256      A1B2C3D4...EF                                                     C:\...\AruArchive-v0.6.3-win-x64.zip
```

### `.sha256` 파일 표준 형식

본 프로젝트는 **GNU coreutils 호환 형식**을 표준으로 사용합니다 (`sha256sum -c` 와 호환):

```
a1b2c3d4e5f6...ef  AruArchive-v0.6.3-win-x64.zip
```

- 64자 hex 해시
- 공백 두 칸
- 파일명

### 비교 절차

1. `Get-FileHash` 출력의 `Hash` 값을 복사한다.
2. `.sha256` 파일을 텍스트 편집기로 열어 첫 64자 해시를 비교한다.
3. **일치**하면 정상 배포된 파일이다.
4. **불일치**하면 파일이 손상되었거나 다른 파일일 수 있으므로 **실행하지 말고** 배포자에게 문의한다.

> 출처가 불분명한 ZIP 파일이나 체크섬이 일치하지 않는 파일은 실행하지 마세요.

---

## 4. 간단 설치법 (Windows ZIP)

### 절차

1. ZIP 파일과 `.sha256` 파일을 **같은 폴더**에 다운로드한다.
2. SHA256 을 위 §3 절차로 확인한다.
3. 원하는 폴더에 압축 해제한다. 예:
   ```
   C:\Users\<사용자>\Apps\AruArchive\
   ```
4. `AruArchive.exe` 를 실행한다.
5. 첫 실행 시 작업 폴더 (Inbox / Classified / Managed) 를 설정한다.
6. Windows Defender 또는 SmartScreen 경고가 뜨면 §6 안내를 참고한다.

### 권장 설치 경로

```
C:\Users\<사용자>\Apps\AruArchive\
```

- 사용자 폴더 아래라 권한 문제 없음
- 한 번에 폴더 통째로 백업/복원 가능

### 비권장 위치

| 위치 | 이유 |
|---|---|
| `C:\Program Files\AruArchive\` | 관리자 권한 필요 — 첫 실행 시 권장하지 않음 |
| OneDrive / iCloud / Dropbox 동기화 폴더 안 | SQLite WAL 파일 lock 충돌이 발생할 수 있음 |
| 한글 또는 특수문자가 포함된 깊은 경로 | 지원 대상이지만, 문제 발생 시 짧은 영문 경로 (`C:\Apps\AruArchive\`) 에서 재현을 권장 |

---

## 5. 업데이트 방법

> 임시 배포판에는 **자동 업데이트가 없습니다**. 사용자가 직접 새 ZIP 으로 교체해야 합니다.

### 권장 절차

1. 기존 앱을 **종료** 한다 (작업 마법사 / 모든 dialog 닫기).
2. 기존 앱 폴더를 **백업** 또는 이름 변경한다:
   ```
   AruArchive\        →  AruArchive_old\
   ```
3. 새 ZIP 을 동일 위치에 압축 해제한다:
   ```
   AruArchive\
   ```
4. **사용자 데이터 폴더 (Inbox / Classified / Managed / aru_archive.db) 는 그대로 유지** 한다 — 기본 위치는 사용자 홈 (`%USERPROFILE%\AruArchive\` 등) 이며, 앱 배포 폴더와 분리되어 있어 영향이 없다.
5. 새 `AruArchive.exe` 를 실행하고 첫 기동을 확인한다.
6. 문제가 있으면 새 폴더를 지우고 `AruArchive_old\` 로 되돌린다.

### 중요

- 사용자 DB / 작업 폴더가 **앱 배포 폴더 안에** 들어 있는 경우에는 백업이 필수다 (별도 위치 권장).
- ZIP 교체는 **원본 이미지 파일을 삭제하지 않는다.**
- 그래도 새 버전 첫 기동 전에는 DB 백업 (`aru_archive.db`) 을 권장한다.

---

## 6. Windows SmartScreen 경고 안내

### 왜 경고가 뜨는가

- 임시 배포판은 아직 **코드 서명 인증서가 없을 수 있습니다**.
- 이 경우 Windows SmartScreen 또는 Defender 가 경고를 표시할 수 있습니다.
- 이는 반드시 악성이라는 뜻이 아니며, **서명 / 평판이 부족한 새 앱** 에서 흔히 발생합니다.

### 사용자 권장 절차

1. 경고 창에서 **"추가 정보"** 를 클릭한다.
2. **게시자 / 앱 이름** 을 확인한다.
3. **배포자가 안내한 SHA256 과 받은 파일이 일치하는지** 확인한다 (§3 참고).
4. **신뢰할 수 있는 배포 경로** 에서 받은 파일이며 체크섬이 일치할 때만 **"실행"** 을 선택한다.

### 하지 마세요

- SmartScreen 을 무조건 무시하지 마세요.
- Windows Defender 실시간 보호를 끄지 마세요.
- 다른 보안 기능을 끄지 마세요.

> 출처 / 체크섬 / 배포 채널 중 하나라도 의심스러우면 실행하지 말고 배포자에게 문의하세요.

---

## 7. 브라우저 확장 프로그램 임시 설치법

### 대상

- **aru-source-captioner** (Ruliweb 출처 캡션 도우미)
- 우선 지원 브라우저: **Google Chrome**, **Naver Whale**

### 공통 주의

- 공식 스토어 (Chrome Web Store / Whale Store) 심사 전 **임시 설치 방식**입니다.
- **자동 업데이트가 없습니다** — 새 버전이 나오면 다시 설치해야 합니다.
- 확장 프로그램은 **지정된 사이트** 에서 출처 문구 삽입을 돕는 용도입니다 (§8 참고).
- 정식 스토어 배포 후에는 스토어 설치를 권장합니다 — 임시 설치판은 브라우저 정책 변경에 따라 동작이 달라질 수 있습니다.

### Chrome 임시 설치

1. ZIP 으로 받았다면 먼저 **압축을 해제** 한다 (Chrome 은 ZIP 직접 로드를 지원하지 않음 — unpacked folder 필요).
2. 주소창에 `chrome://extensions` 를 입력해 접속한다.
3. 우측 상단 **"개발자 모드"** 토글을 켠다.
4. **"압축해제된 확장 프로그램을 로드"** 버튼을 클릭한다.
5. 압축 해제한 `aru-source-captioner` 폴더를 선택한다 (manifest.json 이 들어 있는 폴더).
6. 확장 아이콘이 표시되는지 확인한다.
7. 대상 페이지 (Ruliweb 게시판) 에서 동작을 확인한다.

### Naver Whale 임시 설치

1. ZIP 압축을 해제한다.
2. 주소창에 `whale://extensions` 를 입력해 접속한다.
3. **개발자 모드** 를 활성화한다.
4. **압축해제된 확장 프로그램 로드** 를 클릭한다.
5. `aru-source-captioner` 폴더를 선택한다.
6. 대상 페이지에서 동작을 확인한다.

---

## 8. 확장 프로그램 권한 안내

`browser-extension/aru-source-captioner/manifest.json` 기준 (manifest version 3):

| 항목 | 값 | 의미 |
|---|---|---|
| **동작 사이트 범위** | `https://bbs.ruliweb.com/community/board/300143/*` <br>`https://bbs.ruliweb.com/community/board/*/read/*` | Ruliweb 특정 게시판 / read 페이지에서만 작동 |
| **host_permissions** | 위와 동일 | 다른 사이트의 페이지 / 데이터에 접근하지 않음 |
| **permissions.storage** | `storage` | 사용자 옵션 (출처 prefix 등) 을 브라우저 로컬에 저장하기 위해 사용 |
| **nativeMessaging** | **사용하지 않음** | 외부 네이티브 프로그램과 통신하지 않음 |
| **외부 서버 전송** | **없음** | 사용자가 클릭한 시점에 페이지 안에서만 동작. 외부 서버로 데이터를 보내지 않음 |
| **댓글 / 글 자동 등록** | **없음** | 입력란에 텍스트만 삽입. submit 은 사용자가 직접 누름 |
| **이미지 자동 업로드** | **없음** | 기존 이미지 첨부 동작을 가로채지 않음 |

### Ruliweb 출처 캡션 동작 요약

- read 페이지의 댓글 영역에 **"출처 추가"** 버튼이 표시됩니다.
- 클릭 시 댓글 textarea 에 다음과 같은 형식으로 출처 문구가 삽입됩니다:
  ```
  출처: <첨부 이미지 metadata 의 artwork_url 또는 현재 페이지 URL>
  ```
- 사용자는 내용을 확인한 뒤 직접 등록 버튼을 누릅니다.
- 댓글 자동 등록은 하지 않습니다.

---

## 9. 문제 해결

| 증상 | 확인 사항 |
|---|---|
| 앱이 실행되지 않음 | ZIP 이 끝까지 압축 해제되었는지 / SHA256 일치 / 백신 격리 여부 확인 |
| 이미지 / 리소스가 안 보임 | 압축 해제 경로 / release 폴더 구조가 그대로 유지되었는지 확인 (`_internal/` 폴더와 함께 배치되어야 함) |
| Loading 화면 좌측 이미지가 비어 있음 | 빌드에 `assets/loading/` 가 포함되었는지 — 배포자에게 문의 |
| ExifTool 관련 경고 / 메타데이터 입력 시 cmd 창 깜빡임 | bundled ExifTool 포함 여부 / 빌드된 windowed mode 여부 — 배포자에게 문의. 메타데이터가 `json_only` 로만 저장될 수 있음 |
| Windows SmartScreen 경고 | §6 절차로 체크섬과 배포 출처를 확인한 뒤 결정 |
| 확장 프로그램 메뉴 / 아이콘이 안 보임 | 개발자 모드가 켜졌는지 / **manifest.json 이 있는 폴더** 를 선택했는지 (상위 폴더가 아닌) 확인 |
| 새 버전이 나왔는데 자동 업데이트 안 됨 | **임시 배포판은 자동 업데이트 없음.** 새 ZIP 을 배포 채널에서 직접 받아 §5 절차로 교체 |

---

## 10. 배포자 체크리스트

배포자가 release ZIP 을 게시하기 전에 확인할 항목입니다.

### 빌드 산출물

- [ ] `scripts/build_windows.ps1 -Version <X.Y.Z>` 로 ZIP 생성
- [ ] 동일 디렉터리에 `.sha256` 파일 생성 확인
- [ ] ZIP 을 깨끗한 임시 폴더에 압축 해제 테스트
- [ ] `release/`, `dist/`, `*.zip`, `*.sha256` 가 git 에 포함되지 않았는지 (`.gitignore` 차단) 재확인

### 빈 Windows 환경 smoke test

- [ ] 새 사용자 폴더에 압축 해제 후 `AruArchive.exe` 실행
- [ ] 첫 실행 DB 자동 생성 확인 (`aru_archive.db`)
- [ ] `build/check_exiftool_bundle.py` 와 동일한 진단 — bundled ExifTool 인식 확인
- [ ] Windows Explorer 에서 메타데이터 입력 후 "제목 / 태그 / 만든 이" 컬럼 표시 확인
- [ ] Loading overlay 좌측 일러스트 정상 표시 확인 (`assets/loading/`)
- [ ] 메타데이터 입력 작업 중 cmd 창이 깜빡이지 않는지 확인 (CREATE_NO_WINDOW 적용)
- [ ] DB reset safety guard (`전체 DB 초기화` 메뉴 → 2단계 typed confirm) 동작 확인
- [ ] 작업 마법사 9 단계가 모두 열리는지 확인

### 브라우저 확장

- [ ] `aru-source-captioner` 폴더를 ZIP 으로 만들어 별도 배포
- [ ] Chrome `chrome://extensions` 에서 unpacked load 동작 확인
- [ ] Naver Whale `whale://extensions` 에서 unpacked load 동작 확인
- [ ] Ruliweb 대상 게시판 read 페이지 댓글 / 대댓글 영역에서 "출처 추가" 버튼 동작 확인

### 배포 페이지 게시

- [ ] 본 문서 또는 동등한 사용자 안내 링크 게시
- [ ] SHA256 값을 ZIP 다운로드 링크와 같은 페이지에 명시
- [ ] Release notes (CHANGELOG 발췌 등) 첨부
- [ ] "임시 배포판 — 자동 업데이트 없음" 문구 명시
- [ ] 코드 서명 미적용 시 §6 SmartScreen 안내 링크 함께 게시

---

## 관련 문서

- 빌드 절차 / 산출물 정의: [windows_build_guide.md](windows_build_guide.md)
- 설계 / 코드 변경 이력: [../../CHANGELOG.md](../../CHANGELOG.md)
