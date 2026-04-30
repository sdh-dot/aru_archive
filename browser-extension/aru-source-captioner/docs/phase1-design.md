# Phase 1 설계 — Aru Source Captioner

본 문서는 Aru Source Captioner의 Phase 1(구조 + 문서 + MV3 skeleton) 단계에서 확정된 정책과 매칭 알고리즘을 정의합니다. 실제 구현은 Phase 2 이후 진행되며, 본 문서는 그 시점의 작업 기준이 됩니다.

## 1. 범위

| Phase 1 포함 | Phase 1 제외 |
|---|---|
| MV3 manifest 골격 | EXIF/XMP 파싱 라이브러리 도입 |
| `content.js` / `background.js` / `options.html` / `options.js` 자리 | 실제 캡션 삽입 동작 |
| 16개 정책의 명문화 | popup UI |
| 8개 DOM 관찰 사실 기록 | 단위 테스트 프레임워크 |
| 권한 사유 / 비요청 권한 문서 | 빌드 도구(`package.json` 등) |
| 향후 `lib/` 모듈 분할 계획 | Native Messaging |
| 신규 에이전트 도입 후보 기록 | icons / `dist/` |

## 2. 핵심 시나리오

1. 사용자가 루리웹 유게 잡담 게시판의 글쓰기 페이지에 진입한다.
2. 사용자가 본문 에디터에 이미지를 업로드한다 (단일 또는 다중).
3. 루리웹은 이미지를 CDN으로 변환해 `<p><img src="..." alt="원본파일명.jpg"></p>` 형태로 삽입한다.
4. 확장은 사용자가 첨부한 원본 `File` 객체를 추적해 두고, DOM에 새 `<img>`가 생기면 `File.name === img.alt`로 매칭한다.
5. 매칭된 `File`에서 EXIF/XMP를 읽어 출처 URL을 추출한다.
6. URL이 안전(https + scheme/host 정책 통과)이면 이미지가 들어있는 부모 `<p>` 바로 다음에 출처 `<p>`를 삽입한다.
7. URL이 없거나 안전하지 않으면 아무것도 하지 않는다.

## 3. 정책 (16항)

본 정책은 Phase 2 구현의 절대 기준입니다. 변경이 필요하면 본 문서를 먼저 갱신한 뒤 코드를 수정합니다.

### 3.1 파일 매칭

1. **매칭 키**: `File.name === img.alt`로 정확 일치 비교.
2. `img.src`는 루리웹 CDN WebP URL로 변환되므로 매칭에 사용하지 않는다.
3. 같은 파일명 record가 여러 개 있으면 차단하지 않고 **FIFO**로 하나씩 소비한다 (정책 15와 함께).

### 3.2 캡션 삽입 위치

4. 캡션은 이미지가 들어있는 **부모 `<p>` 바로 다음 형제**로 삽입한다 (정책 3).
5. 페이지 상단의 출처 입력란(루리웹 자체 필드)은 **절대 건드리지 않는다** (정책 8).

### 3.3 캡션 형식

6. 캡션 형식은 다음과 같다 (정책 4):

   ```html
   <p style="text-align: center;">출처: <a href="..." target="_blank" rel="noopener noreferrer">...</a></p>
   ```

7. **`innerHTML` 사용 금지** (정책 9). `document.createElement`, `setAttribute`, `appendChild`, `textContent`만 사용한다. `outerHTML`, `insertAdjacentHTML`도 금지한다.

### 3.4 안전 정책

8. 안전한 출처 URL이 있는 경우에만 캡션을 삽입한다 (정책 5).
9. 메타데이터가 없거나 URL이 없으면 **아무것도 삽입하지 않는다** (정책 6).
10. "출처 없음" placeholder 문구는 **절대 삽입하지 않는다** (정책 7).

### 3.5 URL 검증

11. URL 파싱은 `new URL(rawUrl)`로 수행한다 (정책 10). throw하면 안전하지 않은 것으로 간주한다.
12. 기본은 **https만 허용**한다 (정책 11).
13. `http`는 옵션 `allowHttp`이 true일 때만 허용 — 기본값 false (정책 12).
14. 다음 스킴은 **항상 차단**한다 (정책 13):
    - `javascript:`
    - `data:`
    - `vbscript:`
    - `file:`
    - `chrome:`
    - `chrome-extension:`
    - `about:`
    - 그 외 `http` / `https`가 아닌 모든 스킴

