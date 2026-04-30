// Aru Source Captioner — content script
//
// Phase 2B: 실 구현.
// - 사용자가 input[type=file]에서 이미지를 선택하면 exifr로 EXIF/XMP/IPTC/UserComment를 파싱.
// - 메타데이터에서 우선순위 6단계로 출처 URL을 추출.
// - 루리웹 글쓰기 에디터가 <p><img alt="..."> 형태로 이미지를 삽입하면 MutationObserver가 감지.
// - File.name === img.alt(또는 img.title) 매칭 (FIFO).
// - 안전한 URL이면 부모 <p> 바로 다음에 출처 캡션 <p>를 DOM API로 삽입.
//
// Phase 1 정책(16개 + DOM 관찰 8항)은 docs/phase1-design.md 단일 출처를 따른다.
//
// 절대 규칙:
//   - innerHTML / outerHTML / insertAdjacentHTML 사용 금지.
//   - eval / new Function 사용 금지.
//   - "출처 없음" placeholder 절대 삽입 금지.
//   - 페이지 상단의 출처 입력란은 절대 건드리지 않는다.
//   - File.name === img.alt(또는 img.title) 정확 비교만 사용 (img.src는 매칭에 사용하지 않는다).
//   - URL이 없거나 unsafe면 본문에 아무것도 삽입하지 않는다.

