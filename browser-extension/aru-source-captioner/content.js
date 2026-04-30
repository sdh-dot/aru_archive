// Aru Source Captioner — content script
//
// Phase 2A: 설정 로드와 enabled 체크 구현.
// - chrome.storage.sync에서 옵션을 로드해 DEFAULT_OPTIONS와 병합.
// - enabled가 false면 즉시 중단 (어떤 DOM 변경도 하지 않음).
// - 글쓰기 페이지 판별, EXIF·XMP 파싱, MutationObserver 캡션 삽입은 Phase 2B에서 추가.
//
// Phase 1 정책(16개 + DOM 관찰 8항)은 docs/phase1-design.md 단일 출처를 따른다.
// 본 파일은 정책 요지만 인용한다.
//
// 절대 규칙:
//   - innerHTML / outerHTML / insertAdjacentHTML 사용 금지.
//   - eval / new Function 사용 금지.
//   - "출처 없음" placeholder 절대 삽입 금지.
//   - 페이지 상단의 출처 입력란은 절대 건드리지 않는다.
//   - File.name === img.alt 정확 비교만 사용 (img.src는 매칭에 사용하지 않는다).

(function bootstrap() {
  "use strict";

  const DEFAULT_OPTIONS = Object.freeze({
    enabled: true,
    allowHttp: false,
    strictAllowlist: false,
    allowedHosts: ["pixiv.net", "x.com", "twitter.com"]
  });

  function loadConfig() {
    return new Promise((resolve) => {
      chrome.storage.sync.get(null, (items) => {
        if (chrome.runtime.lastError) {
          console.warn(
            "[Aru Source Captioner] storage.get failed, falling back to defaults:",
            chrome.runtime.lastError.message
          );
          resolve({ ...DEFAULT_OPTIONS });
          return;
        }
        const merged = { ...DEFAULT_OPTIONS };
        for (const key of Object.keys(DEFAULT_OPTIONS)) {
          if (key in items) {
            merged[key] = items[key];
          }
        }
        resolve(merged);
      });
    });
  }

  async function init() {
    const config = await loadConfig();

    if (!config.enabled) {
      console.info("[Aru Source Captioner] disabled — skipping content script");
      return;
    }

    // Phase 2A: 설정 로드까지만 수행. 실제 캡션 로직은 아직 동작하지 않는다.
    //
    // Phase 2B 이후 추가 예정 (구현 순서):
    //   1. 글쓰기 페이지 정확 판별 — location.pathname / 본문 에디터 root /
    //      input[type=file] 존재 여부로 보수적 early-return.
    //   2. input[type=file] change 캡처 → image/* File을 pendingByFileName Map에 push
    //      (Map<string, Array<Record>>, 같은 파일명은 FIFO).
    //   3. MutationObserver — addedNodes 안에서 <p> > <img> 패턴만 처리.
    //   4. exifr 도입 후 parseSourceFromFile(file) — 우선순위 6단계
    //      (artwork_url > source_url > XMP Source/Identifier > UserComment 등 JSON >
    //       문자열 URL 패턴).
    //   5. sanitizeSourceUrl(rawUrl, config) — new URL() + scheme + strictAllowlist.
    //   6. 캡션 노드 빌드 (DOM API만) → 부모 <p>의 afterend로 삽입 +
    //      data-aru-source-caption="1" 마커 + 다음 형제 텍스트 검사로 중복 방지.
    console.info(
      "[Aru Source Captioner] phase 2A loaded (settings only — caption pending Phase 2B)",
      { strictAllowlist: config.strictAllowlist, allowHttp: config.allowHttp }
    );
  }

  init().catch((err) => {
    console.warn("[Aru Source Captioner] init failed:", err);
  });
})();
