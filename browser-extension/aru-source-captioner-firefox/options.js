// Aru Source Captioner — options page script
//
// Phase 2A: chrome.storage.sync 기반 옵션 로드/저장 구현.
// - DOMContentLoaded 시점에 현재 설정을 폼에 반영.
// - submit 이벤트에서 폼 값을 chrome.storage.sync에 저장.
// - allowedHosts는 줄 단위로 파싱 (공백 trim, 빈 줄 무시).
// - 저장 결과는 textContent로만 표시 (innerHTML 사용 금지).

(function init() {
  "use strict";

  const DEFAULT_OPTIONS = Object.freeze({
    enabled: true,
    allowHttp: false,
    strictAllowlist: false,
    allowedHosts: ["pixiv.net", "x.com", "twitter.com"]
  });

  function parseHostList(text) {
    return text
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
  }

  function renderHostList(hosts) {
    if (!Array.isArray(hosts)) {
      return "";
    }
    return hosts.join("\n");
  }

  function setStatus(text) {
    const el = document.getElementById("save-status");
    if (el) {
      el.textContent = text;
    }
  }

  function loadOptions() {
    return new Promise((resolve) => {
      chrome.storage.sync.get(null, (items) => {
        if (chrome.runtime.lastError) {
          console.warn(
            "[Aru Source Captioner] options load failed, using defaults:",
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

  function saveOptions(options) {
    return new Promise((resolve, reject) => {
      chrome.storage.sync.set(options, () => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        resolve();
      });
    });
  }

  function applyToForm(opts) {
    const enabledEl = document.getElementById("opt-enabled");
    const allowHttpEl = document.getElementById("opt-allow-http");
    const strictEl = document.getElementById("opt-strict-allowlist");
    const hostsEl = document.getElementById("opt-allowed-hosts");

    if (enabledEl) enabledEl.checked = !!opts.enabled;
    if (allowHttpEl) allowHttpEl.checked = !!opts.allowHttp;
    if (strictEl) strictEl.checked = !!opts.strictAllowlist;
    if (hostsEl) hostsEl.value = renderHostList(opts.allowedHosts);
  }

  function readFromForm() {
    return {
      enabled: !!document.getElementById("opt-enabled")?.checked,
      allowHttp: !!document.getElementById("opt-allow-http")?.checked,
      strictAllowlist: !!document.getElementById("opt-strict-allowlist")?.checked,
      allowedHosts: parseHostList(
        document.getElementById("opt-allowed-hosts")?.value ?? ""
      )
    };
  }

  document.addEventListener("DOMContentLoaded", async () => {
    try {
      const opts = await loadOptions();
      applyToForm(opts);
      setStatus("");
    } catch (err) {
      const msg = err?.message || String(err);
      setStatus(`설정을 불러오지 못했습니다: ${msg}`);
    }

    const form = document.getElementById("options-form");
    if (!form) {
      return;
    }

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      setStatus("저장 중…");
      try {
        const next = readFromForm();
        await saveOptions(next);
        setStatus("저장되었습니다.");
      } catch (err) {
        const msg = err?.message || String(err);
        setStatus(`저장에 실패했습니다: ${msg}`);
      }
    });
  });
})();