(function bootstrap() {
  "use strict";

  const DEFAULT_OPTIONS = Object.freeze({
    enabled: true,
    allowHttp: false,
    strictAllowlist: false,
    allowedHosts: ["pixiv.net", "x.com", "twitter.com"]
  });

  const URL_PATTERN = /https?:\/\/[^\s"'<>]+/g;

  const TEXT_FIELDS_FOR_JSON = [
    "UserComment", "userComment", "Comment",
    "Description", "ImageDescription"
  ];

  const EDITOR_ROOT_SELECTORS = [
    '[contenteditable="true"]',
    '.cke_editable',
    '.fr-element',
    '.editor'
  ];

  const BOOT_OBSERVER_TIMEOUT_MS = 60000;
  const WALK_MAX_DEPTH = 10;

  // 사용자가 이번 세션에서 첨부한 파일들의 메타데이터 추출 결과.
  // 같은 파일명이 여러 번 첨부되면 FIFO로 소비.
  const pendingByFileName = new Map();

  // ---------------- 옵션 로드 (Phase 2A 재사용) ----------------

  function loadConfig() {
    return new Promise((resolve) => {
      chrome.storage.sync.get(null, (items) => {
        if (chrome.runtime.lastError) {
          console.warn(
            "[Aru Source Captioner] storage.get failed, falling back to defaults:",
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

  // ---------------- 파일 입력 감지 ----------------

  function attachFileInputListeners(config) {
    document.addEventListener("change", async (ev) => {
      const target = ev.target;
      if (!(target instanceof HTMLInputElement)) return;
      if (target.type !== "file") return;
      if (!target.files || target.files.length === 0) return;

      const images = Array.from(target.files).filter((f) =>
        f && typeof f.type === "string" && f.type.startsWith("image/")
      );
      if (images.length === 0) return;

      // config는 parse 시점에는 사용하지 않는다. raw URL을 record에 저장하고
      // insert 시점(insertCaptionIfNeeded)에서 sanitizeSourceUrl(rawUrl, config)로 검증한다.
      await handleSelectedImageFiles(images);
    }, true);
  }

  async function handleSelectedImageFiles(files) {
    for (const file of files) {
      let sourceInfo;
      try {
        sourceInfo = await parseSourceFromFile(file);
      } catch (err) {
        console.debug("[Aru Source Captioner] parse failed for", file.name, err);
        sourceInfo = { status: "error", url: null, reason: "parse_threw" };
      }
      addPendingRecord(file, sourceInfo);
    }
  }

  function addPendingRecord(file, sourceInfo) {
    const fileName = file.name;
    const record = {
      fileName,
      fileSize: file.size,
      lastModified: file.lastModified,
      sourceInfo,
      consumed: false,
      createdAt: Date.now()
    };
    let arr = pendingByFileName.get(fileName);
    if (!arr) {
      arr = [];
      pendingByFileName.set(fileName, arr);
    }
    arr.push(record);
  }

  function consumePendingRecordByFileName(fileName) {
    if (typeof fileName !== "string" || fileName.length === 0) return null;
    const arr = pendingByFileName.get(fileName);
    if (!arr) return null;
    for (const record of arr) {
      if (!record.consumed) {
        record.consumed = true;
        return record;
      }
    }
    return null;
  }

  // ---------------- 메타데이터 파싱 ----------------

  async function parseSourceFromFile(file) {
    if (typeof exifr === "undefined" || !exifr || typeof exifr.parse !== "function") {
      return { status: "error", url: null, reason: "exifr_unavailable" };
    }

    let metadata;
    try {
      metadata = await exifr.parse(file, {
        xmp: true,
        exif: true,
        iptc: true,
        userComment: true
      });
    } catch (err) {
      console.debug("[Aru Source Captioner] exifr.parse threw for", file.name, err);
      return { status: "error", url: null, reason: "metadata_parse_failed" };
    }

    if (!metadata || typeof metadata !== "object") {
      return { status: "missing", url: null, reason: "no_metadata" };
    }

    const candidates = extractSourceUrl(metadata);
    if (candidates.length === 0) {
      return { status: "missing", url: null, reason: "no_url_candidates" };
    }

    return { status: "ok", url: candidates[0], reason: "ok" };
  }

  function extractSourceUrl(metadata) {
    if (!metadata || typeof metadata !== "object") return [];
    const candidates = [];

    // 우선순위 1·2·3: AruArchive JSON
    collectFromPossibleAruJson(metadata, candidates);

    // 우선순위 4: XMP Source / source
    pushIfString(candidates, metadata.Source);
    pushIfString(candidates, metadata.source);

    // 우선순위 5: XMP Identifier / identifier
    pushIfStringOrArray(candidates, metadata.Identifier);
    pushIfStringOrArray(candidates, metadata.identifier);

    // 우선순위 6: 텍스트 필드를 raw URL로 직접 사용
    collectUrlCandidates(metadata, candidates);

    // 우선순위 7: 모든 문자열 필드에서 https?:// 패턴 fallback
    walkStringFields(metadata, candidates, 0);

    return uniqueOrdered(candidates);
  }

  function collectFromPossibleAruJson(metadata, candidates) {
    for (const field of TEXT_FIELDS_FOR_JSON) {
      const v = metadata[field];
      if (typeof v !== "string") continue;
      const obj = safeJsonParse(v);
      if (!obj || typeof obj !== "object") continue;
      pushIfString(candidates, obj.artwork_url);
      pushIfString(candidates, obj.source_url);
      pushIfString(candidates, obj.artworkUrl);
    }
  }

  function collectUrlCandidates(metadata, candidates) {
    for (const field of TEXT_FIELDS_FOR_JSON) {
      const v = metadata[field];
      if (typeof v !== "string") continue;
      const trimmed = v.trim();
      if (/^https?:\/\//.test(trimmed)) {
        candidates.push(trimmed);
      }
    }
  }

  function walkStringFields(value, candidates, depth) {
    if (depth > WALK_MAX_DEPTH) return;
    if (typeof value === "string") {
      const matches = value.match(URL_PATTERN);
      if (matches) {
        for (const m of matches) {
          candidates.push(m);
        }
      }
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        walkStringFields(item, candidates, depth + 1);
      }
      return;
    }
    if (value && typeof value === "object") {
      for (const k of Object.keys(value)) {
        walkStringFields(value[k], candidates, depth + 1);
      }
    }
  }

  function safeJsonParse(text) {
    if (typeof text !== "string") return null;
    const trimmed = text.trim();
    if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return null;
    try {
      return JSON.parse(trimmed);
    } catch {
      return null;
    }
  }

  function pushIfString(arr, v) {
    if (typeof v === "string") {
      const t = v.trim();
      if (t.length > 0) arr.push(t);
    }
  }

  function pushIfStringOrArray(arr, v) {
    if (typeof v === "string") {
      pushIfString(arr, v);
      return;
    }
    if (Array.isArray(v)) {
      for (const item of v) {
        if (typeof item === "string") pushIfString(arr, item);
      }
    }
  }

  function uniqueOrdered(arr) {
    const seen = new Set();
    const out = [];
    for (const item of arr) {
      if (!seen.has(item)) {
        seen.add(item);
        out.push(item);
      }
    }
    return out;
  }

  // ---------------- URL 보안 검증 ----------------

  function sanitizeSourceUrl(rawUrl, config) {
    if (typeof rawUrl !== "string") return null;
    const trimmed = rawUrl.trim();
    if (trimmed.length === 0) return null;

    let parsed;
    try {
      parsed = new URL(trimmed);
    } catch {
      return null;
    }

    const protocol = parsed.protocol;
    if (protocol === "https:") {
      // 통과
    } else if (protocol === "http:") {
      if (!config.allowHttp) return null;
    } else {
      // javascript: / data: / vbscript: / file: / chrome: / chrome-extension: / about: 등 모두 차단
      return null;
    }

    if (config.strictAllowlist) {
      if (!isAllowedByPolicy(parsed.hostname, config)) return null;
    }

    return parsed.toString();
  }

  function isAllowedByPolicy(hostname, config) {
    if (typeof hostname !== "string" || hostname.length === 0) return false;
    if (!Array.isArray(config.allowedHosts)) return false;
    const h = hostname.toLowerCase();
    for (const allowed of config.allowedHosts) {
      if (typeof allowed !== "string") continue;
      const a = allowed.trim().toLowerCase();
      if (a.length === 0) continue;
      if (h === a) return true;
      if (h.endsWith("." + a)) return true;
    }
    return false;
  }

  // ---------------- DOM 감시 ----------------

  function findEditorRoot() {
    for (const sel of EDITOR_ROOT_SELECTORS) {
      const el = document.querySelector(sel);
      if (el instanceof HTMLElement) return el;
    }
    return null;
  }

  function startEditorObserver(config) {
    let root = findEditorRoot();
    if (root) {
      return attachMainObserver(root, config);
    }

    // 에디터가 동적으로 추가되는 경우 — body 임시 감시 후 발견 시 본격 observer로 전환
    const bootObs = new MutationObserver(() => {
      const candidate = findEditorRoot();
      if (candidate) {
        bootObs.disconnect();
        attachMainObserver(candidate, config);
      }
    });
    bootObs.observe(document.body, { childList: true, subtree: true });

    setTimeout(() => {
      // 시간 내 못 찾으면 boot observer 정리. 본격 observer는 attach 안 됨.
      // disconnect는 멱등하고 throw하지 않으므로 try/catch 없이 호출한다.
      bootObs.disconnect();
    }, BOOT_OBSERVER_TIMEOUT_MS);

    return null;
  }

  function attachMainObserver(root, config) {
    const obs = new MutationObserver((mutations) => {
      for (const mut of mutations) {
        if (mut.type !== "childList") continue;
        for (const node of mut.addedNodes) {
          handleAddedNode(node, config);
        }
      }
    });
    obs.observe(root, { childList: true, subtree: true });
    return obs;
  }

  function handleAddedNode(node, config) {
    if (!(node instanceof HTMLElement)) return;
    if (node instanceof HTMLImageElement) {
      insertCaptionIfNeeded(node, config);
      return;
    }
    if (typeof node.querySelectorAll === "function") {
      const imgs = node.querySelectorAll("img");
      for (const img of imgs) {
        insertCaptionIfNeeded(img, config);
      }
    }
  }

  // ---------------- 캡션 삽입 ----------------

  function insertCaptionIfNeeded(img, config) {
    if (!(img instanceof HTMLImageElement)) return false;
    if (img.dataset.aruSourceCaptioned === "1") return false;

    if (hasExistingSourceCaption(img)) {
      // 사용자가 이미 직접 작성한 출처 캡션이 있으면 마커만 찍고 skip.
      img.dataset.aruSourceCaptioned = "1";
      return false;
    }

    const fileName = img.alt || img.title;
    if (typeof fileName !== "string" || fileName.length === 0) return false;

    const record = consumePendingRecordByFileName(fileName);
    if (!record) return false;
    if (!record.sourceInfo || record.sourceInfo.status !== "ok") return false;

    const safeUrl = sanitizeSourceUrl(record.sourceInfo.url, config);
    if (!safeUrl) return false;

    const caption = createSourceCaption(safeUrl);
    const anchor = findImageParagraph(img);

    try {
      anchor.after(caption);
    } catch (err) {
      console.debug("[Aru Source Captioner] insert failed:", err);
      return false;
    }

    img.dataset.aruSourceCaptioned = "1";
    return true;
  }

  function findImageParagraph(img) {
    const p = img.closest("p");
    return p || img;
  }

  function hasExistingSourceCaption(img) {
    const anchor = findImageParagraph(img);
    const next = anchor.nextElementSibling;
    if (!next) return false;
    if (next instanceof HTMLElement && next.dataset?.aruSourceCaption === "1") {
      return true;
    }
    const text = (next.textContent || "").trim();
    if (text.startsWith("출처:")) {
      const a = next.querySelector?.("a[href]");
      if (a) return true;
    }
    return false;
  }

  function createSourceCaption(url) {
    const p = document.createElement("p");
    p.className = "aru-source-caption";
    p.style.textAlign = "center";
    p.dataset.aruSourceCaption = "1";

    p.appendChild(document.createTextNode("출처: "));

    const a = document.createElement("a");
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = url;

    p.appendChild(a);
    return p;
  }

  // ---------------- 부트스트랩 ----------------

  async function init() {
    const config = await loadConfig();

    if (!config.enabled) {
      console.info("[Aru Source Captioner] disabled — skipping content script");
      return;
    }

    if (typeof exifr === "undefined") {
      console.warn("[Aru Source Captioner] exifr not loaded — caption insertion disabled");
      return;
    }

    attachFileInputListeners(config);
    startEditorObserver(config);

    console.info(
      "[Aru Source Captioner] phase 2B active — caption insertion enabled",
      { strictAllowlist: config.strictAllowlist, allowHttp: config.allowHttp }
    );
  }

  // TODO(phase2C): chrome.storage.onChanged 리스너로 옵션 변경을 즉시 반영한다.
  //   현 Phase 2B에서는 옵션 변경 후 페이지 새로고침이 필요하다.

  init().catch((err) => {
    console.warn("[Aru Source Captioner] init failed:", err);
  });
})();
