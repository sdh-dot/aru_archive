/**
 * Pixiv content script.
 * background service worker의 "save_artwork" 메시지에 응답하여
 * 현재 페이지의 artwork_id, title, preload_data를 반환한다.
 */

"use strict";

/** Pixiv 작품 URL에서 artwork_id를 추출한다 (순수 함수, 테스트 가능). */
function extractPixivArtworkIdFromUrl(url) {
  const m = url.match(/\/artworks\/(\d+)/);
  return m ? m[1] : null;
}

/**
 * window.__NEXT_DATA__ 또는 window.__INITIAL_STATE__에서
 * preload_data JSON을 추출한다. 없으면 null 반환.
 */
function extractPreloadData() {
  try {
    if (globalThis.__NEXT_DATA__) {
      const props = globalThis.__NEXT_DATA__.props?.pageProps;
      if (props) return props;
    }
    if (globalThis.__INITIAL_STATE__) {
      return globalThis.__INITIAL_STATE__;
    }
  } catch (e) {
    console.debug("[AruArchive] preload_data 접근 오류:", e);
  }
  return null;
}

/** 페이지 타이틀에서 artwork_id 이후 부분을 잘라 제목을 추출한다. */
function extractTitle() {
  try {
    if (globalThis.__NEXT_DATA__?.props?.pageProps?.illust?.title) {
      return globalThis.__NEXT_DATA__.props.pageProps.illust.title;
    }
  } catch (e) {
    console.debug("[AruArchive] title 추출 오류:", e);
  }
  return document.title || "";
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type !== "save_artwork") return false;

  const artwork_id = extractPixivArtworkIdFromUrl(location.href);
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
    url:   location.href,
    title: extractTitle(),
    preload_data,
  });
  return false;
});
