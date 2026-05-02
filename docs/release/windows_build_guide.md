# Aru Archive — Windows Build Packaging Guide

> **Canonical packaging guide.** `docs/packaging.md`는 이 문서를 가리키는 redirect다.

작성일: 2026-05-02 (v0.6.3 release cycle 직후)
대상 환경: Windows x64
대상 사용자: end-user (개발자 아님)

---

## 1. 배포 목표

- Windows x64 사용자에게 **ZIP 형태**로 배포 (1차)
- 설치 프로그램(Inno Setup)은 **후순위** (PR E)
- Browser extension은 **별도 ZIP** 또는 Store submission으로 분리
- 첫 공식 배포는 **PyInstaller onedir ZIP**

---

## 2. 현재 준비된 자산

| 자산 | 경로 | 용도 |
|---|---|---|
| PyInstaller spec | `build/aru_archive.spec` | onedir 빌드 정의 |
| ExifTool bundle check | `build/check_exiftool_bundle.py` | 빌드 전 검증 |
| ExifTool resolver | `core/exiftool_resolver.py` | frozen aware 탐색 chain |
| Resource path resolver | `app/resources/__init__.py` | `_MEIPASS` aware |
| ExifTool binary | `tools/exiftool/exiftool.exe` + Perl runtime | vendored |
| App icon | `assets/icon/aru_archive_icon.ico` | Window/taskbar |
| Splash | `assets/splash/splash.png` | startup splash |
| ExifTool license | `LICENSES/ExifTool.txt` | attribution |

부족:

- `scripts/build_windows.ps1` 없음 (**PR B**)
- `.github/workflows/windows-build.yml` 없음 (**PR D**)

---

## 3. 권장 빌드 방식

### 1차: PyInstaller `--onedir`

| 도구 | PyQt6 호환 | ExifTool bundle | 디버깅 | 빌드 속도 | 산출물 크기 | 첫 배포 적합성 |
|---|---|---|---|---|---|---|
| **PyInstaller --onedir** O | 검증됨 (spec 존재) | 매우 쉬움 (datas) | 쉬움 (`_internal/` 노출) | ~1-3분 | ~250-400 MB | ★★★★★ |
| PyInstaller --onefile | 동일 | 가능하나 첫 실행 5-15초 (압축 해제) | 어려움 | 약간 느림 | ~150-250 MB | ★★ |
| Nuitka standalone | 가능 (검증 필요) | 가능 | 중간 | 5-20분 (C 컴파일) | ~200 MB | ★★ |
| cx_Freeze | 가능 | 가능 | 중간 | 보통 | ~250-400 MB | ★ |

선택 이유:

1. spec이 이미 onedir로 작성됨 — 검증/수정 비용 최소
2. ExifTool Perl runtime(250+ files)이 onefile 압축 해제 비용 큼
3. resolver가 `Path(sys.executable).parent` 가정 — onedir와 정합
4. PyInstaller PyQt6 hook이 가장 성숙

### Installer 비교 (후순위 — PR E)

| 도구 | 한국어 | 장점 | 단점 |
|---|---|---|---|
| **Inno Setup** | 완전 지원 | 단순, 무료, Windows 표준 wizard | Windows-only 빌드 |
| NSIS | 가능 (UTF-8 처리 까다로움) | 가벼움 | 한국어 verbose |
| WiX (MSI) | 가능 | 기업 환경 친화 | 학습 곡선 |

권장: **Inno Setup** — 첫 installer로 적합.

---

## 4. 즉시 위험 (PR B에서 일괄 처리)

다음 5건은 첫 빌드 전 반드시 수정 필요. **이번 PR(A)에서는 수정하지 않는다.**

