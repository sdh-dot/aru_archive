# 패키징 및 릴리즈 구성

Aru Archive를 배포하기 위한 패키징 절차와 릴리즈 구성입니다.

---

## Icon Assets

아이콘 리소스는 아래 원본 이미지에서 생성됩니다.

- 원본: `docs/icon_1.png`

생성 산출물:

| 경로 | 용도 |
|------|------|
| `assets/icon/aru_archive_icon_master.png` | 공식 master asset (RGBA, 투명 배경) |
| `assets/icon/aru_archive_icon.ico` | Windows 앱 / PyInstaller 아이콘 |
| `assets/icon/aru_archive_icon_{size}.png` | 16·32·48·64·128·256·512·1024px PNG 세트 |
| `extension/icons/icon{size}.png` | 브라우저 확장 전용 아이콘 (16·32·48·128) |
| `docs/icon.png` | README 대표 이미지 (256px) |

아이콘 재생성:

```bash
python build/generate_icons.py
```

---

## 1. 현재 배포 방법

### Python 직접 실행 (개발자 / 개인 사용)

```bash
pip install -r requirements.txt
python main.py
```

요구사항: Python 3.12+, Git

### PyInstaller 단독 실행 EXE (배포용)

```bash
pyinstaller build/aru_archive.spec
```

빌드 결과: `dist/AruArchive/AruArchive.exe`

> `dist/` 디렉터리는 `.gitignore`에 포함되어 있습니다.

---

## 2. PyInstaller Spec 주요 내용

`build/aru_archive.spec`:

| 항목 | 내용 |
|------|------|
| 진입점 | `main.py` |
| 아이콘 | `app/resources/icons/aru_archive_icon.ico` |
| 포함 데이터 | `db/schema.sql`, `config.example.json`, `app/resources/icons/` |
| 숨겨진 임포트 | `piexif`, `httpx`, `PyQt6` 관련 플러그인 |
| 빌드 모드 | `onedir` (단일 폴더) |

### PyInstaller 주의사항

- **Python 경로 문제:** `spec` 파일이 `SPECPATH`를 기준으로 경로를 계산합니다. 다른 디렉터리에서 실행하면 오류가 납니다.
  ```bash
  # 반드시 프로젝트 루트에서 실행
  cd /path/to/aru_archive
  pyinstaller build/aru_archive.spec
  ```

- **native_host 포함 여부:** `native_host/host.py`는 별도 Python 환경이 필요하므로 EXE에 포함하지 않습니다. Native Host는 `install_host.bat`으로 별도 등록합니다.

- **config.json:** EXE 배포 시 `config.example.json`만 포함합니다. 사용자가 복사해 `config.json`을 만들어야 합니다.

- **PyQt6 플러그인:** PyInstaller가 Qt 플러그인(이미지 포맷, 스타일 등)을 자동 탐지하지 못할 경우 `hiddenimports`에 명시적으로 추가해야 합니다.

---

## 3. 브라우저 확장 배포

### 개발자 모드 로드 (현재 방식)

`extension/` 폴더를 Chrome / Whale 개발자 모드로 직접 로드합니다.

→ 설치 절차: [extension-setup.md](extension-setup.md)

### ZIP 배포 (크롬 웹스토어 / 배포용)

```bash
# extension/ 디렉터리를 ZIP으로 압축
cd extension
zip -r ../dist/aru_archive_extension_v0.3.0.zip .
```

> 크롬 웹스토어 배포는 별도 개발자 계정과 심사가 필요합니다.

---

## 4. Native Host 배포

| 파일 | 역할 |
|------|------|
| `build/install_host.bat` | 설치 스크립트 (registry 등록) |
| `build/uninstall_host.bat` | 제거 스크립트 |
| `build/gen_manifest.py` | manifest.json 생성기 (extension ID 주입) |
| `native_host/manifest_chrome.json` | Chrome용 template (PLACEHOLDER 포함) |
| `native_host/manifest_whale.json` | Whale용 template (PLACEHOLDER 포함) |

---

## 5. 릴리즈 구성 예시

```
AruArchive_v0.3.0/
├── AruArchive.exe              ← PyInstaller 빌드 (또는 Python 패키지)
├── aru_archive_extension.zip   ← 브라우저 확장
├── install_host.bat            ← Native Host 설치
├── uninstall_host.bat          ← Native Host 제거
├── gen_manifest.py             ← manifest 생성기 (Python 직접 실행 시)
├── config.example.json         ← 설정 파일 템플릿
├── README.md
└── docs/
    ├── extension-setup.md
    ├── troubleshooting.md
    └── ...
```

---

## 6. 버전 관리

릴리즈 전 다음 파일의 버전을 일치시킵니다.

| 파일 | 버전 필드 |
|------|-----------|
| `core/version.py` | `APP_VERSION`, `EXTENSION_VERSION` |
| `extension/manifest.json` | `"version"` |
| `extension/popup/popup.html` | footer 표시 버전 |
| `CHANGELOG.md` | 해당 버전 섹션 |

→ 상세: [release-checklist.md](release-checklist.md)

---

## 7. 배포 전 테스트

```bash
# 단위 테스트
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q

# PySide6 잔존 검사 (0건이어야 함)
grep -r "PySide6" --include="*.py" --include="*.js" --include="*.html" .

# PyInstaller 빌드 테스트
pyinstaller build/aru_archive.spec --clean
```
