# 메타데이터 정책

Aru Archive가 아트워크 파일에 메타데이터를 기록하고 관리하는 규칙입니다.

---

## 1. 메타데이터 레이어 구조

Aru Archive는 두 가지 레이어로 메타데이터를 관리합니다.

| 레이어 | 위치 | 목적 |
|--------|------|------|
| **AruArchive JSON** | JPEG/WebP `UserComment`, PNG `iTXt`, 사이드카 `.aru.json` | 내부 관리·복구·DB 재구성 |
| **XMP** | JPEG/WebP/PNG XMP 블록 (ExifTool 경유) | 외부 툴(Lightroom, Bridge 등) 호환 |

`metadata_sync_status`가 `json_only`인 파일은 AruArchive JSON만 기록된 상태입니다.  
ExifTool이 설정되어 있으면 저장·보강 직후 XMP 기록을 시도하고 `full`로 승격합니다.

---

## 2. metadata_sync_status 목록

DB `artwork_files.metadata_sync_status` 컬럼의 11가지 상태값입니다.

| 상태값 | 의미 |
|--------|------|
| `pending` | 메타데이터 기록 대기 (스캔만 됨) |
| `full` | AruArchive JSON + XMP 모두 기록 완료 |
| `json_only` | AruArchive JSON만 기록됨 (XMP 미기록) |
| `out_of_sync` | DB와 파일 메타데이터 불일치 |
| `file_write_failed` | 파일 쓰기 자체가 실패 |
| `convert_failed` | 포맷 변환(BMP→PNG, GIF→WebP) 실패 |
| `metadata_write_failed` | JSON 임베딩 실패 (파일은 존재) |
| `xmp_write_failed` | XMP 기록 실패 (JSON은 성공) |
| `db_update_failed` | DB 갱신 실패 (파일 쓰기는 성공) |
| `needs_reindex` | 파일 변경 감지 — 재인덱스 필요 |
| `metadata_missing` | 파일 내 메타데이터를 찾을 수 없음 |

### 분류 가능 상태

분류 엔진(`core/classifier.py`)은 다음 상태의 파일만 분류 대상으로 처리합니다.

```
full | json_only | xmp_write_failed
```

---

## 3. 파일 포맷별 정책

### JPEG (`.jpg`, `.jpeg`)

- AruArchive JSON: `UserComment` EXIF 태그 (piexif)
- XMP: ExifTool로 `XMP-dc:*`, `XMP:MetadataDate`, `XMP:Rating`, `XMP:Label` 기록
- 분류 대상: 원본 파일

### PNG

- AruArchive JSON: `iTXt` 청크 (`AruArchive` 키워드)
- XMP: ExifTool로 XMP 표준 필드 기록
- 분류 대상: 원본 파일 (또는 BMP managed PNG)

### WebP

- AruArchive JSON: `UserComment` (piexif 경유)
- XMP: ExifTool로 XMP 표준 필드 기록
- 분류 대상: 원본 파일 (또는 GIF managed WebP)

### BMP, static GIF, ZIP (Ugoira)

XMP 직접 기록 불가 — `json_only` 상태 유지 또는 managed 파일에 기록:

| 포맷 | AruArchive JSON | XMP |
|------|-----------------|-----|
| BMP original | 미지원 (managed PNG에 기록) | managed PNG에 기록 |
| static GIF | `.aru.json` 사이드카 | 불가 (json_only 유지) |
| ZIP (Ugoira) | ZIP comment + `.aru.json` | 불가 (managed WebP에 기록)

---

## 4. BMP 정책

BMP 포맷은 EXIF/XMP를 직접 지원하지 않으므로 **Managed PNG**를 생성합니다.

```
BMP original  →  PNG managed  →  분류 대상
```

