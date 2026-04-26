"""
Safebooru DAPI adapter.

자동 확정 금지 — 조회 결과는 staging 후보로만 사용된다.
사용자 승인 후 tag_aliases / tag_localizations로 승격한다.

Safebooru DAPI endpoints (json=1):
  posts: /index.php?page=dapi&s=post&q=index&tags=...&limit=...&pid=...&json=1
  tags:  /index.php?page=dapi&s=tag&q=index&name=...&limit=...&pid=...&json=1

Safebooru tag type IDs:
  0=general, 1=artist, 3=copyright(series), 4=character, 5=meta
"""
from __future__ import annotations

import logging
import re
import time
from collections import Counter
from typing import Any

import httpx

from core.dictionary_sources.base import DictionarySourceAdapter

logger = logging.getLogger(__name__)

_SAFEBOORU_TYPE_MAP: dict[int, str] = {
    0: "general",
    1: "artist",
    3: "copyright",
    4: "character",
    5: "meta",
}

_KNOWN_SERIES_CANONICAL: dict[str, str] = {
    "blue_archive": "Blue Archive",
}


class SafebooruSourceError(Exception):
    """Safebooru API 호출 실패."""


class SafebooruSourceAdapter(DictionarySourceAdapter):
    """
    Safebooru DAPI 기반 사전 후보 어댑터.

    post co-occurrence 분석으로 character 후보를 생성한다.
    rate_limit_seconds 간격으로 요청을 제한한다.
    네트워크 실패 시 SafebooruSourceError를 raise한다.
    """

    source_name = "safebooru"

    def __init__(
        self,
        base_url: str = "https://safebooru.org",
        timeout: float = 15.0,
        user_agent: str | None = None,
        rate_limit_seconds: float = 1.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._rate_limit = rate_limit_seconds
        self._last_request_at: float = 0.0
        self._cache: dict[str, Any] = {}
        ua = user_agent or "AruArchive/1.0 (https://github.com/sdh-dot/aru_archive)"
        self._headers = {"User-Agent": ua, "Accept": "application/json"}

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def fetch_posts(
        self,
        tags: str,
        *,
        limit: int = 100,
        pid: int = 0,
    ) -> list[dict]:
        """
        DAPI post 검색.
        반환: post dict list. 각 post에는 space-separated 'tags' 문자열 포함.
        네트워크 오류 시 [] 반환 (앱 전체 실패로 전파 안 됨).
        """
        cache_key = f"posts:{tags}:{limit}:{pid}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            data = self._get(params={
                "page": "dapi", "s": "post", "q": "index",
                "tags": tags, "limit": limit, "pid": pid, "json": 1,
            })
        except SafebooruSourceError:
            return []
        result = self._parse_posts(data)
        self._cache[cache_key] = result
        return result

    def fetch_tags(
        self,
        name: str | None = None,
        *,
        tag_type: int | None = None,
        limit: int = 100,
        pid: int = 0,
    ) -> list[dict]:
        """
        DAPI tag 검색.
        name: 태그명 (wildcard 가능, 예: "wakamo*")
        tag_type: Safebooru type int (3=copyright, 4=character 등)
        네트워크 오류 시 [] 반환.
        """
        params: dict[str, Any] = {
            "page": "dapi", "s": "tag", "q": "index",
            "limit": limit, "pid": pid, "json": 1,
        }
        if name:
            params["name"] = name
        if tag_type is not None:
            params["type"] = tag_type
        cache_key = f"tags:{name}:{tag_type}:{limit}:{pid}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            data = self._get(params=params)
        except SafebooruSourceError:
            return []
        result = self._parse_tags(data)
        self._cache[cache_key] = result
        return result

    def fetch_series_candidates(self, query: str) -> list[dict]:
        """
        copyright(=series) 후보를 tag API로 조회한다.

        반환 항목은 external_dictionary_entries 호환 dict.
        """
        series_slug = query.lower().replace(" ", "_")
        tags = self.fetch_tags(f"*{series_slug}*", tag_type=3)  # 3 = copyright
        results = []
        for tag in tags:
            tag_name = tag.get("name", "")
            if not tag_name:
                continue
            canonical = _KNOWN_SERIES_CANONICAL.get(tag_name) or _humanize_booru_tag(tag_name)
            results.append({
                "source":            "safebooru",
                "danbooru_tag":      tag_name,
                "danbooru_category": "copyright",
                "canonical":         canonical,
                "tag_type":          "series",
                "parent_series":     "",
                "alias":             tag_name,
                "locale":            None,
                "display_name":      None,
                "confidence_score":  _series_confidence(tag),
                "evidence_json":     {
                    "post_count": tag.get("count", 0),
                    "source": "safebooru",
                },
            })
        return results

    def fetch_character_candidates(
        self,
        series: str,
        query: str | None = None,
    ) -> list[dict]:
        """
        series 소속 character 후보를 post co-occurrence로 조회한다.

        series: slug 형식 (예: "blue_archive")
        query:  추가 필터 (없으면 series 전체)
        """
        series_slug = series.lower().replace(" ", "_")
        series_canonical = (
            _KNOWN_SERIES_CANONICAL.get(series_slug)
            or _humanize_booru_tag(series_slug)
        )
        posts = self.fetch_posts(series_slug, limit=100)
        candidates = build_candidates_from_safebooru_posts(
            posts,
            series_query=series_slug,
            series_canonical=series_canonical,
        )
        if query:
            q_slug = query.lower().replace(" ", "_")
            candidates = [c for c in candidates if q_slug in c.get("danbooru_tag", "")]
        return candidates

    # ------------------------------------------------------------------
    # 내부 파싱
    # ------------------------------------------------------------------

    def _parse_posts(self, data: Any) -> list[dict]:
        """Safebooru post 응답을 list[dict]로 방어적 파싱한다."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # {"@attributes": {...}, "post": [...]} 구조
            posts = data.get("post") or data.get("posts") or []
            if isinstance(posts, list):
                return posts
        return []

    def _parse_tags(self, data: Any) -> list[dict]:
        """Safebooru tag 응답을 list[dict]로 방어적 파싱한다."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            tags = data.get("tag") or data.get("tags") or []
            if isinstance(tags, list):
                return tags
        return []

    # ------------------------------------------------------------------
    # 내부 HTTP 헬퍼
    # ------------------------------------------------------------------

    def _get(self, params: dict | None = None) -> Any:
        """rate-limited GET 요청. 실패 시 SafebooruSourceError raise."""
        self._wait_rate_limit()
        url = self._base_url + "/index.php"
        try:
            resp = httpx.get(
                url,
                params=params,
                headers=self._headers,
                timeout=self._timeout,
                follow_redirects=True,
            )
            self._last_request_at = time.monotonic()
            if resp.status_code == 200:
                try:
                    return resp.json()
                except Exception as parse_exc:
                    raise SafebooruSourceError(
                        f"JSON parse error: {url}"
                    ) from parse_exc
            if resp.status_code == 404:
                return None
            raise SafebooruSourceError(f"HTTP {resp.status_code}: {url}")
        except httpx.TimeoutException as exc:
            raise SafebooruSourceError(f"Timeout: {url}") from exc
        except httpx.RequestError as exc:
            raise SafebooruSourceError(f"Request error: {exc}") from exc

    def _wait_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self._rate_limit - elapsed
        if wait > 0:
            time.sleep(wait)


