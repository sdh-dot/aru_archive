/**
 * Pixiv content script.
 * preload_data (window.__INITIAL_STATE__ 또는 globalThis.__NEXT_DATA__)를 추출하여
 * background service worker로 전달한다.
 *
 * MVP-A: save 버튼 메시지 수신 시 현재 페이지의 artwork 데이터를 응답한다.
 */

"use strict";

/** Pixiv 작품 상세 페이지 URL 패턴 */
const ARTWORK_URL_PATTERN = /^https:\/\/www\.pixiv\.net\/(?:en\/)?artworks\/(\d+)/;

/**
 * window.__NEXT_DATA__ 또는 window.__INITIAL_STATE__ 에서
 * preload_data JSON을 추출한다.
 * 없으면 null 반환.
 */
function extractPreloadData() {
  try {
    // Next.js 기반 (현재 Pixiv)
    if (window.__NEXT_DATA__) {
      const props = window.__NEXT_DATA__.props?.pageProps;
      if (props) return props;
    }
    // 구형 fallback
    if (window.__INITIAL_STATE__) {
      return window.__INITIAL_STATE__;
    }
  } catch (_) {
    // 접근 오류 무시
  }
  return null;
}

/**
 * 현재 URL에서 artwork_id를 추출한다.
 * artwork 상세 페이지가 아니면 null 반환.
 */
function getArtworkId() {
  const m = location.href.match(ARTWORK_URL_PATTERN);
  return m ? m[1] : null;
}

/**
 * background service worker의 "save_artwork" 메시지에 응답한다.
 */
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type !== "save_artwork") return false;

  const artwork_id = getArtworkId();
  if (!artwork_id) {
    sendResponse({ ok: false, error: "not_artwork_page" });
    return false;
  }

  const preload_data = extractPreloadData();
  if (!preload_data) {
    sendResponse({ ok: false, error: "no_dom_data", artwork_id });
    return false;
  }

  sendResponse({
    ok: true,
    artwork_id,
    url: location.href,
    preload_data,
  });
  return false;
});
