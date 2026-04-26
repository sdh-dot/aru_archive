# Aru Archive

<p align="center">
  <img src="docs/icon.png" width="160" alt="Aru Archive icon">
</p>

개인 아트워크 아카이브 관리 도구.  
Pixiv 등 소스에서 수집한 파일을 메타데이터 기반으로 분류·관리합니다.

**플랫폼:** Windows 11 · Python 3.12+ · PyQt6 · SQLite · v0.4.0

---

## 구성 요소

| 경로 | 역할 |
|------|------|
| `main.py` | GUI 진입점, 설정 로드, 로깅 초기화 |
| `app/` | PyQt6 데스크톱 UI (갤러리, 분류 미리보기, 작업 로그) |
| `core/` | 스캔, 메타데이터, Pixiv 보강, 태그·경로 분류 엔진 |
| `db/` | SQLite 초기화 및 스키마 |
| `extension/` | Chrome / Naver Whale MV3 브라우저 확장 |
| `native_host/` | Native Messaging Host (protocol v2) |
| `build/` | 설치 스크립트 및 패키징 설정 |
| `tests/` | pytest 테스트 스위트 |
| `docs/` | 설계 문서 |

---

## 빠른 시작

```bash
pip install -r requirements.txt
python main.py
```

설정 파일 지정:

```bash
python main.py --config path/to/config.json
```

`config.example.json`을 `config.json`으로 복사하여 `data_dir`, `inbox_dir`, `db.path`를 수정하세요.

### 작업 마법사 (권장 진입점)

앱 실행 후 툴바의 **[🧭 작업 마법사]** 를 클릭하면 9단계 순서형 가이드가 시작됩니다:

1. **Archive Root** — 아카이브 루트 폴더 설정
2. **Scan** — Inbox 파일 스캔
3. **메타데이터 확인** — 상태 요약 및 경고 표시
4. **메타데이터 보강** — Pixiv에서 메타데이터 가져오기
5. **사전 정규화** — 태그 alias / 후보 검토
6. **태그 재분류** — 사전 업데이트 반영
7. **분류 미리보기** — 경로·위험도 확인
8. **분류 실행** — Classified 폴더에 복사
9. **결과 / Undo** — 작업 이력 및 Undo

자세한 설명: [docs/workflow-wizard.md](docs/workflow-wizard.md)

---

## 브라우저 확장 설치

1. Chrome / Whale에서 `extension/` 폴더를 개발자 모드로 로드 → **확장 ID 복사**
2. Native Host 등록:
   ```bat
   build\install_host.bat chrome <extension_id>
   ```
3. 브라우저 재시작 → 팝업 **연결 테스트** → "연결 성공 ✓" 확인

자세한 절차: [docs/extension-setup.md](docs/extension-setup.md)

---

## 기본 사용법

1. `python main.py` 실행
2. **[📁 Archive Root 선택]** → 아카이브 루트 폴더 선택
3. **[🔍 Inbox 스캔]** → Pixiv 파일 검색
4. 갤러리에서 항목 선택 → **[🌐 Pixiv 메타데이터 가져오기]**
5. **[📋 분류 미리보기]** → 경로 확인 → **[▶ 분류 실행]**
6. Ctrl+Click으로 여러 항목 선택 → **[📋 일괄 분류]** → 범위·언어 설정 후 미리보기·실행
7. **[🕘 작업 로그]** → Undo 가능

Pixiv 작품 페이지에서 팝업 **저장** 버튼으로 직접 저장도 가능합니다.

---

## 테스트

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q
```

현재 750개 이상 테스트 통과.

---

## Bundled ExifTool (내장 ExifTool)

Aru Archive는 XMP 메타데이터 기록을 위해 Portable ExifTool을 내장할 수 있습니다.

### 내장 ExifTool 배치 경로

```text
tools/
└── exiftool/
    ├── exiftool.exe          ← 실행 파일
    └── exiftool_files/       ← Perl 런타임 및 라이브러리
