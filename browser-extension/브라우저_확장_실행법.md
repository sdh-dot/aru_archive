# browser-extension/

Aru Archive 프로젝트의 브라우저 확장 프로그램들을 모아두는 부모 디렉터리입니다.

## 정책

- 신규 브라우저 확장은 이 디렉터리 하위에 `<확장-이름>/` 형태로 추가합니다.
- 기존 [`extension/`](../extension/) (Aru Archive Pixiv Saver)는 이 디렉터리에 포함되어 있지 않으며, 본 디렉터리 도입과 무관하게 그대로 유지됩니다.
- `extension/` → `browser-extension/aru-pixiv-saver/`로의 이관은 Native Messaging Host manifest와 사용자 설치 경로 영향이 있으므로 **별도 작업**으로 분리합니다. 본 디렉터리 도입 PR에서는 다루지 않습니다.

## 현재 포함된 확장

| 디렉터리 | 설명 | 상태 |
|---|---|---|
| [`aru-source-captioner/`](aru-source-captioner/) | 루리웹 글쓰기 페이지에 이미지 출처 캡션을 자동 삽입 | Phase 1 (skeleton + docs) |

## 명명 규칙

- 디렉터리 이름은 kebab-case (`aru-source-captioner`).
- 확장 이름(`manifest.json`의 `name`)은 사용자 친화적인 표기 ("Aru Source Captioner").
- 데스크톱 앱과 명시적으로 분리된 버전 번호를 사용합니다 (예: 데스크톱 `0.4.x` ↔ 확장 `0.1.x`).

## 데스크톱 앱과의 관계

브라우저 확장은 PyQt6 데스크톱 앱(`app/`, `core/`, `db/`)과 독립적으로 빌드·배포됩니다. 데스크톱 앱과의 통신이 필요할 경우에만 [`native_host/`](../native_host/)의 Native Messaging 프로토콜을 사용합니다. Phase 1의 Aru Source Captioner는 Native Messaging을 사용하지 않습니다.

## 빌드·테스트 도구

본 디렉터리 하위 확장은 자체 `package.json` / 테스트 프레임워크를 가질 수 있습니다. 데스크톱 앱의 `pytest` 수집과 충돌하지 않도록 다음을 권장합니다.

- 확장 디렉터리 내부에 한해 `node_modules/`, `dist/`, `*.zip`, `*.crx`를 두며 루트 `.gitignore` 또는 확장별 `.gitignore`에 등록.
- 루트 `pytest.ini`의 수집 범위에서 `browser-extension/`을 제외 (필요 시 후속 task로 적용).
