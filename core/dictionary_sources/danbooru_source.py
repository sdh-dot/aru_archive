"""
Danbooru 계열 API를 통해 태그/alias/implication 후보를 조회한다.

자동 확정 금지 — 조회 결과는 staging 후보로만 사용된다.
사용자 승인 후 tag_aliases / tag_localizations로 승격한다.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from core.dictionary_sources.base import DictionarySourceAdapter

logger = logging.getLogger(__name__)

# Danbooru tag category 번호 → 이름 매핑
_CATEGORY_ID_MAP: dict[int, str] = {
    0: "general",
    1: "artist",
    3: "copyright",
    4: "character",
    5: "meta",
}

# Danbooru copyright tag → Aru canonical 매핑 (humanize 보정)
_KNOWN_SERIES_CANONICAL: dict[str, str] = {
    "blue_archive": "Blue Archive",
}


class DanbooruSourceError(Exception):
    """Danbooru API 호출 실패."""


class DanbooruSourceAdapter(DictionarySourceAdapter):
    """
    Danbooru API 기반 사전 후보 어댑터.

    rate_limit_seconds 간격으로 요청을 제한한다.
    네트워크 실패 시 DanbooruSourceError를 raise한다.
    """

    source_name = "danbooru"

    def __init__(
        self,
        base_url: str = "https://danbooru.donmai.us",
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

    def fetch_tag(self, tag_name: str) -> dict | None:
        """태그 단건 조회. 없으면 None 반환."""
        cache_key = f"tag:{tag_name}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            data = self._get("/tags.json", params={"search[name]": tag_name, "limit": 1})
        except DanbooruSourceError:
            raise
        if not data:
            self._cache[cache_key] = None
            return None
        result = data[0] if isinstance(data, list) else data
        self._cache[cache_key] = result
        return result

    def fetch_tag_aliases(self, tag_name: str | None = None) -> list[dict]:
        """tag_name과 관련된 alias 목록 조회."""
        params: dict[str, Any] = {"limit": 50}
        if tag_name:
            params["search[antecedent_name]"] = tag_name
        cache_key = f"aliases:{tag_name}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        result = self._get("/tag_aliases.json", params=params)
        if not isinstance(result, list):
            result = []
        self._cache[cache_key] = result
        return result

    def fetch_tag_implications(self, tag_name: str | None = None) -> list[dict]:
        """tag_name과 관련된 implication 목록 조회."""
        params: dict[str, Any] = {"limit": 50}
        if tag_name:
            params["search[antecedent_name]"] = tag_name
        cache_key = f"implications:{tag_name}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        result = self._get("/tag_implications.json", params=params)
        if not isinstance(result, list):
            result = []
        self._cache[cache_key] = result
        return result

    def fetch_related_tags(
        self,
        query: str,
        category: str | None = None,
    ) -> list[dict]:
        """related_tag API로 관련 태그를 조회한다."""
        params: dict[str, Any] = {"query": query, "limit": 50}
        if category:
            params["category"] = category
        cache_key = f"related:{query}:{category}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            raw = self._get("/related_tag.json", params=params)
        except DanbooruSourceError:
            return []
        tags = raw.get("tags", []) if isinstance(raw, dict) else []
        self._cache[cache_key] = tags
        return tags

    def fetch_series_candidates(self, query: str) -> list[dict]:
        """
        copyright(=series) 후보를 조회한다.

        반환 항목:
          danbooru_tag, danbooru_category, canonical, tag_type, parent_series,
          alias, confidence_score, evidence_json
        """
        params = {
            "search[name_matches]": f"*{query}*",
            "search[category]": 3,  # copyright
            "limit": 20,
            "only": "name,category,post_count",
        }
        try:
            rows = self._get("/tags.json", params=params)
        except DanbooruSourceError:
            return []
        if not isinstance(rows, list):
            return []

        results = []
        for row in rows:
            tag_name = row.get("name", "")
            if not tag_name:
                continue
            canonical = _KNOWN_SERIES_CANONICAL.get(tag_name) or humanize_danbooru_tag(tag_name)
            results.append({
                "source":            "danbooru",
                "danbooru_tag":      tag_name,
                "danbooru_category": "copyright",
                "canonical":         canonical,
                "tag_type":          "series",
                "parent_series":     "",
                "alias":             tag_name,
                "locale":            None,
                "display_name":      None,
                "confidence_score":  _series_confidence(row),
                "evidence_json":     {"post_count": row.get("post_count", 0)},
            })
        return results

    def fetch_character_candidates(
        self,
        series: str,
        query: str | None = None,
    ) -> list[dict]:
        """
        series 소속 character 후보를 조회한다.

        series: Danbooru tag name (예: "blue_archive")
        query:  추가 검색어 (없으면 series 소속 전체)
        """
        name_pattern = f"*{query}*({series})*" if query else f"*({series})"
        params = {
            "search[name_matches]": name_pattern,
            "search[category]": 4,  # character
            "limit": 100,
            "only": "name,category,post_count",
        }
        try:
            rows = self._get("/tags.json", params=params)
        except DanbooruSourceError:
            return []
        if not isinstance(rows, list):
            return []

        series_canonical = _KNOWN_SERIES_CANONICAL.get(series) or humanize_danbooru_tag(series)
        results = []
        for row in rows:
            tag_name = row.get("name", "")
            if not tag_name:
                continue
            canonical = humanize_danbooru_tag(tag_name)
            inferred_series = extract_parent_series_from_danbooru_character_tag(tag_name)
            parent_series = inferred_series or series_canonical
            results.append({
                "source":            "danbooru",
                "danbooru_tag":      tag_name,
                "danbooru_category": "character",
                "canonical":         canonical,
                "tag_type":          "character",
                "parent_series":     parent_series,
                "alias":             tag_name,
                "locale":            None,
                "display_name":      None,
                "confidence_score":  _character_confidence(row, series),
                "evidence_json":     {"post_count": row.get("post_count", 0)},
            })
        return results

    # ------------------------------------------------------------------
    # 내부 HTTP 헬퍼
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> Any:
        """rate-limited GET 요청. 실패 시 DanbooruSourceError raise."""
        self._wait_rate_limit()
        url = self._base_url + path
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
                return resp.json()
            if resp.status_code == 404:
                return None
            raise DanbooruSourceError(
                f"HTTP {resp.status_code}: {url}"
            )
        except httpx.TimeoutException as exc:
            raise DanbooruSourceError(f"Timeout: {url}") from exc
        except httpx.RequestError as exc:
            raise DanbooruSourceError(f"Request error: {exc}") from exc

    def _wait_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self._rate_limit - elapsed
        if wait > 0:
            time.sleep(wait)


# ---------------------------------------------------------------------------
# 유틸리티 함수 (모듈 수준 공개)
# ---------------------------------------------------------------------------

def map_danbooru_category_to_aru_type(category: str | int) -> str:
    """
    Danbooru tag category를 Aru Archive 내부 tag_type으로 변환한다.

    숫자 category 처리:
      0=general, 1=artist, 3=copyright(series), 4=character, 5=meta
    """
    if isinstance(category, int):
        category = _CATEGORY_ID_MAP.get(category, "general")
    mapping = {
        "copyright": "series",
        "character": "character",
        "general":   "general",
        "artist":    "artist",
        "meta":      "general",
    }
    return mapping.get(str(category).lower(), "general")


def humanize_danbooru_tag(tag: str) -> str:
    """
    Danbooru snake_case tag를 사람이 읽기 좋은 형식으로 변환한다.

    wakamo_(blue_archive) → Wakamo
    kosaka_wakamo         → Kosaka Wakamo
    blue_archive          → Blue Archive
    """
    # 괄호 suffix 제거: name_(series) → name
    base = re.sub(r"\([^)]*\)\s*$", "", tag).strip("_ ")
    # snake_case → Title Case
    return " ".join(w.capitalize() for w in base.split("_") if w)


def extract_parent_series_from_danbooru_character_tag(tag: str) -> str | None:
    """
    Danbooru character tag에서 parent series를 추론한다.

    wakamo_(blue_archive) → "Blue Archive"
    shiroko_(blue_archive) → "Blue Archive"
    unknown_char → None
    """
    m = re.search(r"\(([^)]+)\)\s*$", tag)
    if not m:
        return None
    series_slug = m.group(1)
    # 알려진 매핑 우선
    if series_slug in _KNOWN_SERIES_CANONICAL:
        return _KNOWN_SERIES_CANONICAL[series_slug]
    return humanize_danbooru_tag(series_slug)


# ---------------------------------------------------------------------------
# 내부 신뢰도 헬퍼
# ---------------------------------------------------------------------------

def _series_confidence(row: dict) -> float:
    score = 0.40  # copyright category 확인됨
    post_count = row.get("post_count", 0)
    if post_count and post_count >= 100:
        score += 0.20
    return min(1.0, score)


def _character_confidence(row: dict, series_slug: str) -> float:
    score = 0.35  # character category 확인됨
    tag_name = row.get("name", "")
    # parent_series 확인
    if series_slug and f"({series_slug})" in tag_name:
        score += 0.25
    post_count = row.get("post_count", 0)
    if post_count and post_count >= 50:
        score += 0.15
    return min(1.0, score)
