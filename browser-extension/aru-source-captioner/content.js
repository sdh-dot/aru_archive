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

  // ---------------- PNG AruArchive iTXt 직접 파서 (D2) ----------------
  //
  // Aru Archive 데스크톱 앱은 PNG에 비표준 iTXt chunk(keyword="AruArchive")로
  // JSON 메타데이터를 저장한다. exifr는 표준 XMP/EXIF만 인식하므로, AruArchive iTXt
  // 안의 artwork_url / source_url / artworkUrl을 별도 파서로 직접 추출한다.
  //
  // 지원 범위:
  //   - PNG signature 8 bytes 검증
  //   - chunk length(big-endian uint32) / type(ASCII 4) / data / crc 순회
  //   - iTXt chunk 중 keyword="AruArchive"
  //   - compression_flag === 0 (uncompressed)만 우선 지원
  //
  // 미지원:
  //   - compression_flag === 1 (zlib-compressed iTXt) — Phase 3 후보
  //   - .aru.json sidecar — 별도 첨부 시에만 가능, 본 파서 범위 외
  //
  // 실패는 missing / error 반환만 — throw 절대 안 함, 항상 exifr fallback에 양보.

  const PNG_SIGNATURE = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
  const ARU_ITXT_KEYWORD = "AruArchive";
  const ARU_PAYLOAD_URL_KEYS = ["artwork_url", "source_url", "artworkUrl"];

  function isPngFile(file) {
    if (!file) return false;
    if (typeof file.type === "string" && file.type === "image/png") return true;
    if (typeof file.name === "string" && /\.png$/i.test(file.name)) return true;
    return false;
  }

  function hasPngSignature(buffer) {
    if (!buffer || buffer.byteLength < 8) return false;
    const sig = new Uint8Array(buffer, 0, 8);
    for (let i = 0; i < PNG_SIGNATURE.length; i++) {
      if (sig[i] !== PNG_SIGNATURE[i]) return false;
    }
    return true;
  }

  function decodeAruPayloadFromItxtText(textBytes) {
    let jsonText;
    try {
      jsonText = new TextDecoder("utf-8", { fatal: false }).decode(textBytes);
    } catch {
      return { status: "error", url: null, reason: "png_itxt_invalid_chunk" };
    }

    let payload;
    try {
      payload = JSON.parse(jsonText);
    } catch {
      return { status: "error", url: null, reason: "png_itxt_json_parse_failed" };
    }

    return extractSourceFromAruArchivePayload(payload);
  }

  async function parseAruArchivePngItxt(file) {
    let buffer;
    try {
      buffer = await file.arrayBuffer();
    } catch {
      return { status: "error", url: null, reason: "arraybuffer_failed" };
    }

    if (!hasPngSignature(buffer)) {
      return { status: "missing", url: null, reason: "png_itxt_invalid_signature" };
    }

    for (const chunkBytes of parsePngItxtChunks(buffer)) {
      const itxt = parseItxtChunk(chunkBytes);
      if (!itxt) continue;
      if (itxt.keyword !== ARU_ITXT_KEYWORD) continue;

      if (itxt.compressionFlag !== 0) {
        return { status: "missing", url: null, reason: "png_itxt_compressed_unsupported" };
      }

      return decodeAruPayloadFromItxtText(itxt.textBytes);
    }

    return { status: "missing", url: null, reason: "png_itxt_missing" };
  }

  function* parsePngItxtChunks(buffer) {
    const view = new DataView(buffer);
    let offset = 8;  // skip PNG signature

    // 각 chunk: length(4 BE) + type(4 ASCII) + data(length bytes) + crc(4) = 12 + length bytes
    while (offset + 12 <= buffer.byteLength) {
      const length = view.getUint32(offset, false);
      if (length > 0x7FFFFFFF) return;  // sanity guard against malformed PNG

      const dataStart = offset + 8;
      const dataEnd = dataStart + length;
      if (dataEnd + 4 > buffer.byteLength) return;  // truncated

      const t0 = view.getUint8(offset + 4);
      const t1 = view.getUint8(offset + 5);
      const t2 = view.getUint8(offset + 6);
      const t3 = view.getUint8(offset + 7);
      const type = String.fromCodePoint(t0, t1, t2, t3);

      if (type === "iTXt" && length > 0) {
        yield new Uint8Array(buffer, dataStart, length);
      }

      if (type === "IEND") return;

      offset = dataEnd + 4;  // skip CRC
    }
  }

  function parseItxtChunk(data) {
    if (!data || data.length < 6) return null;

    // 1. keyword (1-79 bytes Latin-1, null-terminated)
    let kwEnd = -1;
    const maxKw = Math.min(data.length, 80);
    for (let i = 0; i < maxKw; i++) {
      if (data[i] === 0) { kwEnd = i; break; }
    }
    if (kwEnd < 1) return null;

    let keyword;
    try {
      keyword = String.fromCodePoint(...data.subarray(0, kwEnd));
    } catch {
      return null;
    }

    // 2. compression_flag (1 byte) + compression_method (1 byte)
    if (kwEnd + 2 >= data.length) return null;
    const compressionFlag = data[kwEnd + 1];
    const compressionMethod = data[kwEnd + 2];

    // 3. language_tag (variable, null-terminated)
    let langEnd = -1;
    for (let i = kwEnd + 3; i < data.length; i++) {
      if (data[i] === 0) { langEnd = i; break; }
    }
    if (langEnd === -1) return null;

    // 4. translated_keyword (variable, null-terminated)
    let tkwEnd = -1;
    for (let i = langEnd + 1; i < data.length; i++) {
      if (data[i] === 0) { tkwEnd = i; break; }
    }
    if (tkwEnd === -1) return null;

    // 5. text (remainder)
    const textBytes = data.subarray(tkwEnd + 1);

    return { keyword, compressionFlag, compressionMethod, textBytes };
  }

  function extractSourceFromAruArchivePayload(payload) {
    if (!payload || typeof payload !== "object") {
      return { status: "missing", url: null, reason: "png_itxt_no_url" };
    }

    for (const key of ARU_PAYLOAD_URL_KEYS) {
      const v = payload[key];
      if (typeof v === "string" && v.trim().length > 0) {
        return { status: "ok", url: v.trim(), reason: "png_itxt_source_found" };
      }
    }

    return { status: "missing", url: null, reason: "png_itxt_no_url" };
  }

  // ---------------- 메타데이터 파싱 ----------------

  async function parseSourceFromFile(file) {
    // PNG 우선: Aru Archive 데스크톱 앱이 PNG에 비표준 iTXt(keyword="AruArchive")로
    // JSON 메타데이터를 저장하는데, exifr는 이를 인식하지 못한다. PNG 파일이면
    // 직접 파서를 먼저 시도하고, 성공 시 즉시 반환한다. 실패(missing/error)는
    // silent fallback으로 기존 exifr 흐름을 그대로 탄다.
    if (isPngFile(file)) {
      const aruResult = await parseAruArchivePngItxt(file);
      if (aruResult.status === "ok") {
        return aruResult;
      }
      if (aruResult.status === "error") {
        console.debug(
          "[Aru Source Captioner] png itxt fallback to exifr:",
          file.name, aruResult.reason
        );
      }
    }

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

  // ---------------- 페이지 종류 감지 ----------------
  //
  // 글쓰기 페이지(write)와 일반 게시글 조회 페이지(read)는 manifest matches가 모두
  // 매칭되지만 동작이 다르다. URL pathname으로 명확히 분기한다.
  //
  //   write: /community/board/{boardId}/write 등
  //   read:  /community/board/{boardId}/read/{postId}
  //
  // read 페이지에서는 write용 file input / editor observer를 띄우지 않고,
  // 댓글 영역에 "출처 추가" 버튼만 주입한다.

  const READ_PATH_PATTERN = /^\/community\/board\/[^/]+\/read\/[^/?]+/;

  function isReadPage() {
    try {
      return READ_PATH_PATTERN.test(location.pathname);
    } catch {
      return false;
    }
  }

  // 글쓰기 페이지는 별도 selector 검사 없이 isReadPage()의 음수로 정의한다.
  // (manifest matches가 이미 루리웹 게시판으로 좁혀져 있다.)

  // ---------------- 댓글 영역 출처 버튼 (read 페이지) ----------------
  //
  // 댓글 textarea(textarea[name="comment_input"])를 가진 .border_box.after_clear
  // wrapper를 찾아 .common_img_button 바로 다음에 "출처 추가" 버튼을 주입한다.
  //
  // 정책:
  //   - 출처 URL은 현재 read 페이지의 location.href를 사용한다 (게시글 자체가 출처).
  //   - 삽입 텍스트 형식: "출처: {url}\n\n" — 마지막 빈 줄을 두어 사용자가 그 아래
  //     댓글 본문을 바로 이어 작성할 수 있게 한다.
  //   - 빈 textarea: 출처 텍스트만 삽입.
  //   - 기존 내용 있음: existing.trimEnd() + "\n\n" + 출처 텍스트.
  //   - 동일 출처가 이미 있으면 skip (중복 방지).
  //   - 다른 출처 라인("출처: ..." 다른 URL)이 이미 있으면 skip (자동 덮어쓰기 금지).
  //   - textarea.maxLength 초과 시 skip.
  //   - 커서를 마지막 빈 줄에 위치시키고 input/change 이벤트 dispatch.
  //   - 한 wrapper당 한 번만 주입 (data-aru-source-comment-bound guard).
  //   - 기존 onclick / onchange / onkeydown / .common_img_button 이벤트는 절대 손대지 않는다.

  const COMMENT_WRAPPER_SELECTOR = ".border_box.after_clear";
  const COMMENT_TEXTAREA_SELECTOR = 'textarea[name="comment_input"]';
  const COMMENT_IMG_BUTTON_SELECTOR = ".common_img_button";
  const COMMENT_BOUND_DATASET_KEY = "aruSourceCommentBound";
  const COMMENT_BUTTON_CLASS = "aru-source-caption-comment-button";
  const COMMENT_SOURCE_PREFIX = "출처:";

  function findCommentInputWrappers() {
    const wrappers = document.querySelectorAll(COMMENT_WRAPPER_SELECTOR);
    const out = [];
    for (const w of wrappers) {
      if (!(w instanceof HTMLElement)) continue;
      if (!w.querySelector(COMMENT_TEXTAREA_SELECTOR)) continue;
      out.push(w);
    }
    return out;
  }

  function buildCommentSourceText(sourceUrl) {
    return `${COMMENT_SOURCE_PREFIX} ${sourceUrl}\n\n`;
  }

  function logCommentInsertSkip(reason, detail) {
    // 사용자 페이지 콘솔 오염을 피하기 위해 console.debug만 사용한다.
    console.debug("[Aru Source Captioner] comment insert skipped:", reason, detail || "");
  }

  function insertSourceIntoCommentTextarea(textarea, sourceText) {
    if (!(textarea instanceof HTMLTextAreaElement)) return false;

    const existing = typeof textarea.value === "string" ? textarea.value : "";
    const sourceLine = sourceText.split("\n")[0];  // "출처: {url}"

    // 동일 출처 중복 방지.
    if (existing.includes(sourceLine)) {
      try { textarea.focus(); } catch { /* noop */ }
      logCommentInsertSkip("duplicate_source_line");
      return false;
    }

    // 다른 출처가 이미 존재하면 자동 덮어쓰기 금지.
    if (/(^|\n)\s*출처\s*:\s*\S/.test(existing)) {
      try { textarea.focus(); } catch { /* noop */ }
      logCommentInsertSkip("other_source_present");
      return false;
    }

    let newValue;
    if (existing.trim().length === 0) {
      newValue = sourceText;
    } else {
      newValue = existing.replace(/\s+$/u, "") + "\n\n" + sourceText;
    }

    const maxLen = typeof textarea.maxLength === "number" ? textarea.maxLength : -1;
    if (maxLen > 0 && newValue.length > maxLen) {
      logCommentInsertSkip("maxlength_exceeded", { maxLen, newLen: newValue.length });
      return false;
    }

    textarea.value = newValue;

    const cursorPos = newValue.length;
    try {
      textarea.focus();
      textarea.setSelectionRange(cursorPos, cursorPos);
    } catch {
      // 일부 브라우저/상태에서 setSelectionRange가 throw할 수 있다 — 무시.
    }

    // 사이트가 textarea 변화를 감지할 수 있도록 표준 이벤트 dispatch.
    try {
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.dispatchEvent(new Event("change", { bubbles: true }));
    } catch (err) {
      console.debug("[Aru Source Captioner] event dispatch failed:", err);
    }

    return true;
  }

  function handleCommentSourceButtonClick(textarea) {
    if (!(textarea instanceof HTMLTextAreaElement)) return;
    let sourceUrl;
    try {
      sourceUrl = location.href;
    } catch {
      return;
    }
    if (typeof sourceUrl !== "string" || sourceUrl.length === 0) return;

    const sourceText = buildCommentSourceText(sourceUrl);
    insertSourceIntoCommentTextarea(textarea, sourceText);
  }

  function injectCommentSourceButton(wrapper) {
    if (!(wrapper instanceof HTMLElement)) return false;

    const textarea = wrapper.querySelector(COMMENT_TEXTAREA_SELECTOR);
    if (!(textarea instanceof HTMLTextAreaElement)) return false;

    const imgButton = wrapper.querySelector(COMMENT_IMG_BUTTON_SELECTOR);
    if (!(imgButton instanceof HTMLElement)) return false;

    // 이미 동일 wrapper에 주입된 적이 있으면 (DOM 재구성 등) 추가 주입 방지.
    if (wrapper.querySelector("." + COMMENT_BUTTON_CLASS)) return false;

    const button = document.createElement("button");
    button.type = "button";
    button.className = COMMENT_BUTTON_CLASS;
    button.textContent = "출처 추가";
    button.title = "현재 게시글 URL을 댓글에 출처로 추가합니다";
    button.dataset.aruSourceCommentButton = "1";

    button.addEventListener("click", (ev) => {
      // 사이트의 form submit / 다른 핸들러 트리거를 막는다.
      try { ev.preventDefault(); } catch { /* noop */ }
      try { ev.stopPropagation(); } catch { /* noop */ }
      handleCommentSourceButtonClick(textarea);
    });

    try {
      imgButton.insertAdjacentElement("afterend", button);
    } catch (err) {
      console.debug("[Aru Source Captioner] comment button insert failed:", err);
      return false;
    }
    return true;
  }

  function setupCommentSourceCaptioner() {
    if (!isReadPage()) return;
    const wrappers = findCommentInputWrappers();
    for (const wrapper of wrappers) {
      if (wrapper.dataset[COMMENT_BOUND_DATASET_KEY] === "1") continue;
      const ok = injectCommentSourceButton(wrapper);
      if (ok) {
        wrapper.dataset[COMMENT_BOUND_DATASET_KEY] = "1";
      }
    }
  }

  let commentObserver = null;
  let commentObserverScheduled = false;

  function scheduleCommentSetup() {
    if (commentObserverScheduled) return;
    commentObserverScheduled = true;
    // microtask로 모아서 단일 실행 — MutationObserver 폭주 방지.
    Promise.resolve().then(() => {
      commentObserverScheduled = false;
      try {
        setupCommentSourceCaptioner();
      } catch (err) {
        console.debug("[Aru Source Captioner] comment setup failed:", err);
      }
    });
  }

  function startCommentObserver() {
    if (!isReadPage()) return null;
    if (commentObserver) return commentObserver;

    commentObserver = new MutationObserver((mutations) => {
      // 우리가 주입한 버튼 / dataset 변경은 무한 루프 위험이 있으니
      // 단순히 추가 노드 발생 여부만 확인하고 idempotent setup을 schedule한다.
      // dataset.aruSourceCommentBound guard가 중복 주입을 막는다.
      for (const mut of mutations) {
        if (mut.type !== "childList") continue;
        if (mut.addedNodes && mut.addedNodes.length > 0) {
          scheduleCommentSetup();
          return;
        }
      }
    });

    if (document.body) {
      commentObserver.observe(document.body, { childList: true, subtree: true });
    }
    return commentObserver;
  }

  // ---------------- 부트스트랩 ----------------

  async function init() {
    const config = await loadConfig();

    if (!config.enabled) {
      console.info("[Aru Source Captioner] disabled — skipping content script");
      return;
    }

    // 페이지 종류별로 분기:
    //   - read 페이지: 댓글 영역 "출처 추가" 버튼만 주입. 글쓰기용 editor / file input 로직은 띄우지 않는다.
    //   - write 페이지(=non-read): 기존 글쓰기 캡션 자동 삽입 동작 그대로 유지.
    if (isReadPage()) {
      setupCommentSourceCaptioner();
      startCommentObserver();
      console.info(
        "[Aru Source Captioner] read page active — comment source button enabled"
      );
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
