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

## Phase 2B에서 수행할 캡션 기능 테스트 (예정)

> Phase 2A 완료 시점에는 아직 동작하지 않습니다. 아래 항목은 Phase 2B 진입 후에 검증합니다.

### 메타데이터 추출

- [ ] EXIF UserComment / ImageDescription에 JSON이 포함된 이미지에서 출처 URL이 추출되는가
- [ ] XMP `Source` / `Identifier`에 출처 URL이 있는 이미지에서 추출되는가
- [ ] AruArchive `artwork_url` / `source_url` JSON 필드가 우선순위대로 사용되는가
- [ ] 메타데이터가 없는 이미지는 캡션이 삽입되지 않는가 (정책 6)

### URL 보안

- [ ] `https://...` URL은 통과하는가
- [ ] `http://...`은 `allowHttp=false` 시 차단되는가
- [ ] `http://...`은 `allowHttp=true` 시 통과하는가
- [ ] `javascript:` / `data:` / `vbscript:` / `file:` / `chrome:` / `chrome-extension:` / `about:`은 차단되는가
- [ ] `strictAllowlist=true` 시 `allowedHosts`에 등록된 호스트와 그 서브도메인만 통과하는가

### DOM 동작

- [ ] 단일 이미지 업로드 시 부모 `<p>` 바로 다음에 캡션이 삽입되는가
- [ ] 다중 이미지 업로드 시 각 이미지에 정확히 매칭된 출처가 삽입되는가
- [ ] 같은 파일명 record가 여러 개일 때 FIFO로 소비되는가
- [ ] 한글/공백/괄호 파일명도 매칭되는가
- [ ] 이미 캡션이 있는 이미지에 중복 삽입되지 않는가 (`data-aru-source-caption` 마커 + 다음 형제 검사)
- [ ] source mode ↔ WYSIWYG mode 전환 후에도 캡션이 보존되는가
- [ ] "출처 없음" placeholder가 절대 삽입되지 않는가 (정책 7)
- [ ] 페이지 상단의 출처 입력란이 절대 변경되지 않는가 (정책 8)

### 회귀

- [ ] 글쓰기가 아닌 게시판 페이지(목록/상세)에서는 캡션 로직이 동작하지 않는가
- [ ] EXIF 파싱 실패 시 페이지 동작에 영향을 주지 않는가 (silent fail)
- [ ] DOM Mutation이 많은 페이지에서 성능 저하가 없는가