| 원칙 | 내용 |
|------|------|
| 원본 보존 | BMP original은 삭제하지 않음 |
| 직접 기록 금지 | BMP 파일에 메타데이터를 직접 기록하지 않음 |
| Managed 생성 | `{artwork_id}_p{n}_managed.png` 파일 생성 |
| 메타데이터 기록 | AruArchive JSON + XMP를 Managed PNG에 기록 |
| 분류 대상 | Managed PNG가 분류·복사의 실제 대상 |

---

## 5. GIF 정책

| 상태 | 처리 방식 |
|------|-----------|
| **정적 GIF** (단일 프레임) | PNG로 변환 후 메타데이터 기록 |
| **Ugoira (Pixiv 애니메이션)** | WebP managed 생성 (`is_ugoira=true`) |
| **일반 애니메이션 GIF** | WebP managed 생성 |

> Ugoira 원본 ZIP은 보존되며, WebP managed에 메타데이터를 기록합니다.

---

## 6. AruArchive JSON 스키마

```json
{
  "_aru_schema": "1.0",
  "source_site": "pixiv",
  "artwork_id": "103192368",
  "artwork_url": "https://www.pixiv.net/artworks/103192368",
  "artwork_title": "작품 제목",
  "page_index": 0,
  "total_pages": 3,
  "original_filename": "103192368_p0.jpg",
  "artist_id": "12345",
  "artist_name": "작가명",
  "artist_url": "https://www.pixiv.net/users/12345",
  "tags": ["tag1", "tag2"],
  "character_tags": ["character1"],
  "series_tags": ["series1"],
  "is_ugoira": false,
  "downloaded_at": "2026-04-26T12:00:00+00:00"
}
```

---

## 7. 사이드카 파일

이미지 포맷이 UserComment를 지원하지 않거나 쓰기가 실패한 경우,  
`{filename}.aru.json` 사이드카 파일에 메타데이터를 저장합니다.

---

## 8. ExifTool XMP 기록

### XMP 필드 매핑

| XMP 필드 | AruArchive 소스 |
|----------|----------------|
| `XMP-dc:Title` | `artwork_title` |
| `XMP-dc:Creator` | `artist_name` |
| `XMP-dc:Subject` | `tags` + `series_tags` + `character_tags` (각각 별도 항목) |
| `XMP-dc:Source` | `artwork_url` |
| `XMP-dc:Description` | `description` |
| `XMP-dc:Identifier` | `artwork_id` |
| `XMP:MetadataDate` | 현재 UTC 시각 |
| `XMP:Rating` | `rating` (0–5, 없으면 생략) |
| `XMP:Label` | `source_site` (없으면 `"Aru Archive"`) |

### 상태 전이

```
json_only + ExifTool 성공  → full
json_only + ExifTool 실패  → xmp_write_failed  ← no_metadata_queue 삽입 없음
json_only + ExifTool 없음  → json_only (변경 없음)
xmp_write_failed + 성공    → full (XMP 재시도로 복구)
```

`xmp_write_failed`는 **Warning 카테고리**에 표시됩니다 (사이드바 `⚠ 경고`).  
`no_metadata_queue`에는 삽입하지 않습니다.

### ExifTool 설정

`설정 → 고급 → ExifTool 경로`에서 실행 파일 경로를 지정합니다.

```json
{ "exiftool_path": "C:/exiftool/exiftool.exe" }
```

ExifTool이 설정되지 않으면 XMP 기록을 건너뛰고 `json_only`를 유지합니다.

### XMP 재처리

- **Detail 패널** `[🔄 XMP 재시도]` — 현재 그룹 1개를 재처리
- **툴바** `[🔄 전체 XMP 재처리]` — `json_only` 및 `xmp_write_failed` 그룹 일괄 처리

---

## 9. Referer 정책 (다운로드)

Pixiv 이미지 서버(`i.pximg.net`)는 Referer 검증을 수행합니다.

```
Referer: https://www.pixiv.net/artworks/{artwork_id}
```

Referer 없이 요청하면 HTTP 403 응답이 반환됩니다.
