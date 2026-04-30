// Aru Source Captioner — options page script
//
// Phase 1: skeleton 단계.
// 폼 양방향 바인딩과 chrome.storage.sync 입출력은 Phase 2에서 구현합니다.

(function init() {
  "use strict";

  const DEFAULT_OPTIONS = Object.freeze({
    strictAllowlist: false,
    allowHttp: false,
    allowedHosts: ["pixiv.net", "x.com", "twitter.com"]
  });

  // TODO(phase2): chrome.storage.sync.get으로 현재 옵션을 읽어 폼에 반영한다.
  //   - 키가 없으면 DEFAULT_OPTIONS를 사용한다.
  //   - allowedHosts 배열은 textarea에 한 줄에 하나씩 표시한다.

  // TODO(phase2): submit 이벤트에서 폼 값을 검증하고 chrome.storage.sync.set으로 저장한다.
  //   - allowedHosts: 한 줄에 하나, 공백 trim, 빈 줄 무시.
  //   - 호스트명 형식 검증: 알파벳/숫자/하이픈/점만 허용.
  //   - 검증 실패 시 #save-status에 한국어 오류 메시지를 표시.
  //   - 저장 성공 시 #save-status에 "저장되었습니다." 표시.
  //   - 인라인 핸들러 사용 금지 (CSP 호환). addEventListener만 사용.

  // TODO(phase2): chrome.storage.onChanged 리스너로 다른 디바이스에서 변경된 값에
  //   대해 옵션 페이지가 열려 있을 때 자동 갱신한다 (선택).

  // Phase 1: 자리만 마련. 실제 동작은 수행하지 않는다.
  void DEFAULT_OPTIONS;
})();