### 3.6 allowlist 정책 (정책 14)

15. 옵션 키와 기본값:

    | 키 | 타입 | 기본값 |
    |---|---|---|
    | `strictAllowlist` | boolean | `false` |
    | `allowHttp` | boolean | `false` |
    | `allowedHosts` | string[] | `["pixiv.net", "x.com", "twitter.com"]` |

16. `strictAllowlist`가 true이면 `URL.hostname`이 `allowedHosts`의 항목과 일치하거나 그 서브도메인일 때만 통과시킨다.
17. `strictAllowlist`가 false이면 scheme 검증만 통과해도 캡션을 삽입한다.

### 3.7 멱등성 / 중복 방지 (정책 16)

18. 중복 캡션 방지는 **파일명이 아니라 DOM 기준**으로 수행한다.
19. 다음 중 하나라도 참이면 해당 이미지는 skip한다.
    - 이미지가 captioned 마커(예: `data-aru-source-caption="1"` 속성)를 갖고 있다.
    - 이미지 부모 `<p>`의 다음 형제가 텍스트 `출처:`로 시작하고 그 안에 `a[href]`를 포함한다.

## 4. 매칭 알고리즘 (의사 코드)

```text
on file_input_change(files):
    for each file in files:
        pendingQueue.push({ name: file.name, file: file, addedAt: now() })

on dom_mutation(addedNodes):
    for each img in find_images(addedNodes):
        if img has captioned marker: continue
        if next sibling of img.parentElement starts with "출처:" and contains a[href]:
            mark img as captioned (멱등성)
            continue

        record = pendingQueue.shiftFirstWhere(name === img.alt)
        if record is null: continue   # 매칭 실패는 무시 (사용자 직접 입력일 수 있음)

        metadata = await extractExifXmp(record.file)
        url = pickSourceUrl(metadata)
        if url is null: continue

        if not isSafeUrl(url, options): continue

        captionNode = buildCaptionNode(url)
        img.parentElement.insertAdjacentElement("afterend", captionNode)
        markCaptioned(img)
```

`isSafeUrl(url, options)`:

```text
try:
    parsed = new URL(url)
catch:
    return false

if parsed.protocol not in ("https:", "http:"):
    return false
if parsed.protocol === "http:" and not options.allowHttp:
    return false
if options.strictAllowlist:
    if not hostMatches(parsed.hostname, options.allowedHosts):
        return false
return true
```

`hostMatches(hostname, allowedHosts)`:

```text
for each allowed in allowedHosts:
    if hostname === allowed: return true
    if hostname endsWith ("." + allowed): return true
return false
```

`buildCaptionNode(url)` — DOM API만 사용:

```text
p = document.createElement("p")
p.setAttribute("style", "text-align: center;")
p.appendChild(document.createTextNode("출처: "))

a = document.createElement("a")
a.setAttribute("href", url)
a.setAttribute("target", "_blank")
a.setAttribute("rel", "noopener noreferrer")
a.textContent = url

p.appendChild(a)
return p
```

## 5. DOM API 사용 원칙

- `document.createElement`, `setAttribute`, `appendChild`, `textContent`, `insertAdjacentElement` 만 사용.
- `innerHTML`, `outerHTML`, `insertAdjacentHTML` 사용 금지.
- 인라인 이벤트 핸들러(예: `onclick="..."`) 사용 금지.
- 외부 스크립트 로드 금지 (MV3 기본 CSP 준수).
- `eval`, `Function()` 사용 금지.

## 6. 매칭 실패 / 메타데이터 없음 처리

| 상황 | 처리 |
|---|---|
| `pendingQueue`에서 동명 record를 찾지 못함 | 캡션 삽입 안 함. 로그 안 남김 (사용자 직접 입력 이미지일 수 있음) |
| EXIF/XMP에 출처 URL 키가 없음 | 캡션 삽입 안 함 (정책 6) |
| 출처 URL이 빈 문자열 | 캡션 삽입 안 함 |
| `new URL()` throw | 캡션 삽입 안 함 (정책 10) |
| scheme 차단 | 캡션 삽입 안 함 (정책 13) |
| `strictAllowlist`이고 host 불일치 | 캡션 삽입 안 함 (정책 14) |

> 어떤 경우에도 "출처 없음" 같은 placeholder를 넣지 않습니다 (정책 7).

