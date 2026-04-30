# Phase 2 테스트 체크리스트

본 문서는 Aru Source Captioner의 Phase 2 단계별 수동 검증 항목을 정리합니다. Phase 2A는 인프라(아이콘·옵션·설정 로드)에 한정하며, 실제 캡션 삽입은 Phase 2B에서 추가됩니다.

## Phase 2A — 인프라 검증

### 0. 사전 준비

- 작업 폴더: `browser-extension/aru-source-captioner/`
- 압축해제된 확장 프로그램 로드:
  - Chrome: `chrome://extensions` → 개발자 모드 ON → "압축해제된 확장 프로그램 로드" → 위 폴더 선택
  - Whale: `whale://extensions` → 개발자 모드 ON → 동일 절차
- 확장이 이미 로드되어 있다면 새로고침(↻) 한 번 누른다.

### 1. Chrome 로드 테스트

- [ ] `chrome://extensions`에서 "Aru Source Captioner"가 활성 상태로 보인다.
- [ ] 오류 표시(빨간 "오류" 배지)가 없다.
- [ ] manifest 파싱 오류가 콘솔/페이지에 보고되지 않는다.

### 2. Whale 로드 테스트

- [ ] `whale://extensions`에서 동일 항목이 활성 상태로 보인다.
- [ ] 오류 표시가 없다.

### 3. 아이콘 표시 확인

- [ ] 브라우저 도구바(주소 표시줄 우측)의 확장 아이콘 영역에 본 확장 아이콘이 보인다.
- [ ] 아이콘에 마우스를 올리면 툴팁 "Aru Source Captioner"가 표시된다.
- [ ] `chrome://extensions` 카드 위쪽 아이콘이 깨지지 않는다 (16/32/48/128 모두 정상).
- [ ] 확장 관리 페이지의 "세부정보"에서 큰 아이콘(128px)이 정상 표시된다.

### 4. options 페이지 표시 확인

- [ ] 확장 카드의 "세부정보" → "확장 프로그램 옵션" 클릭 시 새 탭이 열린다 (`open_in_tab: true`).
- [ ] 옵션 페이지 제목이 "Aru Source Captioner — 옵션"이다.
- [ ] 다음 4개 입력이 보인다.
  - [ ] 확장 활성화 (체크박스, `id="opt-enabled"`)
  - [ ] 엄격 모드 (체크박스, `id="opt-strict-allowlist"`)
  - [ ] http URL도 허용 (체크박스, `id="opt-allow-http"`)
  - [ ] 허용 호스트 목록 (textarea, `id="opt-allowed-hosts"`)
- [ ] 저장 버튼 (`id="btn-save"`)과 상태 영역 (`id="save-status"`)이 보인다.

### 5. 옵션 저장/로드 확인

- [ ] 페이지 첫 로드 시 다음 기본값이 반영되어 있다.
  - 확장 활성화: 켜짐
  - 엄격 모드: 꺼짐
  - http 허용: 꺼짐
  - allowedHosts: `pixiv.net`, `x.com`, `twitter.com` (한 줄에 하나)
- [ ] 한 옵션을 변경하고 "저장" 클릭 시 상태 영역에 "저장되었습니다."가 표시된다.
- [ ] 옵션 페이지를 닫았다가 다시 열면 변경 값이 유지된다.
- [ ] allowedHosts에 빈 줄을 섞어 저장 후 다시 열면 빈 줄이 제거되어 표시된다.
- [ ] DevTools 콘솔에 옵션 페이지 관련 오류(`Uncaught ...`)가 없다.

### 6. enabled off 시 content script 동작 중단 확인

- [ ] "확장 활성화" 체크 해제 후 저장.
- [ ] 루리웹 글쓰기 페이지를 새로고침한다.
- [ ] DevTools(F12) → Console 탭에서 다음 메시지가 보인다.
      `[Aru Source Captioner] disabled — skipping content script`
- [ ] 페이지에 어떤 DOM 변경도 발생하지 않는다 (Phase 2B 캡션 로직 자체가 아직 없으므로 자명).
- [ ] 다시 활성화 후 저장하고 페이지 새로고침하면 다음 메시지가 보인다.
      `[Aru Source Captioner] phase 2A loaded (settings only — caption pending Phase 2B)`

### 7. 루리웹 글쓰기 페이지 content.js 주입 확인

