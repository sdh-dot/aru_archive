/**
 * Aru Archive popup script.
 * Pixiv artwork 상세 페이지에서 저장 버튼을 활성화하고
 * 클릭 시 background SW로 save_request를 전달한다.
 */

"use strict";

const ARTWORK_URL_PATTERN = /^https:\/\/www\.pixiv\.net\/(?:en\/)?artworks\/(\d+)/;

const btnSave = document.getElementById("btn-save");
const statusMsg = document.getElementById("status-msg");

function setStatus(text, cls = "") {
  statusMsg.textContent = text;
  statusMsg.className = cls;
}

async function init() {
  let tab;
  try {
    [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  } catch (_) {
    setStatus("탭 정보를 가져올 수 없습니다.", "error");
    return;
  }

  if (!tab || !ARTWORK_URL_PATTERN.test(tab.url || "")) {
    setStatus("Pixiv 작품 페이지에서 사용하세요.");
    return;
  }

  setStatus("저장 준비 완료");
  btnSave.disabled = false;

  btnSave.addEventListener("click", () => onSaveClick(tab.id));
}

async function onSaveClick(tabId) {
  btnSave.disabled = true;
  setStatus("저장 중...", "running");

  let resp;
  try {
    resp = await chrome.runtime.sendMessage({
      type: "save_request",
      tab_id: tabId,
    });
  } catch (e) {
    setStatus("오류: 백그라운드 연결 실패", "error");
    btnSave.disabled = false;
    return;
  }

  if (!resp || !resp.ok) {
    const msg = errorToKorean(resp?.error);
    setStatus(`오류: ${msg}`, "error");
    btnSave.disabled = false;
    return;
  }

  setStatus(`저장 완료 (job: ${resp.job_id?.slice(0, 8) ?? "?"})`, "success");
}

function errorToKorean(error) {
  const MAP = {
    not_artwork_page: "작품 페이지가 아닙니다",
    no_dom_data: "페이지 데이터를 찾을 수 없습니다",
    content_script_unavailable: "페이지를 새로고침 후 다시 시도하세요",
    native_host_disconnected: "Aru Archive 앱이 실행 중인지 확인하세요",
  };
  return MAP[error] ?? error ?? "알 수 없는 오류";
}

init();
