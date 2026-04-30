# Aru Source Captioner

루리웹 유게 잡담 게시판 글쓰기 페이지에서, 본문에 첨부한 이미지의 EXIF / XMP 메타데이터에 담긴 출처 URL을 읽어 이미지 바로 아래에 출처 캡션을 자동으로 삽입하는 브라우저 확장 프로그램입니다.

> **현재 상태: Phase 1 — 구조와 문서, MV3 최소 skeleton만 포함합니다.** 실제 EXIF/XMP 파싱과 캡션 삽입 로직은 Phase 2 이후 추가됩니다.

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
| `strictAllowlist` | `false` | 켜면 `allowedHosts`에 등록된 호스트만 캡션 삽입 |
| `allowHttp` | `false` | 켜면 http URL도 허용 (기본은 https만) |
| `allowedHosts` | `["pixiv.net", "x.com", "twitter.com"]` | 엄격 모드에서 허용할 호스트 목록 |

## Phase 1 범위

| 포함 | 제외 |
|---|---|
| MV3 manifest 골격 | EXIF/XMP 파서 라이브러리 |
| content / background / options 자리 | 실제 캡션 삽입 동작 |
| 정책·DOM 관찰·권한 문서 | popup, icons, 빌드 도구 |
| `lib/`, `docs/` 디렉터리 안내 | 단위 테스트 프레임워크 |

자세한 설계는 [`docs/phase1-design.md`](docs/phase1-design.md) 참고.

## 라이선스

데스크톱 앱과 동일한 라이선스 정책을 따르되, 별도 라이선스 사용이 결정되면 본 디렉터리에 `LICENSE` 파일을 추가합니다. (Phase 1: 결정 보류)

## 관련 문서

- [`docs/phase1-design.md`](docs/phase1-design.md) — Phase 1 정책과 매칭 알고리즘 (16개 정책 명문화)
- [`docs/ruliweb-dom-notes.md`](docs/ruliweb-dom-notes.md) — 루리웹 DOM 동작 관찰 기록 (8개 사실)
- [`docs/permissions.md`](docs/permissions.md) — manifest 권한의 사유와 비요청 권한 목록
- [`lib/README.md`](lib/README.md) — 향후 모듈 분할 계획