- [ ] 루리웹 유게 잡담 게시판(`https://bbs.ruliweb.com/community/board/300143/...`) 글쓰기 페이지로 이동.
- [ ] DevTools → Sources 탭의 Content Scripts 영역에 `content.js`가 로드되어 있다.
- [ ] Console에 위 6번의 phase 2A loaded 메시지가 한 번만 출력된다.
- [ ] 다른 사이트(예: `https://www.naver.com`)에서는 위 메시지가 출력되지 않는다 (host_permissions 한정).

### 8. 콘솔 오류 확인

- [ ] DevTools Console 탭에 본 확장 관련 오류(`[Aru Source Captioner] ...`로 시작하는 빨간 메시지)가 없다.
- [ ] `chrome://extensions` 카드의 "오류" 배지가 0이다.
- [ ] background service worker(`chrome://extensions` → 카드 → "service worker" 링크 → DevTools)에서도 오류가 없다.
- [ ] 처음 설치 시 background 콘솔에 다음 메시지가 한 번 보일 수 있다 (정상).
      `[Aru Source Captioner] seeded missing default options: [...]`

## Phase 2B — 캡션 자동 삽입 검증 (현재)

### 0. 사전 준비

- 확장을 새로 로드하거나 재로드한다 (`chrome://extensions` → 본 확장 카드의 ↻).
- 콘솔 메시지 확인:
  - `[Aru Source Captioner] phase 2B active — caption insertion enabled` (정상)
  - `[Aru Source Captioner] exifr not loaded — caption insertion disabled` (라이브러리 로드 실패 — 즉시 보고 필요)

### 1. 메타데이터 추출 — XMP `Source`

- [ ] XMP `Source = "https://www.pixiv.net/artworks/123456789"` 포함된 이미지를 첨부.
- [ ] 이미지 부모 `<p>` 바로 다음에 출처 캡션이 삽입된다.
- [ ] 캡션 형식: `<p style="text-align: center;" data-aru-source-caption="1">출처: <a href="https://www.pixiv.net/artworks/123456789" target="_blank" rel="noopener noreferrer">https://www.pixiv.net/artworks/123456789</a></p>`

### 2. 메타데이터 추출 — XMP `Identifier`

- [ ] XMP `Identifier = "https://x.com/user/status/...."` (string 또는 array) 포함된 이미지를 첨부.
- [ ] 출처 캡션이 삽입된다.

### 3. 메타데이터 추출 — AruArchive JSON (`artwork_url` / `source_url` / `artworkUrl`)

- [ ] EXIF `UserComment` 또는 `ImageDescription` 또는 `Description`에 다음 JSON 문자열이 포함된 이미지를 첨부:
  - `{"artwork_url": "https://www.pixiv.net/artworks/...", "source_url": "..."}`
- [ ] 출처 캡션이 `artwork_url` 값으로 삽입된다 (정책 1이 우선).

### 4. 메타데이터 추출 — UserComment 직접 URL

- [ ] `UserComment = "https://www.pixiv.net/..."` (JSON 아님, raw URL string) 이미지를 첨부.
- [ ] 출처 캡션이 삽입된다.

### 5. 메타데이터 추출 — 문자열 fallback (정책 7)

- [ ] 위 1~4 키에는 URL 없고 다른 임의 문자열 필드(예: `Software` 안에 `https://...`)에 URL이 있는 이미지를 첨부.
- [ ] 출처 캡션이 삽입된다 (단, 우선순위 1~6보다 후순위).

### 6. 메타데이터 없음

- [ ] EXIF / XMP / IPTC가 모두 비어있는 평범한 이미지를 첨부.
- [ ] **캡션 미삽입**, "출처 없음" 등 어떤 문구도 본문에 들어가지 않는다.

### 7. URL 보안 — unsafe scheme 차단

- [ ] 다음 각각의 scheme을 가진 URL이 메타데이터에 있는 이미지를 첨부:
  - `javascript:alert(1)`
  - `data:text/html,...`
  - `vbscript:...`
  - `file:///C:/...`
  - `chrome://extensions/`
  - `chrome-extension://...`
  - `about:blank`
- [ ] 각 케이스에서 **캡션 미삽입**.

### 8. URL 보안 — http 정책

- [ ] 옵션 `allowHttp=false`(기본): `http://example.com/...` URL 이미지 → **캡션 미삽입**.
- [ ] 옵션 `allowHttp=true`로 변경 + 페이지 새로고침: 동일 이미지 → 캡션 삽입.

