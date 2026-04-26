/**
 * Aru Archive background service worker (Manifest V3).
 *
 * 역할:
 *  1. popup → SW: "save_request" 수신
 *  2. SW → content_script: "save_artwork" 전송 → preload_data 수집
 *  3. SW → native host: {type:"save", ...} 전달
 *  4. native host 응답 → popup에 결과 중계
 */

"use strict";

const NATIVE_HOST = "net.aru_archive.host";

// ---------------------------------------------------------------------------
// Native host 연결
// ---------------------------------------------------------------------------

let _port = null;
const _pendingCallbacks = new Map(); // requestId → {resolve, reject}
let _requestCounter = 0;

function getNativePort() {
  if (_port) return _port;
  _port = chrome.runtime.connectNative(NATIVE_HOST);
  _port.onMessage.addListener((msg) => {
    const cb = _pendingCallbacks.get(msg.request_id);
    if (cb) {
      _pendingCallbacks.delete(msg.request_id);
      if (msg.ok) cb.resolve(msg);
      else cb.reject(new Error(msg.error || "native_error"));
    }
  });
  _port.onDisconnect.addListener(() => {
    _port = null;
    for (const [id, cb] of _pendingCallbacks) {
      cb.reject(new Error("native_host_disconnected"));
    }
    _pendingCallbacks.clear();
  });
  return _port;
}

function sendNative(message) {
  return new Promise((resolve, reject) => {
    const request_id = ++_requestCounter;
    _pendingCallbacks.set(request_id, { resolve, reject });
    try {
      getNativePort().postMessage({ ...message, request_id });
    } catch (e) {
      _pendingCallbacks.delete(request_id);
      reject(e);
    }
  });
}

// ---------------------------------------------------------------------------
// popup 메시지 처리
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "save_request") {
    handleSaveRequest(message.tab_id)
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true; // 비동기 응답
  }
  return false;
});

async function handleSaveRequest(tabId) {
  // 1. content_script에서 preload_data 수집
  let contentResp;
  try {
    contentResp = await chrome.tabs.sendMessage(tabId, { type: "save_artwork" });
  } catch (e) {
    throw new Error("content_script_unavailable");
  }

  if (!contentResp.ok) {
    throw new Error(contentResp.error || "content_script_error");
  }

  const { artwork_id, url, preload_data } = contentResp;

  // 2. native host로 전달
  const nativeResp = await sendNative({
    type: "save",
    source_site: "pixiv",
    artwork_id,
    url,
    preload_data,
  });

  return { artwork_id, job_id: nativeResp.job_id };
}
