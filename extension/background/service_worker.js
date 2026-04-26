/**
 * Aru Archive background service worker (Manifest V3).
 *
 * 프로토콜 v2:
 *   SW → native host: {action, request_id, payload}
 *   native host → SW: {success, request_id, data} | {success, request_id, error}
 *
 * 액션:
 *   ping               — 연결 확인
 *   save_pixiv_artwork — 현재 Pixiv 페이지 저장
 *   open_main_app      — Aru Archive GUI 실행
 *   get_job_status     — 저장 작업 상태 조회
 */

"use strict";

const NATIVE_HOST = "net.aru_archive.host";

// ---------------------------------------------------------------------------
// Native host 연결
// ---------------------------------------------------------------------------

let _port = null;
const _pending = new Map(); // request_id → {resolve, reject}
let _reqCounter = 0;

function getNativePort() {
  if (_port) return _port;
  _port = chrome.runtime.connectNative(NATIVE_HOST);

  _port.onMessage.addListener((msg) => {
    const cb = _pending.get(msg.request_id);
    if (cb) {
      _pending.delete(msg.request_id);
      if (msg.success) cb.resolve(msg.data ?? {});
      else cb.reject(new Error(msg.error ?? "native_error"));
    }
  });

  _port.onDisconnect.addListener(() => {
    _port = null;
    const err = chrome.runtime.lastError?.message ?? "native_host_disconnected";
    for (const cb of _pending.values()) cb.reject(new Error(err));
    _pending.clear();
  });

  return _port;
}

function sendNative(action, payload = {}) {
  return new Promise((resolve, reject) => {
    const request_id = String(++_reqCounter);
    _pending.set(request_id, { resolve, reject });
    try {
      getNativePort().postMessage({ action, request_id, payload });
    } catch (e) {
      _pending.delete(request_id);
      reject(e);
    }
  });
}

// ---------------------------------------------------------------------------
// Context menu
// ---------------------------------------------------------------------------

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id:                  "aru_save",
    title:               "Aru Archive에 저장",
    contexts:            ["page"],
    documentUrlPatterns: ["https://www.pixiv.net/*/artworks/*", "https://www.pixiv.net/artworks/*"],
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "aru_save" && tab?.id) {
    handleSaveRequest(tab.id).catch((err) => console.error("[AruArchive] Context menu save failed:", err));
  }
});

// ---------------------------------------------------------------------------
// popup 메시지 처리
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === "save_request") {
    handleSaveRequest(message.tab_id)
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((err)   => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.type === "ping_request") {
    sendNative("ping")
      .then(() => sendResponse({ ok: true }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.type === "job_status_request") {
    sendNative("get_job_status", { job_id: message.job_id })
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  return false;
});

// ---------------------------------------------------------------------------
// 저장 흐름
// ---------------------------------------------------------------------------

async function handleSaveRequest(tabId) {
  // content_script에서 artwork_id + preload_data 수집
  let contentResp;
  try {
    contentResp = await chrome.tabs.sendMessage(tabId, { type: "save_artwork" });
  } catch {
    throw new Error("content_script_unavailable");
  }

  if (!contentResp.ok) {
    throw new Error(contentResp.error ?? "content_script_error");
  }

  const { artwork_id, url, title, preload_data } = contentResp;

  // native host로 save_pixiv_artwork 요청
  const data = await sendNative("save_pixiv_artwork", {
    artwork_id,
    page_url:     url,
    title,
    preload_data,
  });

  return { artwork_id, job_id: data.job_id };
}
