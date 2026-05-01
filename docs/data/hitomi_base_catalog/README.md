# Hitomi Base Tag Catalog — Docs Working Data

이 디렉터리는 **Aru Archive BASE tag seed 설계를 위한 docs 작업용 데이터**다.
런타임 코드, DB, tag pack, classifier에는 아직 반영되지 않은 **설계 참고 전용** 자료다.

---

## 1. 출처

- **데이터 원본**: 사용자 로컬 `hitomi_downloader_GUI` 캐시
- **원본 파일**: `hitomi_data/tags.txt` (사용자 환경 로컬 절대 경로 — 이 저장소에 포함되지 않음)
- **원본 파일 크기**: 약 3.5 MB (JSON)
- **추출 시점**: 로컬 실행 시 생성되는 output 파일 참조

`source_path_user` 같은 절대경로는 README나 commit 대상 어디에도 기록하지 않습니다.

원본 파일은 이 저장소에 commit되지 않는다.
`extract_hitomi_catalog.py`로 언제든 재추출 가능하다.

---

## 2. 데이터 성격

- **Hitomi.la 로컬 검색 카탈로그** — Hitomi.la 갤러리 인덱스 기반
- **canonical slug 형식** — lowercase, 공백 구분자 (예: `blue archive`, `arknights`)
- **다국어 번역/alias 아님** — 일본어 원어, 한국어 표기, alias는 포함되지 않음
- **Pixiv tag canonical과 다를 수 있음**
  - Hitomi: `blue archive` (lowercase slug)
  - Pixiv: `ブルーアーカイブ` (일본어 원어)
- **각 항목 구조**: `{"s": "canonical slug", "t": <gallery count>}`

---

## 3. 카테고리별 카운트 정보 (재생성 가능)

아래 수치는 로컬 추출 기준 스냅샷이다. 원본 캐시 갱신 후 `extract_hitomi_catalog.py`로 재추출하면 달라질 수 있다.

| category  | count (Hitomi local cache 기준) | filter | sample 사용 |
|-----------|--------------------------------|--------|------------|
| series    | 5,487 | none | 로컬 추출 전용 |
| character | 25,016 | none | 로컬 추출 전용 |
| female    | 622 | adult denylist (~40% 제외, 371건 통과) | 로컬 추출 전용 |
| male      | 584 | adult denylist (~38% 제외, 361건 통과) | 로컬 추출 전용 |
| artist    | 41,497 | — | 제외 (작가명 보호) |
| group     | 33,957 | — | 제외 (서클명 보호) |
| tag       | 13,221 | — | 제외 (성인 태그 다수 포함 가능) |
| language  | 44 | — | 제외 (사용 안 함) |

sample 파일은 로컬 추출 전용이며 이 저장소에 commit되지 않는다.

---

## 4. Aru Archive 활용 가능성

- **BASE canonical 후보** — 특히 `series` / `character` 카테고리
- **frequency-based priority** — gallery count(`t`)를 popularity 지표로 활용 가능
- **tag pack 설계 참고** — 어떤 시리즈/캐릭터가 많이 존재하는지 파악
- **Pixiv ↔ Hitomi alias gap 분석** — Hitomi slug vs Pixiv 일본어 원어 매핑 작업의 기초 자료
- **series seed 확장** — 현재 built-in series에 없는 항목 발굴
- **female/male body descriptor seed** — 의상·헤어·신체 묘사 태그 후보 (성인 필터 적용 후)

---

## 5. 성인 콘텐츠 필터 정책 (female / male 카테고리)

`female` / `male` 카테고리는 doujinshi 카탈로그 특성상 성인 콘텐츠 태그를 다수 포함한다.
`extract_hitomi_catalog.py`는 **ADULT_DENYLIST 기반 보수적 필터링**을 적용한다.

### 필터 정책

