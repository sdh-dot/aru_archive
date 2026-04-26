# Aru Archive Architecture

이 문서는 GitHub에서 코드를 처음 보는 사람이 기능별 책임과 데이터 흐름을 빠르게 잡을 수 있도록 유지하는 짧은 개발자 메모입니다.

## 실행 흐름

```text
main.py
  -> config_manager.load_config()
  -> PyQt6 MainWindow 또는 headless AppHttpServer
  -> db.database.initialize_database()
```

- GUI 모드는 `app/main_window.py`가 중심입니다. 툴바 액션, 갤러리/상세 패널 갱신, 백그라운드 스레드 시작을 조율합니다.
- 헤드리스 모드는 `app/http_server.py`를 실행해 브라우저 확장 또는 외부 도구와 통신할 수 있는 로컬 IPC 서버를 띄웁니다.

## 기능별 책임

| 기능 | 주요 파일 | 책임 |
|------|-----------|------|
| 설정 | `core/config_manager.py`, `config.example.json` | Archive Root, DB, 분류 옵션 기본값 관리 |
| DB | `db/schema.sql`, `db/database.py` | artwork/file/tag/copy/undo 테이블 생성과 마이그레이션 기반 |
| Inbox 스캔 | `core/inbox_scanner.py` | 파일 인덱싱, artwork group 생성, 상태 초기화 |
| 메타데이터 모델 | `core/models.py` | 파일 내 AruArchive JSON과 DB row의 Python 표현 |
| 메타데이터 읽기/쓰기 | `core/metadata_reader.py`, `core/metadata_writer.py` | 이미지/사이드카별 AruArchive JSON 보존 |
| Pixiv 보강 | `core/adapters/pixiv.py`, `core/metadata_enricher.py` | Pixiv AJAX 응답을 AruMetadata로 변환하고 DB/파일 갱신 |
| 태그 분류 | `core/tag_classifier.py` | Pixiv 원본 태그를 general/series/character로 정규화 |
| 파일 분류 | `core/classifier.py` | 분류 미리보기 생성, 충돌 처리, 복사 기록/Undo 로그 생성 |
| UI | `app/`, `app/views/`, `app/widgets/` | 사용자가 기능을 실행하고 상태를 확인하는 PyQt6 화면 |

## 메타데이터 보강 흐름

```text
gallery selection
  -> EnrichThread
  -> metadata_enricher.enrich_file_from_pixiv(file_id)
  -> PixivAdapter.fetch_metadata(artwork_id)
  -> PixivAdapter.to_aru_metadata()
  -> tag_classifier.classify_pixiv_tags()
  -> metadata_writer.write_aru_metadata()
  -> artwork_groups / artwork_files / tags 갱신
```

핵심 정책:

- Pixiv 원본 태그는 `tags_json`에 그대로 쌓지 않고, `tag_classifier`를 통해 일반 태그와 시리즈/캐릭터 태그로 분리합니다.
- `series_tags_json`, `character_tags_json`, `tags` 정규화 테이블은 분류 경로와 UI 필터의 기준 데이터입니다.
- 파일 메타데이터 쓰기에 실패하면 `metadata_write_failed`로 표시하고, 파일 내부와 DB의 불일치를 명확히 남깁니다.

## 분류 흐름

```text
selected artwork group
  -> classifier.build_classify_preview()
  -> ClassifyPreviewDialog
  -> ClassifyThread
  -> classifier.execute_classify_preview()
  -> Classified 폴더 복사 + copy_records/undo_entries 기록
```

분류 경로 우선순위:

1. 시리즈와 캐릭터가 모두 있으면 `BySeries/{series}/{character}`.
2. 시리즈만 있으면 `BySeries/{series}/_uncategorized`.
3. 캐릭터만 있으면 `ByCharacter/{character}`.
4. 둘 다 없으면 `ByAuthor/{artist}` fallback.
5. `enable_by_author=true`이면 위 조건과 별개로 작성자 경로를 추가합니다.
6. `enable_by_tag=true`이면 일반 태그 기반 경로도 추가합니다.

`build_classify_preview()`는 파일을 복사하지 않습니다. 실제 복사는 `execute_classify_preview()`만 수행하며, 복사 결과는 Undo를 위해 `copy_records`와 `undo_entries`에 남깁니다.

## 상태값 기준

- 분류 가능: `full`, `json_only`, `xmp_write_failed`
- 분류 제외: `pending`, `metadata_missing`, `metadata_write_failed` 등 실패 계열
- 파일 선택 우선순위: `managed` 파일 우선, 없으면 BMP를 제외한 `original`
- BMP original은 직접 분류하지 않고 PNG managed 생성 후 분류합니다.

## 코멘트 유지 원칙

- 모듈 docstring은 “이 파일의 책임”과 “외부에서 호출하는 핵심 함수”만 설명합니다.
- 함수 내부 주석은 정책 분기, DB 상태 전이, 파일 시스템 부작용처럼 읽는 사람이 실수하기 쉬운 곳에만 둡니다.
- README는 사용법과 큰 지도, 이 문서는 내부 흐름과 정책을 담당합니다.
