// Aru Source Captioner — background service worker
//
// Phase 1: skeleton 단계.
// 본 service worker는 현재 실제 메시지 라우팅을 수행하지 않습니다.
// 향후 옵션 변경 알림, content script 헬스체크, 옵션 시드 등의 자리로 사용됩니다.

const DEFAULT_OPTIONS = Object.freeze({
  strictAllowlist: false,
  allowHttp: false,
  allowedHosts: ["pixiv.net", "x.com", "twitter.com"]
});

// TODO(phase2): chrome.runtime.onInstalled 핸들러에서 chrome.storage.sync에
// DEFAULT_OPTIONS를 시드한다 (값이 없을 때만 — 사용자가 이미 설정한 값을 덮어쓰지 않는다).
chrome.runtime.onInstalled.addListener((details) => {
  // Phase 1: 자리만 마련. 실제 시드 로직은 Phase 2에서 추가한다.
  void details;
});

// TODO(phase2): content script가 옵션을 요청할 때 응답하는 메시지 라우팅을 추가한다.
//   - 메시지 형식과 응답 스키마는 Phase 2 진입 시 docs/phase1-design.md에 추가 정의한다.
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Phase 1: 자리만 마련. 어떤 메시지도 처리하지 않는다.
  void message;
  void sender;
  void sendResponse;
  return false;
});

// 사용 시 import할 수 없도록 의도적으로 export를 두지 않는다 (service worker 컨텍스트).
void DEFAULT_OPTIONS;