| # | 위험 | 처리 PR |
|---|---|---|
| 1 | `resources/tag_packs/`가 spec datas에 누락 — frozen 환경에서 built-in 9 tag pack 로드 깨짐 | PR B |
| 2 | `core/adapters/` dynamic import 여부 미확인 — hiddenimports 누락 시 어댑터 로드 실패 | PR B (사전 grep 필요) |
| 3 | `core/version.py APP_VERSION="0.3.0"` stale — 실제 tag `v0.6.3` | PR B |
| 4 | `main.py:158 setApplicationVersion("0.1.0")` hardcoded — `core.version.APP_VERSION` import로 교체 | PR B |
| 5 | `.gitignore`에 `dist/`, `release/` 누락 — 산출물 commit 사고 위험 | PR B |

---

## 5. 권장 산출물 구조

```
release/
  AruArchive-v0.6.3-win-x64.zip
  AruArchive-v0.6.3-win-x64.zip.sha256
```

ZIP 내부 (onedir 산출물 + 부가 파일):

```
AruArchive-v0.6.3-win-x64/
  AruArchive.exe              # entry point (대소문자 통일 — PR B에서 결정)
  _internal/                  # PyInstaller 6.x default contents-dir
    ...                       # Python runtime, PyQt6, Pillow, etc.
  resources/
    tag_packs/                # built-in 9 tag pack
      blue_archive.json
      ...
  assets/
    icon/
    splash/
  tools/
    exiftool/
      exiftool.exe
      exiftool(-k).exe
      exiftool_files/         # Perl runtime
  LICENSES/
    ExifTool.txt
    (Pillow.txt — 추가 필요)
    (httpx.txt — 추가 필요)
  README_FIRST.txt            # 사용자 첫 실행 안내
  README.md
  CHANGELOG.md
  LICENSE                     # 프로젝트 license (있으면)
```

---

## 6. 포함/제외 정책

### 포함 (spec datas/binaries)

- `app/`, `core/`, `db/` (코드 — Analysis가 자동 수집)
- `db/schema.sql` (datas)
- `resources/` 전체 (tag_packs 포함) ← **PR B에서 spec 보강**
- `assets/icon/`, `assets/splash/`
- `tools/exiftool/` (binaries 또는 datas)
- `LICENSES/` ← **PR B에서 spec 추가**
- `README.md`, `CHANGELOG.md` ← **PR B에서 spec 추가**
- `README_FIRST.txt` (build script가 동봉)

### 제외 (excludes 또는 자동 제외)

- `tests/`, `docs/` (자동)
- `.runtime/`, `.research/`, `temp/`, `build/`, `dist/`, `release/` (자동)
- `*.db`, `*.sqlite`, `*.db-wal`, `*.db-shm` (자동)
- `mojibake_report*.json`, `repair_plan*.json` (자동)
- `*.sample.json` (자동)
- `browser-extension/` (별도 ZIP — PR E)
- `tkinter`, `matplotlib`, `numpy`, `scipy` (excludes 등재)

---

## 7. Runtime data 정책

### 현재

| 항목 | 위치 |
|---|---|
| 기본 `data_dir` | `Path.home() / "AruArchive"` (= `C:\Users\<user>\AruArchive`) |
| DB | `{data_dir}/.runtime/aru.db` |
| 로그 | `{data_dir}/logs/` |
| 썸네일 | `{data_dir}/.thumbcache/` |
| `config.json` | `cwd/config.json` 또는 `~/.aru_archive/config.json` |

### 배포 시 권장

1. **사용자 데이터는 ZIP에 포함하지 않음** — 현 구조가 이미 분리됨 OK
2. ZIP 교체 업그레이드 시 `%USERPROFILE%\AruArchive\.runtime\aru.db` 그대로 보존
3. README_FIRST.txt에 사용자 데이터 위치 + 백업 방법 안내
4. (선택) 후속 PR에서 `os.environ.get("ARU_ARCHIVE_DATA_DIR")` override 지원 검토
5. (확인 필요) OneDrive sync 폴더(`%USERPROFILE%`)에서 SQLite DB lock 충돌 가능성 — corporate 환경

---

## 8. ExifTool bundle 전략

현재 `core/exiftool_resolver.py`의 탐색 chain:

