// Aru Source Captioner — background service worker
//
// Phase 2A: 기본 옵션 seed 구현.
// - 신규 설치 또는 업데이트 시 chrome.storage.sync에 누락된 키만 기본값으로 채운다.
// - 기존 사용자가 설정한 값은 절대 덮어쓰지 않는다.
//
// 캡션 삽입 / EXIF·XMP 파싱은 Phase 2B에서 추가된다.

const DEFAULT_OPTIONS = Object.freeze({
  enabled: true,
  allowHttp: false,
  strictAllowlist: false,
  allowedHosts: ["pixiv.net", "x.com", "twitter.com"]
});

function seedMissingOptions() {
  chrome.storage.sync.get(null, (items) => {
    if (chrome.runtime.lastError) {
      console.warn("[Aru Source Captioner] storage.get failed:", chrome.runtime.lastError.message);
      return;
    }

    const updates = {};
    for (const key of Object.keys(DEFAULT_OPTIONS)) {
      if (!(key in items)) {
        updates[key] = DEFAULT_OPTIONS[key];
      }
    }

    if (Object.keys(updates).length === 0) {
      return;
    }

    chrome.storage.sync.set(updates, () => {
      if (chrome.runtime.lastError) {
        console.warn("[Aru Source Captioner] storage.set failed:", chrome.runtime.lastError.message);
        return;
      }
      console.info("[Aru Source Captioner] seeded missing default options:", Object.keys(updates));
    });
  });
}

chrome.runtime.onInstalled.addListener(() => {
  // install / update / chrome_update / shared_module_update 모두에 대해 누락 키만 보강한다.
  seedMissingOptions();
});

// Phase 2B 예정: content script가 옵션 변경을 즉시 반영해야 하는 경우
// chrome.runtime.onMessage 리스너를 여기에 등록한다. 현 Phase 2A에는 메시지 라우팅이
// 필요하지 않아 리스너 자체를 두지 않는다 (불필요한 listener 등록 방지).
