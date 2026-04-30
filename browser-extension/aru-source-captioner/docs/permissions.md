# 권한 명세 — Aru Source Captioner

본 확장은 권한을 최소한으로 요청합니다. `manifest.json`에 선언된 각 권한의 사유와, 의도적으로 요청하지 않은 권한 목록을 함께 기록합니다.

> Phase 2A에서 아이콘(`icons` / `action.default_icon`)이 추가되었으나 **새로운 권한 요청은 없습니다.** `icons` 필드는 manifest 메타데이터일 뿐 권한이 아니며, `action`은 도구바 표시용으로 별도 권한을 요구하지 않습니다.
>
> **Phase 2B에서 `lib/exifr.full.umd.js` (vendored, MIT)가 도입되었으나 새로운 권한 요청은 없습니다.** exifr는 로컬에 동봉된 정적 JS 파일로 동작하며, 외부 네트워크 호출을 수행하지 않습니다. 메타데이터 파싱은 사용자가 첨부한 File 객체를 브라우저 내부에서만 읽습니다. `host_permissions`는 여전히 루리웹 글쓰기 게시판 한 곳에 한정됩니다.

## 요청하는 권한

### `permissions`

| 권한 | 사유 | 사용 위치 |
|---|---|---|
| `storage` | 사용자 옵션(`enabled`, `strictAllowlist`, `allowHttp`, `allowedHosts`)을 `chrome.storage.sync`에 저장하기 위해 필요 | `options.js`, `background.js`, `content.js` |

### `host_permissions`

| 호스트 패턴 | 사유 |
|---|---|
| `https://bbs.ruliweb.com/community/board/300143/*` | 루리웹 유게 잡담 게시판 글쓰기 페이지에서 content script가 동작하기 위해 필요. 게시판 외 도메인은 일절 접근하지 않는다. |

> 글쓰기 페이지 정확 판별은 content script가 page selector / location 검사로 수행하며, manifest 단계에서는 게시판 전체 경로(`/community/board/300143/*`)를 host로 잡습니다. (Phase 2에서 정확 selector로 좁히거나 content script 내 early-return으로 제한)

## 의도적으로 요청하지 않는 권한

다음 권한은 본 확장의 동작에 불필요하므로 절대 요청하지 않습니다.

| 권한 | 요청하지 않는 사유 |
|---|---|
| `nativeMessaging` | Phase 1 동작은 브라우저 내부에서 완결됩니다. 데스크톱 Aru Archive 앱과의 통신은 사용하지 않습니다. |
| `tabs` | content script는 자기 탭의 DOM만 다루며, 다른 탭 정보가 필요하지 않습니다. |
| `activeTab` | popup이 없고, 사용자가 명시적으로 활성화하는 동작도 없습니다. |
| `webRequest` / `webRequestBlocking` | 네트워크 요청 가로채기를 수행하지 않습니다. |
| `cookies` | 쿠키를 읽거나 변경하지 않습니다. |
| `scripting` | 동적 스크립트 주입 없이 manifest의 `content_scripts`만 사용합니다. |
| `contextMenus` | 컨텍스트 메뉴를 추가하지 않습니다. |
| `<all_urls>` 호스트 권한 | 루리웹 유게 잡담 게시판 외 사이트에는 접근하지 않습니다. |
| `clipboardRead` / `clipboardWrite` | 클립보드를 다루지 않습니다. |
| `downloads` | 파일 다운로드를 수행하지 않습니다. |
| `notifications` | 시스템 알림을 띄우지 않습니다. |
| `unlimitedStorage` | 작은 옵션값만 저장하므로 표준 storage quota로 충분합니다. |

## 데이터 처리 정책

- 원본 이미지 파일은 사용자 브라우저 내에서만 읽으며, 외부 서버로 전송하지 않습니다.
- EXIF / XMP 메타데이터는 출처 URL 추출 목적으로만 사용하고 디스크나 외부에 저장하지 않습니다.
- 사용자 옵션은 `chrome.storage.sync`에 저장됩니다 (구글 계정 연동 시 디바이스 간 동기화).
- 본 확장은 어떠한 분석 / 트래킹 코드도 포함하지 않습니다.
- 본 확장은 사용자가 작성 중인 본문 텍스트를 읽거나 외부로 전송하지 않습니다. 본문 영역에 대한 동작은 캡션 삽입에 한정됩니다.

## 변경 시 절차

권한 추가가 필요해지면 다음 절차를 따릅니다.

1. 본 문서에 사유를 추가.
2. `README.md`의 권한 요약에도 반영.
3. QA-TEST 에이전트가 `manifest.json`의 권한 목록을 본 문서와 대조하여 검증.
4. 사용자(설치자) 관점에서 추가 권한이 명백히 정당한지 재검토.

권한 축소(제거)는 자유롭게 수행하되, 호환성 영향이 있으면 CHANGELOG에 기록합니다.

## 점검 명령 예시 (참고)

다음 명령으로 manifest의 권한이 본 문서와 일치하는지 빠르게 확인할 수 있습니다 (실행은 QA 단계에서).

```text
- manifest.json의 "permissions" 키에 storage 외 항목이 없는지
- manifest.json의 "host_permissions" 키에 ruliweb 외 호스트가 없는지
- manifest.json에 "nativeMessaging"이라는 문자열이 등장하지 않는지
```
