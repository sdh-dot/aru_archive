# lib/

Phase 2A까지 비어 있습니다. **exifr는 아직 도입하지 않았습니다.**

본 디렉터리는 향후 `content.js`에서 분리해 옮길 모듈과, Phase 2B에서 도입될 외부 메타데이터 파서(`exifr`)의 vendor 파일을 모아두는 자리입니다. Phase 2A까지는 모든 로직이 `content.js` 안에 머물러 있으며 (현재는 설정 로드와 `enabled` 체크만), 실제 EXIF/XMP 파싱과 캡션 삽입이 추가되는 Phase 2B 시점에 본 디렉터리에 다음 파일들이 추가됩니다.

- `exifr.<variant>.umd.js` — exifr UMD 번들 (lite/full 중 선정 후 vendoring 권고)
- `exifr.LICENSE` — MIT 라이선스 사본
- 그 외 아래 모듈 후보들 중 분할 가치가 확인되는 것

## 향후 모듈 후보 (Phase 2 이후)

| 모듈 (가칭) | 역할 |
|---|---|
| `exif_reader.js` | `File` 객체로부터 EXIF / XMP 메타데이터를 비동기 추출 |
| `source_url_extractor.js` | 메타데이터에서 출처 URL 후보를 우선순위에 따라 추출 |
| `url_validator.js` | `new URL()` 파서 + scheme allowlist + host allowlist 검증 |
| `caption_renderer.js` | 캡션 `<p>` 노드를 DOM API만으로 생성하고 부모 `<p>` 다음에 삽입 |
| `file_alt_matcher.js` | `File.name ↔ img.alt` FIFO 매칭 큐 |
| `aru_sidecar_reader.js` | (선택) `*.aru.json` sidecar 파서. 사용자가 동시에 첨부한 경우만 사용 |

## 모듈 분할 시 원칙

- 각 모듈은 ESM(`export`)으로 노출합니다.
- DOM API만 사용하며 `innerHTML` / `outerHTML` / `insertAdjacentHTML`은 사용하지 않습니다.
- 외부 패키지(npm 의존성) 도입은 Orchestrator 합의 후에만 수행합니다.
- 단위 테스트가 가능한 순수 함수(side-effect 없음)를 우선합니다.
- 각 모듈은 자체적으로 `chrome.*` API를 호출하지 않습니다 (테스트 용이성). `chrome.*` 호출은 `content.js` / `background.js` / `options.js`에 한정합니다.

## 분할 시점

`content.js`가 다음 조건 중 하나에 해당하면 `lib/` 분할을 진행합니다.

1. 한 파일에 책임이 4개 이상 섞여 있다.
2. 단위 테스트를 도입할 시점이 되었다.
3. 외부 EXIF 파서 라이브러리 도입으로 entry script 길이가 늘어난다.

분할 작업은 별도 task로 위임합니다.
