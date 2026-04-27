# Release Checklist

Aru Archive 릴리즈 전 확인 항목입니다.

---

## 0. 버전 번호 업데이트

- [ ] `core/version.py` — `APP_VERSION`, `EXTENSION_VERSION` 갱신
- [ ] `extension/manifest.json` — `"version"` 갱신
- [ ] `extension/popup/popup.html` — footer 버전 텍스트 갱신
- [ ] `CHANGELOG.md` — `[Unreleased]` → `[x.y.z] — YYYY-MM-DD` 변환

```python
# core/version.py 예시
APP_VERSION       = "0.4.0"
EXTENSION_VERSION = "0.4.0"
```

---

## 1. 코드 품질

- [ ] `QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q` — 전체 통과
- [ ] PySide6 잔존 검사 결과 **0건**
  ```bash
  grep -r "PySide6" --include="*.py" --include="*.js" --include="*.html" --include="*.txt" .
  ```
- [ ] `config.json`이 git에 포함되지 않았는지 확인
  ```bash
  git status config.json
  # → 출력 없어야 정상 (gitignored)
  ```
- [ ] Pixiv 쿠키 / API 토큰이 소스 코드에 없는지 확인
- [ ] 하드코딩된 로컬 경로가 없는지 확인
- [ ] Extension ID 플레이스홀더 (`EXTENSION_ID_PLACEHOLDER`) 확인
  - 소스 `native_host/manifest_chrome.json`에는 그대로 있어야 함
  - 설치 후 `%APPDATA%\AruArchive\NativeHost\manifest_chrome.json`에는 실제 ID가 있어야 함

---

## 2. 버전 정합성 확인

- [ ] `core/version.py`의 `APP_VERSION` == `extension/manifest.json`의 `"version"`
- [ ] `core/version.py`의 `NATIVE_PROTOCOL_VERSION` == `native_host/host.py`의 실제 구현 버전
- [ ] `core/version.py`의 `DB_SCHEMA_VERSION` == `db/schema.sql` 스키마 세대

---

## 3. 문서 확인

- [ ] `README.md` 링크가 유효한지 확인 (docs/ 파일 존재 여부)
- [ ] `CHANGELOG.md` 해당 버전 섹션 완성
- [ ] `docs/extension-setup.md` — 설치 절차 최신 상태
- [ ] `docs/troubleshooting.md` — 알려진 이슈 반영

---

## 4. 브라우저 확장 테스트

- [ ] `extension/` 폴더를 Chrome에서 개발자 모드 로드 성공
- [ ] `extension/` 폴더를 Naver Whale에서 개발자 모드 로드 성공
- [ ] `build\install_host.bat chrome <ext_id>` 실행 — "Chrome 등록 완료" 확인
- [ ] `build\install_host.bat whale <ext_id>` 실행 — "Whale 등록 완료" 확인
- [ ] 브라우저 재시작 후 팝업 → **연결 테스트** → "연결 성공 ✓" 확인
- [ ] Pixiv 공개 작품 페이지에서 **저장** → 완료 확인
- [ ] 우클릭 컨텍스트 메뉴 "Aru Archive에 저장" 동작 확인
- [ ] `build\uninstall_host.bat` 실행 후 연결 실패 확인

---

## 5. 로컬 앱 테스트

- [ ] `python main.py` 실행 — GUI 정상 표시
- [ ] **작업 폴더 설정** → `config.json`에 `inbox_dir`, `classified_dir`, `managed_dir` 저장 확인
- [ ] **Inbox 스캔** → 갤러리에 파일 표시
- [ ] **Pixiv 메타데이터 가져오기** → Status `json_only` 확인
- [ ] **분류 미리보기** → 경로 확정 → **분류 실행** → 파일 복사 확인
- [ ] **작업 로그 / Undo** → Classified 복사본 삭제, 원본 보존 확인
- [ ] **태그 후보** → 승인 / 거부 → `tag_aliases` 반영 확인
- [ ] **저장 작업** (`[💾 저장 작업]`) → 진행 상황 표시 확인

---

## 6. 패키징 (EXE 배포 시)

- [ ] `pyinstaller build/aru_archive.spec --clean` 빌드 성공
- [ ] `dist/AruArchive/AruArchive.exe` 실행 확인
- [ ] 아이콘 (`aru_archive_icon.ico`) 적용 확인
- [ ] `config.example.json` 포함 확인
- [ ] `native_host/` 제외 확인 (Native Host는 별도 등록)
- [ ] `extension/` ZIP 배포 파일 생성

---

## 7. Git / GitHub

- [ ] `git status` — working tree clean
- [ ] `git log --oneline -5` — 커밋 메시지 확인
- [ ] GitHub에서 Release 생성 (tag: `v{APP_VERSION}`)
- [ ] Release Notes에 `CHANGELOG.md` 해당 버전 섹션 붙여넣기
- [ ] Assets 업로드: `AruArchive_vX.Y.Z.zip`, `aru_archive_extension_vX.Y.Z.zip`

---

## 8. 릴리즈 후

- [ ] `CHANGELOG.md`에 `## [Unreleased]` 섹션 새로 추가
- [ ] `core/version.py`에 다음 버전 (개발 중) 표시

---

## 빠른 점검 명령

```bash
# 테스트 전체
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q

# PySide6 검사
grep -r "PySide6" --include="*.py" --include="*.js" --include="*.html" .

# 버전 일치 확인
python -c "from core.version import *; print(APP_VERSION, EXTENSION_VERSION, NATIVE_PROTOCOL_VERSION)"

# config.json 미포함 확인
git check-ignore -v config.json
```