# ---------------------------------------------------------------------------
# 유틸리티 함수 (모듈 수준 공개)
# ---------------------------------------------------------------------------

def map_safebooru_type_to_aru_type(tag_type: str | int | None) -> str:
    """
    Safebooru tag type을 Aru Archive 내부 tag_type으로 변환한다.

    int 입력:   0=general, 1=artist, 3=copyright(→series), 4=character, 5=meta
    str 입력:   "copyright" → "series", "character" → "character", 등
    알 수 없는 값 → "general"
    """
    if tag_type is None:
        return "general"
    if isinstance(tag_type, int):
        tag_type = _SAFEBOORU_TYPE_MAP.get(tag_type, "general")
    mapping = {
        "copyright": "series",
        "character": "character",
        "general":   "general",
        "artist":    "artist",
        "meta":      "general",
    }
    return mapping.get(str(tag_type).lower(), "general")


def build_candidates_from_safebooru_posts(
    posts: list[dict],
    *,
    series_query: str,
    series_canonical: str | None = None,
) -> list[dict]:
    """
    Safebooru post 목록에서 co-occurrence 기반 character 후보를 생성한다.

    series_query: Safebooru tag slug (예: "blue_archive")
    series_canonical: 사람이 읽기 좋은 시리즈명 (없으면 humanize)

    반환: external_dictionary_entries 호환 dict 목록.
    각 후보에는 source="safebooru", tag_type="character", evidence_json 포함.
    """
    from core.dictionary_sources.danbooru_source import (
        humanize_danbooru_tag,
        extract_parent_series_from_danbooru_character_tag,
    )

    if series_canonical is None:
        series_canonical = (
            _KNOWN_SERIES_CANONICAL.get(series_query)
            or _humanize_booru_tag(series_query)
        )

    # 각 character tag의 post 등장 횟수를 카운트
    tag_counter: Counter[str] = Counter()
    for post in posts:
        tags_str = post.get("tags", "") or ""
        if isinstance(tags_str, str):
            for t in tags_str.split():
                if f"({series_query})" in t:
                    tag_counter[t] += 1

    results: list[dict] = []
    total_posts = len(posts)

    for tag_name, post_count in tag_counter.items():
        canonical = humanize_danbooru_tag(tag_name)
        inferred_series = extract_parent_series_from_danbooru_character_tag(tag_name)
        parent_series = inferred_series or series_canonical

        confidence = _character_co_occurrence_confidence(post_count, total_posts)

        results.append({
            "source":            "safebooru",
            "danbooru_tag":      tag_name,
            "danbooru_category": "character",
            "canonical":         canonical,
            "tag_type":          "character",
            "parent_series":     parent_series,
            "alias":             tag_name,
            "locale":            "en",
            "display_name":      canonical,
            "confidence_score":  confidence,
            "evidence_json":     {
                "series_query": series_query,
                "post_count":   post_count,
                "total_posts":  total_posts,
                "source":       "safebooru",
            },
        })

    return results


# ---------------------------------------------------------------------------
# 내부 신뢰도 헬퍼
# ---------------------------------------------------------------------------

def _humanize_booru_tag(tag: str) -> str:
    """snake_case booru tag를 Title Case로 변환 (괄호 suffix 제거)."""
    base = re.sub(r"\([^)]*\)\s*$", "", tag).strip("_ ")
    return " ".join(w.capitalize() for w in base.split("_") if w)


def _series_confidence(tag: dict) -> float:
    score = 0.35  # copyright category 확인됨
    count = tag.get("count", 0)
    if count and count >= 100:
        score += 0.20
    return min(1.0, score)


def _character_co_occurrence_confidence(post_count: int, total_posts: int) -> float:
    """post co-occurrence 빈도로 character 후보 신뢰도를 계산한다."""
    from core.external_dictionary import calculate_external_dictionary_confidence

    ratio = post_count / total_posts if total_posts else 0
    pixiv_obs = ratio >= 0.05  # 전체 posts의 5% 이상 등장

    return calculate_external_dictionary_confidence(
        danbooru_category_match=True,    # character suffix로 추정
        parent_series_matched=True,      # series suffix로 추론됨
        pixiv_observation_matched=pixiv_obs,
    )
