# Packaging

> ⚠ 이 문서는 사용자가 자주 참조하는 안내가 새 canonical 가이드로 이동한 흔적 redirect입니다.
>
> **현행 가이드: [docs/release/windows_build_guide.md](release/windows_build_guide.md)**

## 변경 요약

- v0.6.3 release cycle 준비 과정에서 packaging 분석 결과를 통합 가이드로 정리
- PyInstaller onedir → ZIP 1차 배포 방식 채택
- ExifTool bundle, runtime data 위치, QA checklist (19항목), PR 분할안 등은 모두 새 가이드 참조
- 즉시 위험 5건은 새 가이드 §4 (PR B에서 일괄 처리)

---

## 기존 내용 보존 (참고용)

다음 항목은 새 가이드 범위 밖이거나 주제가 다르므로 짧게 요약만 남깁니다.

### Icon Assets

아이콘 리소스는 `assets/icon/source/icon_1.png`에서 생성됩니다. 재생성:

```bash
python build/generate_icons.py
```

생성 산출물 (요약):

- `assets/icon/aru_archive_icon.ico` — Windows 앱 / PyInstaller 아이콘
- `assets/icon/aru_archive_icon_master.png` — RGBA master
- `assets/icon/aru_archive_icon_{size}.png` — 16/32/48/64/128/256/512/1024
- `extension/icons/icon{size}.png` — 브라우저 확장 (16/32/48/128)
- `docs/icon.png` — README 대표 이미지 (256px)

### Python 직접 실행 (개발자 / 개인 사용)

```bash
pip install -r requirements.txt
python main.py
```

요구사항: Python 3.12+, Git

### PyInstaller 빌드 명령

```bash
pyinstaller build/aru_archive.spec
```

> 반드시 프로젝트 루트에서 실행 (spec이 `SPECPATH` 기준 경로 계산).
> 산출물: `dist/aru_archive/` — 자세한 산출물 구조와 권장 ZIP 레이아웃은 새 가이드 §5.

빌드 전 ExifTool 번들 검증:

```bash
python build/check_exiftool_bundle.py
```

### 브라우저 확장 배포

`extension/` 폴더를 Chrome/Whale 개발자 모드로 직접 로드합니다. 설치 절차: [extension-setup.md](extension-setup.md).

ZIP 배포 (스토어 / 별도 배포):

```bash
cd extension
zip -r ../dist/aru_archive_extension_v<VERSION>.zip .
```

> 새 가이드 §13 PR E에서 "browser extension 별도 ZIP" 트랙으로 묶을 예정.

### Native Host 배포

Native Host (`native_host/host.py`)는 별도 Python 환경이 필요하므로 EXE에 포함하지 않습니다.

| 파일 | 역할 |
|------|------|
| `build/install_host.bat` | 설치 스크립트 (registry 등록) |
| `build/uninstall_host.bat` | 제거 스크립트 |
| `build/gen_manifest.py` | manifest.json 생성기 (extension ID 주입) |
| `native_host/manifest_chrome.json` | Chrome용 template (PLACEHOLDER 포함) |
| `native_host/manifest_whale.json` | Whale용 template (PLACEHOLDER 포함) |

상세: [native-messaging.md](native-messaging.md).

### 버전 관리

릴리즈 전 다음 파일의 버전을 일치시킵니다.

| 파일 | 버전 필드 |
|------|-----------|
| `core/version.py` | `APP_VERSION`, `EXTENSION_VERSION` |
| `extension/manifest.json` | `"version"` |
| `extension/popup/popup.html` | footer 표시 버전 |
| `CHANGELOG.md` | 해당 버전 섹션 |

상세: [release-checklist.md](release-checklist.md).

### 배포 전 테스트

```bash
# 단위 테스트
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q

# PySide6 잔존 검사 (0건이어야 함)
grep -r "PySide6" --include="*.py" --include="*.js" --include="*.html" .

# ExifTool 번들 검증
python build/check_exiftool_bundle.py

# PyInstaller 빌드 테스트
pyinstaller build/aru_archive.spec --clean
```