- `extract_hitomi_catalog.py` 내 `ADULT_DENYLIST` frozenset에 키워드 정의
- 각 태그의 canonical slug를 lowercase로 변환 후 **부분 문자열 매칭 (partial match)**
- 하나라도 매칭되면 해당 태그 제외
- 제외 대상 카테고리: 성행위, 성기 관련, BDSM/구속, 비동의/폭력, 미성년 관련, 페티시, 근친 관계 맥락 등

### female/male 식별자

female/male 추출 항목에는 `"filtered_subset": "non_adult_descriptive"` 필드가 포함된다.
이 값은 "성인 필터를 통과한 descriptive subset"임을 명시한다.

### 자동 필터의 한계

- denylist는 **보수적 휴리스틱**으로 100% 정확하지 않음
- 추출 후 반드시 직접 검토할 것
- borderline 항목 발견 시 `ADULT_DENYLIST`에 키워드 추가 후 재추출

---

## 6. Commit 금지 정책

이 저장소에 절대 commit하지 않는 항목:

- **`*.sample.json`** (모든 카테고리 — series/character/female/male) — 외부 derived data, commit 대상 아님
- **`catalog_summary.json`** — 사용자 절대경로 노출 위험, README로 통합됨
- **`mojibake_report*.json`** — 로컬 DB 진단 결과, 개인 환경 데이터
- **`repair_plan*.json`** — 로컬 DB 수리 계획, 개인 환경 데이터
- **원본 `tags.txt`** — 3.5 MB JSON, 개인 캐시 데이터
- **`galleries*_pack.json`** — 388 MB MessagePack 갤러리 인덱스
- **사용자 DB 캐시** (`hitomi_downloader_GUI.ini`, 로컬 SQLite 등)

| category | commit 가능 여부 |
|----------|----------------|
| series    | **미포함 — 로컬 추출 전용 / commit 금지** |
| character | **미포함 — 로컬 추출 전용 / commit 금지** |
| female    | **미포함 — 로컬 추출 전용 / commit 금지** |
| male      | **미포함 — 로컬 추출 전용 / commit 금지** |

---

## 7. 파일 목록

| 파일 | 설명 | commit 여부 |
|------|------|------------|
| `README.md` | 이 문서 — 출처, 절차, 정책, 카운트 정보 | 포함 |
| `schema.json` | sample item JSON schema (draft-07) | 포함 |
| `extract_hitomi_catalog.py` | 추출 스크립트 (read-only CLI) | 포함 |
| `*.sample.json` | 로컬 추출 결과 (각 카테고리) | **금지** |
| `catalog_summary.json` | (삭제됨 — README로 통합) | **금지** |

---

## 8. 로컬 추출 절차

추출 결과는 `.research/` 또는 별도 임시 디렉터리에 저장할 것.
`docs/data/hitomi_base_catalog/` 내부에 직접 저장하면 실수로 commit될 위험이 있다.

```
python docs/data/hitomi_base_catalog/extract_hitomi_catalog.py \
  --tags "<your-local-tags.txt-path>" \
  --out .research/hitomi_catalog \
  --limit 100
```

→ `.research/hitomi_catalog/` 아래 series, character, female (filtered), male (filtered) sample 생성.
→ `.research/`는 `.gitignore`에 포함되어 있으므로 자동으로 git 추적 제외.

---

## 9. 사용 한계

- **바로 Aru Archive runtime에 승격 금지** — classifier / tag_localizer / tag_pack 반영 전에 별도 검토 필요
- title-only 매칭으로 character 자동 확정 금지
- 성인/민감 태그를 character/series로 승격 금지
- female/male 추출 결과는 필터 통과 후에도 **사용자 review 권장**

---

## 10. 다음 PR 후보

1. **Pixiv canonical 매핑 분석** — Hitomi slug vs Pixiv 일본어 원어 gap diff
2. **built-in series seed 확장** — Hitomi 상위 series 중 Aru Archive에 없는 항목 추가
3. **tag pack 설계** — Hitomi canonical을 alias로, Pixiv canonical을 primary로 매핑하는 tag pack 구조
4. **전체 catalog DB import 설계** — `external_dictionary_entries` 테이블 활용 방안
