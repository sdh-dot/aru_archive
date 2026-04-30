// Aru Source Captioner — content script
//
// Phase 1: skeleton 단계.
// 본 파일은 manifest.matches에 의해 루리웹 게시판 경로에서 로드되지만,
// 현재는 어떤 DOM 변경도 수행하지 않습니다.
// 실제 매칭/캡션 삽입 로직은 Phase 2 이후 추가됩니다.
//
// Phase 1 정책 요약 (자세한 내용은 docs/phase1-design.md 참고):
//   1.  파일 매칭은 File.name === img.alt 기준으로 한다.
//   2.  img.src(루리웹 CDN WebP URL)는 매칭에 사용하지 않는다.
//   3.  캡션은 이미지가 들어있는 부모 <p> 바로 다음에 삽입한다.
//   4.  캡션 형식:
//         <p style="text-align: center;">
//           출처: <a href="..." target="_blank" rel="noopener noreferrer">...</a>
//         </p>
//   5.  안전한 출처 URL이 있는 경우에만 캡션을 삽입한다.
//   6.  메타데이터 또는 URL이 없으면 아무것도 삽입하지 않는다.
//   7.  "출처 없음" placeholder는 절대 삽입하지 않는다.
//   8.  페이지 상단의 출처 입력란은 절대 건드리지 않는다.
//   9.  innerHTML / outerHTML / insertAdjacentHTML 사용 금지 (DOM API만 사용).
//   10. URL 검증은 new URL() 파서를 사용한다.
//   11. 기본은 https만 허용.
//   12. http는 옵션(allowHttp)이 true일 때만 허용 — 기본값 false.
//   13. javascript:, data:, vbscript:, file:, chrome:, chrome-extension:, about: 등
//       http/https가 아닌 모든 스킴을 차단한다.
//   14. allowlist 정책:
//         - strictAllowlist 기본값 false
//         - allowedHosts 기본값 ["pixiv.net", "x.com", "twitter.com"]
//   15. 같은 파일명 record가 여러 개 있으면 차단하지 않고 FIFO로 하나씩 소비한다.
//   16. 중복 캡션 방지는 파일명이 아니라 DOM 기준으로 한다:
//         - 이미지가 captioned 마커(예: data-aru-source-caption="1")를 갖고 있으면 skip.
//         - 이미지 부모 <p>의 다음 형제가 "출처:"로 시작하고 a[href]를 포함하면 skip.

(function init() {
  "use strict";

  // TODO(phase1): 실제 글쓰기 페이지인지 판별한다.
  //   manifest.matches는 게시판 전체 URL 패턴(.../community/board/300143/*)이지만,
  //   해당 경로 안에는 글 목록 / 글 상세 / 글쓰기 등 여러 페이지가 있다.
  //   글쓰기 에디터(본문 contenteditable 등)의 안정적인 selector를 확인한 뒤
  //   여기서 early-return 한다. 확정 전까지는 어떤 DOM 변경도 수행하지 않는다.
  //
  //   판별 후보 (Phase 2 진입 시 실측):
  //     - location.pathname 마지막 segment가 "write"인지 검사
  //     - 본문 에디터 root selector 존재 여부 검사
  //     - 첨부 파일 input[type=file] 존재 여부 검사
  //
  //   참고: 잘못된 판별로 다른 페이지에서 동작하면 정책 8(상단 출처 입력란 미접촉)이
  //         깨질 위험이 있으므로 보수적으로 판별한다.

  // TODO(phase2): 옵션을 background에 요청하거나 chrome.storage.sync에서 직접 읽는다.
  // TODO(phase2): 사용자가 첨부한 File 목록을 추적한다 (FileList <-> img.alt FIFO 큐).
  //   - input[type=file] change 이벤트 hook
  //   - 드래그 앤 드롭 업로드 hook (필요 시)
  // TODO(phase2): 에디터의 이미지 노드 추가를 MutationObserver로 감시한다.
  //   - addedNodes 안에서 <p> > <img> 패턴만 처리
  // TODO(phase2): EXIF/XMP 파서를 도입하고 출처 URL을 추출한다.
  //   - 파서 라이브러리 선정은 Phase 2 진입 시 결정
  // TODO(phase2): URL 검증 (scheme + allowlist) 후 DOM API만으로 캡션을 삽입한다.

  // Phase 1: skeleton 단계 — 어떤 동작도 수행하지 않는다.
  return;
})();