1. `config["exiftool_path"]` (사용자 명시)
2. `<app_base>/tools/exiftool/exiftool.exe` (bundled)
3. `<app_base>/tools/exiftool/exiftool(-k).exe`
4. `shutil.which("exiftool")` (system PATH)

`get_app_base_path()`:

- `sys.frozen` + `_MEIPASS` → `_MEIPASS` (onefile)
- `sys.frozen` 만 → `Path(sys.executable).parent` (onedir)
- 비-frozen → 프로젝트 루트

→ **현재 코드는 onedir/onefile 양쪽 정합**. 추가 코드 변경 없이 spec datas만 유지되면 됨.

빌드 후 검증: `build/check_exiftool_bundle.py`로 frozen 환경에서 bundle 정상 인식 여부 확인.

ExifTool 미해결 시: PR-3 (#59)에서 추가한 `sync_status='json_only'` warning이 Workflow Step 8 완료 메시지에 표시.

---

## 9. Build script 설계 (PR B 대상)

### `scripts/build_windows.ps1` (의사코드 — PR B에서 구현)

```powershell
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)] [string]$Version,
    [switch]$Clean,
    [switch]$SkipChecks
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

# 0. 사전 검증
if (-not $SkipChecks) {
    & python "$Root/build/check_exiftool_bundle.py"
    & python -m pytest "$Root/tests/test_integrity_restore_hold_dialog.py" -q  # PySide6 invariant
    # version 정합 확인
    $av = & python -c "from core.version import APP_VERSION; print(APP_VERSION)"
    if ($av.Trim() -ne $Version) { throw "version mismatch" }
}

# 1. clean
if ($Clean) {
    Remove-Item -Recurse -Force "$Root/build/aru_archive", "$Root/dist", "$Root/release" -ErrorAction SilentlyContinue
}

# 2. PyInstaller
& pyinstaller "$Root/build/aru_archive.spec" --noconfirm --clean

# 3. release dir + bundle 정규화
$BundleName = "AruArchive-v$Version-win-x64"
$Release = "$Root/release"
New-Item -ItemType Directory -Force -Path $Release | Out-Null
Copy-Item -Recurse -Force "$Root/dist/aru_archive" "$Root/dist/$BundleName"

# 3b. 부가 파일 동봉
Copy-Item "$Root/README.md" "$Root/dist/$BundleName/"
Copy-Item "$Root/CHANGELOG.md" "$Root/dist/$BundleName/"
Copy-Item -Recurse "$Root/LICENSES" "$Root/dist/$BundleName/"
# README_FIRST.txt template 작성

# 4. ZIP
$Zip = "$Release/$BundleName.zip"
Compress-Archive -Path "$Root/dist/$BundleName/*" -DestinationPath $Zip -Force

# 5. SHA256
$Hash = (Get-FileHash $Zip -Algorithm SHA256).Hash
"$Hash  $BundleName.zip" | Out-File -Encoding ascii "$Release/$BundleName.zip.sha256"
```

---

## 10. GitHub Actions 가능성 (PR D 대상)

```yaml
# .github/workflows/windows-build.yml (의사코드)
name: Build Windows
on:
  push:
    tags: ['v*']
  workflow_dispatch:
    inputs:
      version: { required: true, type: string }

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r requirements.txt && pip install pyinstaller
      - shell: pwsh
        run: ./scripts/build_windows.ps1 -Version "${{ github.event.inputs.version || github.ref_name }}" -Clean
      - uses: actions/upload-artifact@v4
        with:
          name: AruArchive-windows-x64
          path: release/*
      - if: startsWith(github.ref, 'refs/tags/')
        uses: softprops/action-gh-release@v2
        with:
          files: |
            release/*.zip
            release/*.sha256
```

제약:

- ExifTool bundle: repo에 vendored됨 → CI 다운로드 불필요. 단 repo size 부담 (LFS 검토)
- Code signing: 미적용 시 SmartScreen 경고. 회피하려면 OV/EV 인증서 또는 Azure Trusted Signing (월 $9.99) — **PR F**

---

## 11. 외부 확인 필요 사항

| 항목 | 확인 대상 |
|---|---|
| ExifTool license / vendored 버전 / copyright 연도 | https://exiftool.org/ + bundled `exiftool_files/` 내부 LICENSE |
| PyQt6 LGPL 동적 링크 충족 | PyQt6 6.x license terms |
| Pillow / httpx / piexif attribution | 각 라이브러리 license — `LICENSES/`에 추가 필요 |
| Windows SmartScreen / code signing | https://learn.microsoft.com/en-us/microsoft-edge/web-platform/smartscreen-windows-defender |
| OneDrive sync 폴더에서 SQLite lock 충돌 | corporate 환경 사용자 보고 |
| `tools/exiftool/` repo size + LFS 검토 | git history size |
| Inno Setup 한국어 처리 | https://jrsoftware.org/files/istrans/ (`Korean.isl`) |

---

## 12. QA Checklist (clean Windows 환경)

| # | 항목 | 검증 |
|---|---|---|
| 1 | 첫 실행 DB 생성 | ZIP 압축 해제 → AruArchive.exe → `%USERPROFILE%\AruArchive\.runtime\aru.db` 생성 |
| 2 | Splash + 아이콘 | 정상 표시 |
| 3 | 작업 폴더 설정 | path-setup dialog → 임의 폴더 선택 → `config.json` 생성 |
| 4 | Inbox scan | 테스트 이미지 1개 scan |
| 5 | Pixiv enrichment (mock) | adapter 로직 동작 |
| 6 | Classification preview | 테스트 그룹 미리보기 |
| 7 | Classification execute | 분류 실행 + classified_copy 생성 |
| 8 | Explorer XP field | classified 파일 우클릭 → 속성 → 자세히 → 한글 정상 |
| 9 | json_only warning | ExifTool 경로 비정상 시뮬레이션 → Step 8 경고 |
| 10 | Explorer metadata repair | repair action 동작 |
| 11 | Missing file 카테고리 | 파일 1개 외부 삭제 후 사이드바 missing 카테고리 |
| 12 | Loading overlay | 장시간 작업 중 표시 + "백그라운드로 실행" |
| 13 | DB reset safety guard | 2단계 confirmation + `_before_reset_*.db` backup |
| 14 | Headless mode | `AruArchive.exe --headless` (필요 시 console=True 디버그 빌드) |
| 15 | 한글 경로 처리 | `D:\테스트폴더\` 에서 운영 |
| 16 | 두 번째 실행 (DB 보존) | exe 재실행 → 기존 DB/설정 유지 |
| 17 | ZIP 교체 업그레이드 | 새 ZIP로 폴더 통째 교체 → 사용자 데이터 무영향 |
| 18 | Defender 실시간 스캔 | 빌드 직후 격리/오탐 없음. 발생 시 Defender 제출 |
| 19 | check_exiftool_bundle.py | dist 폴더 안에서 검증 |

별도(후순위): Browser extension 별도 ZIP 설치 — `aru-source-captioner-vX.Y.Z.zip`

---

## 13. PR 분할안

| PR | 내용 | 변경 파일 | 위험도 | 우선순위 |
|---|---|---|---|---|
| **A** (이 PR) | docs/release/windows_build_guide.md 신규 + docs/packaging.md 갱신 | docs only | 낮음 | 1 |
| **B** | scripts/build_windows.ps1 + spec 보강 + .gitignore + version 정합 | 다수 (즉시 위험 5건 일괄) | 중간 | 2 |
| **C** | exiftool_resolver onedir 케이스 강화 + check_exiftool_bundle frozen 모드 | core, build/ | 중간 | 3 |
| **D** | .github/workflows/windows-build.yml | workflow 1개 | 중간 | 4 |
| **E** | Inno Setup .iss + browser extension 별도 ZIP | installer + scripts | 중간 | 5 |
| **F** | Code signing | scripts + workflow | 높음 (비용) | 6 |