## 7. Phase 1 구현 골격 매핑

| 정책 | 자리 (skeleton) |
|---|---|
| 정책 1 ~ 3, 15 | `content.js` — `pendingQueue` (Phase 2에서 `lib/file_alt_matcher.js`로 분할 후보) |
| 정책 4, 16, 18, 19 | `content.js` — caption 노드 빌드와 중복 검사 (Phase 2에서 `lib/caption_renderer.js`로 분할 후보) |
| 정책 5 ~ 7, 9 | `content.js` — early-return 분기 |
| 정책 8 | `content.js` — selector 화이트리스트로 글쓰기 본문 영역만 관찰 |
| 정책 9 | 코드 리뷰 + QA grep 검사 (`innerHTML`, `outerHTML`, `insertAdjacentHTML` 0건) |
| 정책 10 ~ 14 | `lib/url_validator.js` (Phase 2 분할 후보) |
| 정책 14 옵션 | `options.html` + `options.js` + `chrome.storage.sync` |

## 8. Phase 1에서 결정 보류한 항목

| 항목 | 보류 사유 | 다음 결정 시점 |
|---|---|---|
| 글쓰기 페이지 정확 selector | 실제 페이지에서 확인 필요 | Phase 2 진입 시 |
| EXIF 파서 라이브러리 (예: exifr) | 의존성 도입 정책 미정 | Phase 2 진입 시 |
| 빌드 도구 (vanilla / esbuild / 기타) | 모듈 분할 시점에 결정 | Phase 2 진입 시 |
| `*.aru.json` sidecar 지원 | EXIF/XMP만으로 충분한지 사용 후 판단 | Phase 3 후보 |
| icons 디자인 | UI 결정 단계에서 처리 | Phase 2 / 3 |
| 라이선스 | 데스크톱 앱과 동일 vs 별도 | 첫 배포 전 |
| `background.service_worker.type` (`module` 등) | ESM 도입 시점에 함께 결정 | Phase 2 진입 시 |
| `pytest.ini` / `.gitignore` 보강 | QA 단계에서 후속 작업으로 처리 | Phase 1 QA 보고 후 |

## 9. 신규 에이전트 도입 후보 (BROWSER-EXT-DEV)

본 확장 작업이 진행되면서, 기존 6개 에이전트(Orchestrator / UI-DEV / CORE-DEV / TAG-DEV / QA-TEST / GIT-RELEASE)는 모두 PyQt6 데스크톱 도메인에 집중되어 있어, JS / MV3 도메인의 전담 에이전트가 별도로 필요해질 수 있습니다.

> **현재 단계(Phase 1)에서는 에이전트 정의 파일을 생성하지 않습니다.** 본 절은 도입 결정의 근거로만 보존됩니다.

### 도입 후보 사양: `BROWSER-EXT-DEV`

| 필드 | 값 |
|---|---|
| 이름 | `BROWSER-EXT-DEV` |
| 미션 | `browser-extension/**` 하위 MV3 확장 (manifest, content script, options, background) 전담 |
| Scope | `browser-extension/**` 한정. `extension/`(기존 Pixiv Saver), `core/`, `app/`, `db/`, `tests/`, `native_host/` 미접촉 |
| Tools | Edit, Write, Read, Glob, Grep, Bash |
| Must Do | manifest 권한 최소화 / CSP 호환(innerHTML 금지·인라인 핸들러 금지) / `new URL()` 검증 / scheme allowlist / DOM API만 사용 |
| Must Not Do | `eval` / `Function()` 사용 / 허용 호스트 외 접근 / 사용자 동의 없이 Native Messaging 도입 / 기존 `extension/` 수정 / npm 의존성 임의 추가 |
| Handoff | Orchestrator → BROWSER-EXT-DEV → QA-TEST → GIT-RELEASE |

### 도입 시점 권고

- Phase 1 (현재): **도입하지 않음.** Orchestrator가 직접 위임하거나 사용자가 수동 진행.
- Phase 2 (실제 구현 시작): **도입 권고.** 실제 코드 작성과 `lib/` 분할이 시작되는 시점부터 전담 에이전트가 일관성을 확보.
- 사용자 승인 시 `.claude/agents/BROWSER-EXT-DEV.md` 생성. 그 전까지는 본 문서가 사양의 단일 출처입니다.
