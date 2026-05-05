# lib/

Phase 2B에서 외부 메타데이터 파서 [exifr](https://github.com/MikeKovarik/exifr)를 vendored 라이브러리로 도입했습니다.

## 도입된 파일

| 파일 | 용도 | 라이선스 |
|---|---|---|
| `exifr.full.umd.js` | EXIF / XMP / IPTC / UserComment 통합 파서 (UMD 빌드) | MIT (lib/exifr.LICENSE 참고) |
| `exifr.LICENSE` | exifr 라이선스 사본 | MIT |

### 도입 메타

- **버전**: `exifr@7.1.3` (latest 미사용, 버전 고정)
- **빌드 변형**: `dist/full.umd.js`
  - 크기: 75,848 bytes
  - 출처: `https://unpkg.com/exifr@7.1.3/dist/full.umd.js`
- **변형 선택 근거**: `exifr.lite.umd.js`도 검토했으나 XMP wrapper(`<?xpacket ...?>`) 본격 파싱 코드가 부재하여, XMP `Source` / `Identifier` 자동 평탄화가 보장되지 않았다. `full` 변형은 RDF/XML 본격 파싱을 포함하므로 정책 4·5(XMP Source/Identifier)의 정확한 동작을 위해 채택.

### 사용 방법

`manifest.json`의 `content_scripts[0].js`에 `lib/exifr.full.umd.js`를 `content.js`보다 먼저 등록한다. UMD 빌드는 `globalThis.exifr`를 노출하므로 `content.js`에서 `await exifr.parse(file, { xmp: true, exif: true, iptc: true, userComment: true })` 형태로 호출한다.

### Phase 2B에서 사용하는 기능

- `exifr.parse(File, options)` — File 객체에서 EXIF / XMP / IPTC / UserComment를 비동기 추출
- 옵션:
  - `xmp: true` — XMP `Source` / `Identifier` 등 평탄화
  - `exif: true` — EXIF UserComment / ImageDescription
  - `iptc: true` — IPTC 보조
  - `userComment: true` — UserComment 디코딩

### CSP 호환성 검증 (도입 시점 — Phase 2B)

| 패턴 | 결과 |
|---|---|
| `eval(` | 0건 |
| `new Function(` | 0건 |
| `Function("` / `Function('` | 0건 |
| MV3 기본 CSP 호환 여부 | ✅ |

### 업데이트 절차

1. 새 버전 결정 — `exifr@<new>` 형식, latest URL 미사용.
2. 다운로드:
   - `curl --fail --location --silent -o lib/exifr.full.umd.js https://unpkg.com/exifr@<new>/dist/full.umd.js`
   - `curl --fail --location --silent -o lib/exifr.LICENSE https://unpkg.com/exifr@<new>/LICENSE`
3. CSP 검증 재실행 (`eval(`, `new Function(`, `Function("`, `Function('` 모두 0건).
4. XMP 흔적 검증 (`xpacket` 또는 `rdf:` 또는 동등 키워드 1+ 건).
5. 이 README의 버전·크기·sha256(선택)을 갱신.
6. 데스크톱 앱과 분리된 라이선스 정책 — 변경 없으면 LICENSE 파일은 그대로.

## 향후 모듈 후보 (Phase 2C 이후)

`content.js`가 다음 조건 중 하나에 해당하면 `lib/`에 ES 모듈로 분리합니다.

| 모듈 (가칭) | 역할 |
|---|---|
| `source_url_extractor.js` | 메타데이터에서 출처 URL 후보를 우선순위 6단계로 추출 |
| `url_validator.js` | `new URL()` 파서 + scheme allowlist + host allowlist 검증 |
| `caption_renderer.js` | 캡션 `<p>` 노드를 DOM API만으로 생성하고 부모 `<p>` 다음에 삽입 |
| `file_alt_matcher.js` | `File.name ↔ img.alt` FIFO 매칭 큐 |
| `aru_sidecar_reader.js` | (선택) `*.aru.json` sidecar 파서. 사용자가 동시에 첨부한 경우만 사용 |

### 분리 시점

`content.js`가 다음 중 하나에 해당하면 `lib/` 분할을 진행합니다.

1. 한 파일에 책임이 4개 이상 명백히 섞여 있다.
2. 단위 테스트 프레임워크를 도입할 시점이 되었다.
3. 외부 EXIF 파서 라이브러리를 추가 도입한다.

## 모듈 분할 시 원칙

- 각 모듈은 ESM(`export`)으로 노출합니다.
- DOM API만 사용하며 `innerHTML` / `outerHTML` / `insertAdjacentHTML`은 사용하지 않습니다.
- 외부 패키지(npm 의존성) 도입은 Orchestrator 합의 후에만 수행합니다.
- 단위 테스트가 가능한 순수 함수(side-effect 없음)를 우선합니다.
- 각 모듈은 자체적으로 `chrome.*` API를 호출하지 않습니다 (테스트 용이성). `chrome.*` 호출은 `content.js` / `background.js` / `options.js`에 한정합니다.
