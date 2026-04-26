/**
 * Aru Archive popup script.
 */

"use strict";

const ARTWORK_URL_PATTERN = /^https:\/\/www\.pixiv\.net\/(?:en\/)?artworks\/(\d+)/;

const btnSave     = document.getElementById("btn-save");
const btnPing     = document.getElementById("btn-ping");
const statusMsg   = document.getElementById("status-msg");
const artworkInfo = document.getElementById("artwork-info");

function setStatus(text, cls = "") {
  statusMsg.textContent = text;
  statusMsg.className = cls;
}

// ---------------------------------------------------------------------------
// 초기화 (top-level await)
// ---------------------------------------------------------------------------

let activeTabId  = null;
let activeArtworkId = null;

{
  let tab;
  try {
    [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  } catch (e) {
    console.debug("[AruArchive] 탭 조회 실패:", e);
    setStatus("탭 정보를 가져올 수 없습니다.", "error");
    tab = null;
  }

  const match = ARTWORK_URL_PATTERN.exec(tab?.url ?? "");
  if (match) {
    activeTabId     = tab.id;
    activeArtworkId = match[1];
    artworkInfo.textContent = `artwork_id: ${activeArtworkId}`;
    setStatus("저장 준비 완료");
    btnSave.disabled = false;
  } else {
    setStatus("Pixiv 작품 페이지에서 사용하세요.");
  }
}

// ---------------------------------------------------------------------------
// 저장 상태 폴링
// ---------------------------------------------------------------------------

/**
 * job_id로 저장 상태를 1초마다 폴링한다.
 * completed / partial / failed 시 종료, 최대 60회(60초).
 */
async function pollJobStatus(jobId) {
  const MAX_POLLS = 60;
  let polls = 0;

  return new Promise((resolve) => {
    const timer = setInterval(async () => {
      polls++;
      if (polls > MAX_POLLS) {
        clearInterval(timer);
        setStatus("저장 상태 확인 타임아웃. 저장 작업 창을 열어 확인하세요.", "error");
        btnSave.disabled = false;
        resolve(null);
        return;
      }

      let resp;
      try {
        resp = await chrome.runtime.sendMessage({ type: "job_status_request", job_id: jobId });
      } catch (e) {
        console.debug("[AruArchive] job_status_request 전송 실패:", e);
        clearInterval(timer);
        setStatus("상태 조회 중 연결 끊김. 저장 작업 창에서 확인하세요.", "error");
        btnSave.disabled = false;
        resolve(null);
        return;
      }

      if (!resp?.ok) {
        // 일시적 오류 → 폴링 계속 (job_not_found 포함)
        return;
      }

      const data     = resp.data ?? {};
      const progress = data.progress ?? {};
      const status   = data.status;

      // 진행 중 업데이트
      if (status === "running" && progress.total_pages > 0) {
        setStatus(
          `저장 중… ${progress.saved_pages}/${progress.total_pages} 페이지`,
          "running",
        );
      }

      if (status === "completed" || status === "partial" || status === "failed") {
        clearInterval(timer);

        if (status === "completed") {
          setStatus(
            `저장 완료 (${progress.total_pages}페이지)`,
            "success",
          );
        } else if (status === "partial") {
          setStatus(
            `일부 완료 — ${progress.saved_pages}개 성공, ${progress.failed_pages}개 실패`,
            "warning",
          );
        } else {
          const errMsg = data.error_message ? `: ${data.error_message}` : "";
          setStatus(`저장 실패${errMsg}`, "error");
        }

        btnSave.disabled = false;
        resolve(data);
      }
    }, 1000);
  });
}

// ---------------------------------------------------------------------------
// 저장
// ---------------------------------------------------------------------------

btnSave.addEventListener("click", async () => {
  if (activeTabId === null) return;
  btnSave.disabled = true;
  setStatus("저장 요청 중…", "running");

  let resp;
  try {
    resp = await chrome.runtime.sendMessage({ type: "save_request", tab_id: activeTabId });
  } catch (e) {
    console.debug("[AruArchive] save_request 전송 실패:", e);
    setStatus(
      "오류: " + errorToKorean("native_host_disconnected"),
      "error",
    );
    btnSave.disabled = false;
    return;
  }

  if (!resp?.ok) {
    setStatus(`오류: ${errorToKorean(resp?.error)}`, "error");
    btnSave.disabled = false;
    return;
  }

  const jobId    = resp.job_id;
  const shortJob = jobId ? jobId.slice(0, 8) : "?";
  setStatus(`저장 중… (job: ${shortJob}…)`, "running");

  if (jobId) {
    await pollJobStatus(jobId);
  } else {
    setStatus("저장 요청됨", "success");
    btnSave.disabled = false;
  }
});

// ---------------------------------------------------------------------------
// 연결 테스트
// ---------------------------------------------------------------------------

btnPing.addEventListener("click", async () => {
  btnPing.disabled = true;
  const prev = statusMsg.textContent;
  setStatus("연결 테스트 중…", "running");

  let resp;
  try {
    resp = await chrome.runtime.sendMessage({ type: "ping_request" });
  } catch (e) {
    console.debug("[AruArchive] ping_request 전송 실패:", e);
    setStatus("연결 실패: 백그라운드 응답 없음", "error");
    btnPing.disabled = false;
    return;
  }

  if (resp?.ok) {
    setStatus("연결 성공 ✓", "success");
  } else {
    setStatus(`연결 실패: ${errorToKorean(resp?.error)}`, "error");
  }

  btnPing.disabled = false;
  setTimeout(() => { setStatus(prev); }, 2000);
});

// ---------------------------------------------------------------------------
// 오류 한국어 변환
// ---------------------------------------------------------------------------

function errorToKorean(error) {
  const MAP = {
    not_artwork_page:           "작품 페이지가 아닙니다",
    no_dom_data:                "페이지 데이터를 찾을 수 없습니다",
    content_script_unavailable: "페이지를 새로고침 후 다시 시도하세요",
    native_host_disconnected:   "Aru Archive 앱이 실행 중인지 확인하세요",
    native_error:               "Native Host 오류 — 앱 로그를 확인하세요",
  };
  return MAP[error] ?? error ?? "알 수 없는 오류";
}