### 9. URL 보안 — strict allowlist

- [ ] 옵션 `strictAllowlist=true`, `allowedHosts=["pixiv.net"]`로 변경 + 페이지 새로고침.
- [ ] `https://www.pixiv.net/...` 이미지 → 캡션 삽입 (서브도메인 매칭).
- [ ] `https://example.com/...` 이미지 → **캡션 미삽입**.

### 10. 다중 업로드 (서로 다른 파일명)

- [ ] 3개의 서로 다른 이미지(`a.jpg`, `b.jpg`, `c.jpg`)를 동시 업로드.
- [ ] 각 이미지 아래에 자기 파일의 출처 URL이 정확히 매칭된 캡션이 삽입된다.

### 11. 동명 다중 업로드 (FIFO)

- [ ] `same.jpg`를 다른 EXIF로 2회 연속 업로드.
- [ ] 첫 번째 이미지 아래에 1번째 record의 출처, 두 번째 이미지 아래에 2번째 record의 출처가 삽입된다.

### 12. `enabled=false` 시 비활성

- [ ] 옵션에서 "확장 활성화" 끔 + 저장 + 페이지 새로고침.
- [ ] 어떤 이미지를 첨부해도 캡션이 삽입되지 않는다.
- [ ] 콘솔에 `[Aru Source Captioner] disabled — skipping content script`만 표시된다.

### 13. 한글/공백/괄호 파일명

- [ ] `한글 파일 (1).jpg` 같은 파일명 + 출처 URL EXIF가 있는 이미지를 첨부.
- [ ] 캡션이 정확히 삽입된다 (정책 1: `File.name === img.alt` 정확 일치).

### 14. 중복 방지 — 마커 기반

- [ ] 같은 페이지에서 첨부 직후 페이지 전환/뒤로가기 등으로 캡션 삽입 후 같은 이미지가 다시 노출되어도 **두 번 삽입되지 않는다** (`data-aru-source-captioned="1"` 마커 검사).

### 15. 중복 방지 — 사용자 직접 작성한 캡션 보존

- [ ] 사용자가 직접 `<p>출처: <a href="...">...</a></p>`을 이미지 다음 줄에 작성한 후 그 위 이미지에 대해 본 확장이 추가 삽입을 시도해도 **본 확장은 새 캡션을 추가하지 않는다** (다음 형제 텍스트 검사).

### 16. source mode ↔ WYSIWYG mode 전환

- [ ] 캡션 삽입 후 에디터의 source mode/WYSIWYG mode를 토글.
- [ ] 캡션 HTML이 그대로 보존된다 (DOM 관찰 §7·8 — `target="_blank"`, `rel="noopener noreferrer"` 속성 포함).

### 17. 페이지 상단 출처 입력란 보호

- [ ] 어떤 시나리오에서도 페이지 상단의 루리웹 자체 "출처" 입력 필드는 변경되지 않는다 (정책 8).

### 18. WebP / JPEG / PNG 포맷별 검증

- [ ] 각 포맷별로 1~3번 시나리오를 반복 — 모두 캡션 삽입.

### 19. Whale에서 1~18번 동일 검증

- [ ] 네이버 웨일에서 위 모든 항목을 다시 한 번 통과한다.

### 20. 콘솔 오류

- [ ] 1~19번 어느 시나리오에서도 빨간색 오류 메시지 0건. `console.warn` / `console.info` / `console.debug`만 허용.
- [ ] `chrome://extensions`의 "오류" 배지 0건.
- [ ] background service worker 콘솔에도 오류 0건 (단 첫 설치 시 `seeded missing default options` 메시지는 정상).

## 회귀 검사 (Phase 2A 항목)

Phase 2A에서 통과한 8개 인프라 항목(아이콘·옵션 저장/로드·`enabled` gate 등)도 Phase 2B 변경 후 다시 통과해야 합니다. 위 §1~§8 (Phase 2A)을 재실행하여 회귀 없음을 확인.

## 알려진 제한 사항

- 옵션 변경 시 즉시 반영 안 됨 — 페이지 새로고침 필요 (Phase 2C TODO).
- `*.aru.json` sidecar 미지원 (Phase 3 후보).
- 글쓰기 페이지 selector 미발견 시 60초 대기 후 boot observer 자동 종료.
- 루리웹 측 DOM 변경(예: `img.alt` 제거)이 발생하면 매칭 실패 — silent skip.
