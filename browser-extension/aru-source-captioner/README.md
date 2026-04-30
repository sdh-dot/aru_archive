# Aru Source Captioner

루리웹 유게 잡담 게시판 글쓰기 페이지에서, 본문에 첨부한 이미지의 EXIF / XMP 메타데이터에 담긴 출처 URL을 읽어 이미지 바로 아래에 출처 캡션을 자동으로 삽입하는 브라우저 확장 프로그램입니다.

> **현재 상태: Phase 2B + PNG iTXt 보강.** EXIF / XMP / IPTC / UserComment 메타데이터에서 출처 URL을 추출해 이미지 부모 `<p>` 바로 다음에 캡션을 삽입합니다. 메타데이터 파싱은 vendored [exifr](https://github.com/MikeKovarik/exifr) 7.1.3 (`lib/exifr.full.umd.js`, MIT)을 사용하며, **PNG는 Aru Archive 데스크톱 앱이 사용하는 비표준 iTXt(`keyword="AruArchive"`) chunk를 직접 파싱**해 XMP가 없는 PNG에서도 출처 캡션이 동작합니다.

## 동작 흐름 (설계상)

1. 사용자가 글쓰기 페이지에서 이미지를 업로드합니다.
2. 루리웹은 이미지를 CDN URL로 변환하지만 `img.alt`에 원본 파일명을 그대로 유지합니다.
3. 확장이 `File.name === img.alt` 매칭으로 사용자가 첨부한 원본 파일과 DOM의 이미지를 연결합니다.
4. 원본 파일에서 EXIF/XMP 메타데이터를 읽어 출처 URL을 추출합니다.
5. URL이 안전(https + allowlist)이면 이미지의 부모 `<p>` 바로 다음에 출처 캡션 `<p>`를 삽입합니다.

> 안전한 출처 URL이 없으면 아무것도 삽입하지 않습니다. "출처 없음" 같은 placeholder는 절대 넣지 않습니다.

## 지원 사이트

- 루리웹 유게 잡담 게시판 글쓰기 페이지

본 확장은 위 사이트 외 다른 도메인에는 일절 접근하지 않습니다. 자세한 권한 정책은 [`docs/permissions.md`](docs/permissions.md)를 참고하세요.

## 설치 (개발 빌드)

1. Chrome 또는 네이버 웨일에서 `chrome://extensions` (또는 `whale://extensions`) 접속.
2. 우측 상단의 **개발자 모드** 켜기.
3. **압축해제된 확장 프로그램 로드** 클릭.
4. 이 디렉터리(`browser-extension/aru-source-captioner/`)를 선택.

## 권한

본 확장은 권한을 최소한으로 요청합니다.

- `storage` — 사용자 옵션(allowlist 등) 저장.
- `host_permissions` — 루리웹 유게 잡담 게시판 도메인 한정.

Native Messaging은 사용하지 않습니다. 데스크톱 Aru Archive 앱과 독립적으로 동작합니다.

자세한 사유는 [`docs/permissions.md`](docs/permissions.md) 참고.

## 옵션

옵션 페이지는 `chrome://extensions` → 본 확장의 **세부정보** → **확장 프로그램 옵션**에서 열 수 있습니다 (별도 탭으로 열림).

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `enabled` | `true` | 끄면 캡션 삽입을 시도하지 않습니다 (변경은 페이지 새로고침 후 적용) |
| `strictAllowlist` | `false` | 켜면 `allowedHosts`에 등록된 호스트만 캡션 삽입 |
| `allowHttp` | `false` | 켜면 http URL도 허용 (기본은 https만) |
| `allowedHosts` | `["pixiv.net", "x.com", "twitter.com"]` | 엄격 모드에서 허용할 호스트 목록 |

설정은 `chrome.storage.sync`에 저장되며 구글 계정 연동 시 디바이스 간 동기화됩니다.

## Phase 1 범위

| 포함 | 제외 |
|---|---|
| MV3 manifest 골격 | EXIF/XMP 파서 라이브러리 |
| content / background / options 자리 | 실제 캡션 삽입 동작 |
| 정책·DOM 관찰·권한 문서 | popup, icons, 빌드 도구 |
| `lib/`, `docs/` 디렉터리 안내 | 단위 테스트 프레임워크 |

## Phase 2A 범위

| 포함 | 제외 |
|---|---|
| 확장 아이콘 4종 (16/32/48/128) | EXIF/XMP 파서 라이브러리 |
| `manifest` `icons` / `action` | 실제 캡션 삽입 동작 |
| 옵션 4키 저장/로드 (`chrome.storage.sync`) | source URL 추출 로직 |
| `background` `onInstalled` 누락 키 seed | MutationObserver 캡션 삽입 |
| `content.js` `loadConfig` + `enabled` 체크 | `File.name === img.alt` 매칭 |
| Phase 2 테스트 체크리스트 | `popup` |

## PNG iTXt 보강 (D2)

| 포함 | 제외 |
|---|---|
| Aru Archive 데스크톱 앱이 PNG에 저장하는 비표준 `iTXt` chunk(`keyword="AruArchive"`)를 직접 파싱 | `compression_flag=1` (zlib-compressed iTXt) — 미지원, fallback |
| `parseSourceFromFile`에서 PNG일 때 exifr보다 **먼저** 시도하고 성공 시 우선 사용 | non-PNG 포맷은 기존 exifr 경로 유지 |
| 파일에 XMP가 없어도 AruArchive iTXt만 있으면 출처 캡션 동작 | sidecar `.aru.json` |
| 추출 우선순위: `artwork_url` → `source_url` → `artworkUrl` | 본 파서는 raw URL만 반환, sanitize는 기존 `sanitizeSourceUrl` 그대로 사용 |
| 실패 시 silent fallback to exifr (throw 0건, `console.warn` 0건) | 권한 추가 0건 (`File.arrayBuffer()`만 사용) |

## Phase 2B 범위 (현재)

| 포함 | 제외 (Phase 2C 이후) |
|---|---|
| **`exifr@7.1.3` full UMD vendoring** (`lib/exifr.full.umd.js` + `lib/exifr.LICENSE`) | `chrome.storage.onChanged` 즉시 반영 (현재는 페이지 새로고침 필요) |
| EXIF / XMP / IPTC / UserComment 파싱 | `*.aru.json` sidecar 지원 |
| 출처 URL 우선순위 6단계 추출 | `lib/` 모듈 분할 |
| URL 보안 검증 (scheme + strict allowlist) | popup UI |
| `input[type=file] change` (capture phase) 감지 | 단위 테스트 프레임워크 |
| `pendingByFileName` Map FIFO 큐 | self-check (DOM 관찰 8항 회귀 감지) |
| MutationObserver 기반 `<p> > <img>` 감지 | |
| `File.name === img.alt`(또는 `img.title`) 매칭 | |
| 캡션 `<p>` DOM API 빌드 + `target="_blank"` + `rel="noopener noreferrer"` | |
| 중복 방지 (`data-aru-source-caption` 마커 + 다음 형제 텍스트 검사) | |

### 알려진 제한 사항 (Phase 2B + PNG iTXt)

- 옵션 변경(`enabled` / `allowHttp` / `strictAllowlist` / `allowedHosts`)은 **페이지 새로고침 후 적용**됩니다. 즉시 반영은 Phase 2C TODO.
- 메타데이터에 출처 URL이 없거나 안전한 URL이 없으면 **아무것도 삽입하지 않습니다**. "출처 없음" placeholder는 절대 미삽입.
- 매칭 키는 `File.name === img.alt`(또는 `img.title`) 정확 일치만 사용 — 루리웹 측 변경으로 `alt`가 사라지면 동작하지 않습니다.
- 글쓰기 페이지 selector는 `[contenteditable="true"]`, `.cke_editable`, `.fr-element`, `.editor` 후보를 시도하며, 60초 내 발견되지 않으면 캡션 기능이 disable됩니다.
- **PNG iTXt 파서는 `compression_flag=0`(uncompressed)만 지원**합니다. compressed iTXt(`compression_flag=1`, zlib 압축)는 미지원이며 자동으로 exifr fallback으로 넘어갑니다 — Phase 3 후보.
- **`*.aru.json` sidecar 미지원**입니다 — 사용자가 sidecar를 별도로 첨부해야 접근 가능하며 본 파서 범위 외입니다.

자세한 설계는 [`docs/phase1-design.md`](docs/phase1-design.md) 참고. 검증 항목은 [`docs/phase2-test-checklist.md`](docs/phase2-test-checklist.md) 참고. 라이브러리 의존성은 [`lib/README.md`](lib/README.md) 참고.

## 라이선스

데스크톱 앱과 동일한 라이선스 정책을 따르되, 별도 라이선스 사용이 결정되면 본 디렉터리에 `LICENSE` 파일을 추가합니다. (Phase 1: 결정 보류)

## 관련 문서

- [`docs/phase1-design.md`](docs/phase1-design.md) — Phase 1 정책과 매칭 알고리즘 (16개 정책 명문화)
- [`docs/ruliweb-dom-notes.md`](docs/ruliweb-dom-notes.md) — 루리웹 DOM 동작 관찰 기록 (8개 사실)
- [`docs/permissions.md`](docs/permissions.md) — manifest 권한의 사유와 비요청 권한 목록
- [`docs/phase2-test-checklist.md`](docs/phase2-test-checklist.md) — Phase 2 단계별 수동 검증 항목
- [`lib/README.md`](lib/README.md) — 향후 모듈 분할 계획 (현재 비어있음, exifr는 Phase 2B 도입 예정)
