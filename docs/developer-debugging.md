# Aru Archive — Developer Debugging Guide

이 문서는 일반 사용자에게 노출되지 않는 개발자 전용 기능을 설명합니다.

---

## Classification Failure Export

분류 미리보기에서 `author_fallback` / `series_uncategorized` 로 떨어진 항목의
raw tags를 JSON/TXT 파일로 저장하는 기능입니다.
태그 사전 보강(`enrich_tag_pack_aliases.py`) 작업의 입력으로 활용할 수 있습니다.

### 활성화 방법

#### 1. 환경변수 (가장 간단)

```powershell
# Windows PowerShell
$env:ARU_EXPORT_CLASSIFICATION_FAILURES="1"
python main.py

# 또는 모든 dev 기능 일괄 활성화
$env:ARU_ARCHIVE_DEV_MODE="1"
python main.py
```

```bash
# bash / WSL
ARU_EXPORT_CLASSIFICATION_FAILURES=1 python main.py
```

#### 2. config.json

```json
{
  "developer": {
    "enabled": true,
    "export_classification_failures": true,
    "classification_failure_export_dir": ".runtime/debug/classification_failures",
    "classification_failure_export_json": true,
    "classification_failure_export_text": true,
    "include_absolute_paths_in_debug_reports": false
  }
}
```

### 우선순위 규칙

| 조건 | 결과 |
|------|------|
| `ARU_EXPORT_CLASSIFICATION_FAILURES=1` | 강제 ON |
| `ARU_ARCHIVE_DEV_MODE=1` | 강제 ON |
| config `developer.enabled=true` AND `export_classification_failures=true` | ON |
| 그 외 | OFF (기본값) |

> **Note**: 환경변수 미설정 또는 `0`은 config를 강제로 끄지 않습니다.
> env 변수가 없으면 config 값으로 결정됩니다.

### 출력 위치

```
{data_dir}/.runtime/debug/classification_failures/
  classification_failures_20260427T123456Z.json
  classification_failures_20260427T123456Z.txt
```

`classification_failure_export_dir`이 절대 경로면 그대로 사용하고,
상대 경로면 `data_dir` 기준으로 해석합니다.

### 출력 형식

#### JSON

```json
{
  "summary": {
    "failed_groups": 3,
    "unique_raw_tags": 12,
    "generated_at": "2026-04-27T12:34:56Z"
  },
  "failed_items": [
    {
      "group_id": "...",
      "artwork_id": "106646060",
      "title": "アル社長",
      "artist": "eko",
      "file_name": "106646060_p0_master1200.jpg",
      "rule_type": "author_fallback",
      "status": "full",
      "raw_tags": ["陸八魔アル(正月)", "アル(ブルアカ)", "晴れ着"],
      "series_tags_json": [],
      "character_tags_json": [],
      "known_series_candidates": [],
      "known_character_candidates": [],
      "warnings": [],
      "suggested_debug_notes": [
        "'陸八魔アル(正月)': possible parenthetical variant tag (inner='正月')",
        "'アル(ブルアカ)': possible series disambiguator (inner='ブルアカ')"
      ]
    }
  ],
  "tag_frequency": [
    {"tag": "陸八魔アル(正月)", "count": 3, "sample_titles": ["アル社長"]},
    {"tag": "晴れ着", "count": 2, "sample_titles": ["アル社長"]}
  ]
}
```

#### TXT (Claude/Codex 붙여넣기용)

```
# Aru Archive Classification Failure Tags

## Summary
- failed groups: 3
- unique raw tags: 12
- generated_at: 2026-04-27T12:34:56Z

## Frequent Unknown Tags
1. 陸八魔アル(正月) — 3 files
2. 晴れ着 — 2 files

## Failed Files

### 106646060_p0_master1200.jpg
rule_type: author_fallback
title: アル社長
artist: eko
raw_tags:
- 陸八魔アル(正月)
- アル(ブルアカ)
- 晴れ着
debug_notes:
- '陸八魔アル(正月)': possible parenthetical variant tag (inner='正月')
- 'アル(ブルアカ)': possible series disambiguator (inner='ブルアカ')
```

### 개인정보 / 경로 보안

- **기본값**: 절대 경로 미포함. `file_name`(파일명)만 기록.
- **절대 경로 포함**: `include_absolute_paths_in_debug_reports: true` 설정 시.
  공유 전 절대 경로 포함 여부를 반드시 확인하세요.

### 실패 판정 기준

| `rule_type` / `classification_reason` | 설명 |
|---------------------------------------|------|
| `author_fallback` | series + character 모두 미분류 |
| `series_uncategorized` | series 감지됨, character 미분류 |
| `character_uncategorized` | character 감지됨, series 없음 |
| `metadata_missing` | 메타데이터 없음 |

### 자동 실행 지점

개발자 모드가 켜진 경우, 다음 미리보기 생성 시 자동으로 export됩니다.

- 단일 분류 미리보기 (`📋 분류 미리보기` 버튼)
- 선택 / 일괄 분류 미리보기 (`📋 일괄 분류` 다이얼로그)
- Workflow Wizard의 분류 미리보기 단계

로그 패널에 다음과 같은 메시지가 표시됩니다:

```
[DEV] Classification failure report exported: D:\...\.runtime\debug\classification_failures\classification_failures_20260427T123456Z.json
```

일반 모드에서는 아무 표시도 없습니다.

### 관련 모듈

| 파일 | 역할 |
|------|------|
| `core/classification_failure_exporter.py` | export 핵심 로직 |
| `core/config_manager.py` | `developer` 설정 기본값 |
| `core/batch_classifier.py` | 일괄 미리보기 연결 |
| `app/main_window.py` | 단일 미리보기 연결 |

---

## 기타 개발자 도구

- **태그 별칭 보강**: `python tools/enrich_tag_pack_aliases.py [--danbooru]`
- **분류 실패 alias 후보 생성**: `core/tag_candidate_generator.generate_alias_candidates_from_failed_tags(conn)`
- **괄호 변형 태그 분석**: `core/tag_classifier.expand_tag_match_candidates(raw_tag)`
