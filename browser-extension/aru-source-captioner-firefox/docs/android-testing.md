# Aru Source Captioner — Firefox Android 테스트 가이드

## Android 지원 상태

**Experimental** — AMO(addons.mozilla.org)에 Android 공개 전 반드시 실기기 테스트를 완료해야 한다.

## 최소 버전

| 플랫폼 | Firefox 최소 버전 |
|---|---|
| Firefox Desktop | 140.0 |
| Firefox Android | 142.0 |

## 동작 방식

### 자동 출처 삽입 (Auto-insert mode)

이 확장은 **"출처 추가" 버튼 없이** 동작한다. 이미지 파일을 선택하면 자동으로 출처 캡션이 삽입된다.

```
파일 선택 (input[type=file] change 이벤트)
  → 이미지 파일 필터링
  → 메타데이터 추출 (우선순위 순서):
      1. Aru Archive PNG iTXt (artwork_url / source_url / artwork_id)
      2. EXIF/XMP/IPTC (UserComment / Source / Identifier)
      3. Pixiv 파일명 패턴 fallback (88908024_p0_master1200.jpg)
  → source URL 검증 (sanitizeSourceUrl)
  → 출처 캡션 자동 삽입 (editor 또는 comment textarea)
```

### 모바일 환경 판별 (isMobileAutoInsertEnvironment)

```js
navigator.userAgent에 "Android" 포함
  또는 (pointer: coarse) + window.innerWidth < 768px
```

### 데이터 처리 원칙

- 이미지 파일, 메타데이터, 파일명, 캡션 내용은 **외부 서버로 전송하지 않는다.**
- Pixiv API 호출 없음.
- 원격 DB 저장 없음.
- **모든 처리는 브라우저 로컬에서만 수행된다.**

---

## web-ext lint 실행

```bash
npx web-ext lint --source-dir browser-extension/aru-source-captioner-firefox
```

lint 통과 확인 후 AMO 제출 진행.

---

## Android 수동 테스트 체크리스트

### 환경 준비

- [ ] Firefox Android 최신 버전 설치 (최소 142.0)
- [ ] 확장 임시 설치: `about:debugging` → "이 Firefox" → "임시 추가 기능 로드" → `manifest.json` 선택
  - 또는 AMO 개발자 채널을 통해 사전 배포 버전 설치

### 글쓰기 페이지 테스트

1. [ ] 루리웹 모바일 글쓰기 페이지 접속: `https://m.ruliweb.com/community/board/300143/write`
   - 데스크톱 URL `bbs.ruliweb.com` 과 다름 — 모바일은 반드시 `m.ruliweb.com` 사용
2. [ ] Aru Archive로 처리한 PNG 이미지 첨부 (Aru Archive 메타데이터 포함)
3. [ ] 이미지 선택 직후 자동으로 출처 캡션이 에디터에 삽입되는지 확인
4. [ ] Pixiv 파일명 패턴 이미지 첨부 (예: `88908024_p0_master1200.jpg`)
5. [ ] filename fallback으로 출처 URL이 생성되는지 확인
6. [ ] 동일 이미지 재선택 시 중복 삽입이 발생하지 않는지 확인
7. [ ] 출처 없는 이미지 첨부 시 아무것도 삽입되지 않고 조용히 종료되는지 확인

### 댓글 작성 페이지 테스트

8. [ ] 루리웹 모바일 게시글 읽기 페이지 접속: `https://m.ruliweb.com/community/board/.../read/...`
9. [ ] 댓글 이미지 첨부 기능 접근 (`input.common_img_input` 또는 `input[type=file]`)
10. [ ] 이미지 선택 직후 댓글 textarea에 출처 텍스트 자동 삽입 확인
11. [ ] 동일 출처 중복 삽입 방지 확인

### 모바일 UI 확인

12. [ ] 화면 회전 (세로/가로) 후 기능 정상 동작 확인
13. [ ] "출처 추가" 버튼이 기본으로 노출되지 않음 확인
14. [ ] 에디터 selector 미탐지 시 오류 없이 종료 확인 (console warning 정도만)
15. [ ] `about:debugging` 또는 `adb logcat`에서 `[Aru Source Captioner]` 로그 확인

### 실패 시 로그 기반 진단

Firefox Browser Console: `about:debugging → 검사 → Console` 탭

| 관찰 | 원인 | 조치 |
|---|---|---|
| `content script loaded` 로그 **없음** | manifest `content_scripts.matches` 또는 `host_permissions` 누락 | manifest 확인 후 확장 재설치 |
| `content script loaded` 있음, `auto-insert mode active` 없음 | `init()` async 실패 또는 `config.enabled = false` | Console 오류 확인 |
| `auto-insert mode active` 있음, `tryMobileWriteInsert` 없음 | file input change 이벤트 미탐지 | `attachFileInputListeners` 동작 확인 |
| `tryMobileWriteInsert` 있음, `no write area found` 있음 | 에디터 selector 불일치 | `EDITOR_ROOT_SELECTORS` 업데이트 필요 |
| `textarea insert result =` 있음 | 삽입 완료 — 결과값(ok/duplicate 등) 확인 | - |

추가 확인:
- `[Aru Source Captioner] content loaded` (async init 시작)
- `auto-insert mode active` 및 `mobile: true` 여부
- `exifr.parse failed` 이후 `filename_fallback` 경로 진입 여부
- `skipping already-processed file` 로그로 중복 방지 동작 확인

---

## AMO Android 공개 전 확인 사항

1. **web-ext lint 통과** — 경고 없음 또는 허용된 경고만
2. **실기기 테스트 완료** — 위 체크리스트 전 항목 통과
3. **gecko_android.strict_min_version = 142.0** 설정 확인
4. **data_collection_permissions.required = ["none"]** 유지 확인
5. 외부 서버 요청 없음 확인 (Network 탭에서 추가 요청 없음)
6. AMO 심사 노트에 "All processing is local; no data is transmitted" 명시

---

## 관련 파일

| 파일 | 역할 |
|---|---|
| `manifest.json` | Firefox 전용 manifest (gecko + gecko_android) |
| `content.js` | 자동 삽입 로직, isMobileAutoInsertEnvironment, processedFileKeys |
| `background.js` | storage 옵션 기본값 seed |
| `docs/phase1-design.md` | 출처 추출 우선순위 정책 |
