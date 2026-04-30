# Tag Pack Drafts

이 디렉터리는 Tag Pack의 **raw export / draft** 파일을 보관하는 격리 공간입니다.

> **경고**: 이 디렉터리의 파일들은 active dataset이 **아닙니다**.  
> loader(`core/tag_pack_loader.py`)는 이 경로를 읽어서는 **안 됩니다**.

---

## Active Dataset 경로

```
docs/tag_pack_export_localized_ko_ja_failure_patch_v2.json
```

app 및 테스트는 항상 위 경로를 참조해야 합니다.  
이 `drafts/` 하위의 파일로 active dataset을 대체하려면 반드시 전체 v3 pipeline을 완료한 후 **명시적 sign-off**가 있어야 합니다.

---

## 파일 목록

| 파일명 | 설명 | 상태 |
|---|---|---|
| `tag_pack_export_20260430.raw.json` | 2026-04-30 raw export, v3 pipeline 입력 후보 | draft (strict fail) |

---

## `tag_pack_export_20260430.raw.json` 상세

- v3 pipeline의 **입력 후보**입니다.
- `tools/validate_tag_pack_integrity.py --strict`를 **통과하지 않습니다** (raw draft이므로 정상).
- 바이트 레벨 원본 그대로 보관 중 — 내용 수정/재포맷/인코딩 변환 금지.

### 알려진 이슈

- **구조 불일치**: top-level keys가 active v2와 다름
- **mojibake / localization 손상**: 약 175건 (ja/ko entries)
- **alias conflict**: 약 8건
- **orphan parent_series**: 약 1건

---

## 금지 사항

- [ ] active dataset으로 직접 promote 금지
- [ ] localization 추측 복구 금지 (cross-reference 없이 단독 수정 불가)
- [ ] alias conflict 자동 해소 금지
- [ ] orphan parent_series 자동 수정 금지
- [ ] strict validator 통과 전 active swap 금지

---

## v3 Pipeline 8단계 개요

아래 단계를 모두 완료하고 explicit sign-off 후에만 active dataset 교체가 허용됩니다.

1. **raw wrap / normalize** — header repair, top-level key 정규화
2. **mojibake repair** — v2 cross-reference를 통한 손상 복구
3. **alias conflict report** — 충돌 목록 생성 및 수동 검토
4. **orphan parent_series report / repair** — 고아 참조 수동 확인 후 수정
5. **localization gap tracking** — 누락 항목 `_review` 마킹, 추측 자동완성 금지
6. **strict validator pass** — `validate_tag_pack_integrity.py --strict` 종료 코드 0
7. **v3 regression test** — 신규 테스트 케이스 PASS
8. **explicit sign-off 후 active swap** — 담당자 확인 및 commit 승인