```

> Windows 공식 배포판은 `exiftool(-k).exe` 이름으로 배포됩니다.  
> `exiftool.exe` 로 이름을 변경하면 표준 동작이 됩니다.  
> 이름 변경 없이 `exiftool(-k).exe` 를 그대로 두어도 자동 탐색됩니다.

### 탐색 우선순위

| 순서 | 경로 |
|------|------|
| 1 | `config.json`의 `exiftool_path` |
| 2 | `tools/exiftool/exiftool.exe` (개발 / onedir 배포) |
| 3 | `sys._MEIPASS/tools/exiftool/exiftool.exe` (onefile 배포) |
| 4 | 시스템 PATH의 `exiftool` |
| 5 | (없으면) `json_only` 유지 |

`config.json`의 `exiftool_path`를 `null` 또는 생략하면 자동 탐색합니다:

```json
{ "exiftool_path": null }
```

### 번들 검증

```bash
python build/check_exiftool_bundle.py
```

### 라이선스

ExifTool은 Phil Harvey가 개발했으며 Artistic License 또는 GPL v2 이상으로 배포됩니다.  
→ [LICENSES/ExifTool.txt](LICENSES/ExifTool.txt)

---

## ExifTool XMP 설정 (사용자 지정 경로)

내장 ExifTool 대신 별도 설치 버전을 사용하려면 config.json에 경로를 지정합니다:

```json
{ "exiftool_path": "C:/exiftool/exiftool.exe" }
```

ExifTool이 없으면 AruArchive JSON만 기록됩니다 (`json_only` 상태 유지).

기록되는 XMP 필드: `XMP-dc:Title/Creator/Subject/Source/Identifier`,  
`XMP:MetadataDate`, `XMP:Rating`, `XMP:Label`

XMP 기록에 실패하면 `xmp_write_failed` 상태로 표시됩니다 (⚠ 사이드바).  
Detail 패널 `[🔄 XMP 재시도]` 또는 툴바 `[🔄 전체 XMP 재처리]`로 재시도할 수 있습니다.

---

## 문서

| 문서 | 내용 |
|------|------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 전체 시스템 아키텍처, 데이터 흐름, DB 스키마 |
| [docs/native-messaging.md](docs/native-messaging.md) | Native Messaging 프로토콜 v2 명세 |
| [docs/extension-setup.md](docs/extension-setup.md) | 브라우저 확장 설치 절차 |
| [docs/metadata-policy.md](docs/metadata-policy.md) | 메타데이터 정책, sync_status 값 |
| [docs/classification-policy.md](docs/classification-policy.md) | 4-tier 분류 정책, 충돌 처리 |
| [docs/tag-normalization.md](docs/tag-normalization.md) | 태그 정규화 파이프라인 |
| [docs/packaging.md](docs/packaging.md) | PyInstaller 패키징, 릴리즈 구성 |
| [docs/troubleshooting.md](docs/troubleshooting.md) | 문제 해결 가이드 |
| [docs/release-checklist.md](docs/release-checklist.md) | 릴리즈 전 확인 항목 |
| [CHANGELOG.md](CHANGELOG.md) | 버전별 변경 이력 |

---

## 현황 / 로드맵

**v0.4.0 (현재)**
- PyQt6 데스크톱 앱 + Chrome/Whale 브라우저 확장
- Native Messaging 프로토콜 v2 (5개 액션)
- 4-tier 분류 엔진 + 태그 정규화 파이프라인
- **Tag Pack 시스템** — `resources/tag_packs/*.json`에서 시리즈/캐릭터 alias + 로컬라이제이션 자동 시드
- **4단계 alias 매칭** — DB → built-in → 정규화(normalize_tag_key) 순서, 전각/공백 변형 처리
- **미분류 태그 후보 생성** — `series_uncategorized` / `author_fallback` 감지 → `tag_candidates` 생성 (사용자 승인 필요)
- **외부 사전 가져오기** — Danbooru / Safebooru에서 캐릭터·시리즈 후보 수집, confidence 점수 기반 스테이징, 사용자 승인 후 `tag_aliases` 반영 (`[🌐 웹 사전]`); Danbooru 차단 시 Safebooru fallback 지원
- 다국어 폴더명 (ko/ja/en) — `tag_localizations` DB + 내장 Blue Archive 데이터
- 일괄 분류 (Batch Classification) — 재분류 옵션, 실패 원인 요약, Ctrl+Click 다중 선택
- Undo 시스템, 저장 작업 실시간 모니터링
- **ExifTool XMP 연동** — `XMP-dc:*` + `XMP:Rating/Label/MetadataDate` 기록, XMP 재시도 UI

**예정**
- Pixiv 쿠키 자동 수집 (R-18 저장 지원)
- EXE 독립 배포 빌드
