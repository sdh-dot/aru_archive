"""
core/dictionary_sources/safebooru_source.py 테스트.

네트워크 호출 없이 unittest.mock으로 httpx를 mock한다.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.dictionary_sources.safebooru_source import (
    SafebooruSourceAdapter,
    SafebooruSourceError,
    build_candidates_from_safebooru_posts,
    map_safebooru_type_to_aru_type,
)


# ---------------------------------------------------------------------------
# map_safebooru_type_to_aru_type
# ---------------------------------------------------------------------------

class TestMapSafebooruType:
    def test_copyright_str_to_series(self) -> None:
        assert map_safebooru_type_to_aru_type("copyright") == "series"

    def test_Copyright_case_insensitive(self) -> None:
        assert map_safebooru_type_to_aru_type("Copyright") == "series"

    def test_character_str_to_character(self) -> None:
        assert map_safebooru_type_to_aru_type("character") == "character"

    def test_Character_case_insensitive(self) -> None:
        assert map_safebooru_type_to_aru_type("Character") == "character"

    def test_artist_str_to_artist(self) -> None:
        assert map_safebooru_type_to_aru_type("artist") == "artist"

    def test_general_str_to_general(self) -> None:
        assert map_safebooru_type_to_aru_type("general") == "general"

    def test_meta_str_to_general(self) -> None:
        assert map_safebooru_type_to_aru_type("meta") == "general"

    def test_int_0_to_general(self) -> None:
        assert map_safebooru_type_to_aru_type(0) == "general"

    def test_int_1_to_artist(self) -> None:
        assert map_safebooru_type_to_aru_type(1) == "artist"

    def test_int_3_to_series(self) -> None:
        assert map_safebooru_type_to_aru_type(3) == "series"

    def test_int_4_to_character(self) -> None:
        assert map_safebooru_type_to_aru_type(4) == "character"

    def test_int_5_meta_to_general(self) -> None:
        assert map_safebooru_type_to_aru_type(5) == "general"

    def test_none_returns_general(self) -> None:
        assert map_safebooru_type_to_aru_type(None) == "general"

    def test_unknown_string_returns_general(self) -> None:
        assert map_safebooru_type_to_aru_type("unknown_type") == "general"

    def test_int_99_unknown_returns_general(self) -> None:
        assert map_safebooru_type_to_aru_type(99) == "general"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_response(data, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


# ---------------------------------------------------------------------------
# fetch_posts
# ---------------------------------------------------------------------------

class TestFetchPosts:
    def test_fetch_posts_list_response(self) -> None:
        posts = [
            {"id": 1, "tags": "blue_archive wakamo_(blue_archive) kimono", "score": "5"},
            {"id": 2, "tags": "blue_archive shiroko_(blue_archive) school_uniform"},
        ]
        with patch("httpx.get", return_value=_make_response(posts)):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_posts("blue_archive")
        assert len(result) == 2
        assert result[0]["id"] == 1

    def test_fetch_posts_dict_response_with_post_key(self) -> None:
        """응답이 {"@attributes": {...}, "post": [...]} 구조인 경우."""
        posts_data = {
            "@attributes": {"limit": 100, "offset": 0, "count": 1},
            "post": [{"id": 1, "tags": "blue_archive wakamo_(blue_archive)"}],
        }
        with patch("httpx.get", return_value=_make_response(posts_data)):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_posts("blue_archive")
        assert len(result) == 1

    def test_fetch_posts_empty_list(self) -> None:
        with patch("httpx.get", return_value=_make_response([])):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_posts("nonexistent_series_xyz")
        assert result == []

    def test_fetch_posts_network_error_returns_empty(self) -> None:
        import httpx as _httpx
        with patch("httpx.get", side_effect=_httpx.RequestError("conn refused")):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_posts("blue_archive")
        assert result == []

    def test_fetch_posts_timeout_returns_empty(self) -> None:
        import httpx as _httpx
        with patch("httpx.get", side_effect=_httpx.TimeoutException("timeout")):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_posts("blue_archive")
        assert result == []

    def test_fetch_posts_http_500_returns_empty(self) -> None:
        with patch("httpx.get", return_value=_make_response(None, 500)):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_posts("blue_archive")
        assert result == []

    def test_fetch_posts_cached(self) -> None:
        posts = [{"id": 1, "tags": "blue_archive wakamo_(blue_archive)"}]
        with patch("httpx.get", return_value=_make_response(posts)) as mock_get:
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            adapter.fetch_posts("blue_archive")
            adapter.fetch_posts("blue_archive")  # cached — no new HTTP call
        assert mock_get.call_count == 1


# ---------------------------------------------------------------------------
# fetch_tags
# ---------------------------------------------------------------------------

class TestFetchTags:
    def test_fetch_tags_list_response(self) -> None:
        tags = [
            {"id": 1, "name": "wakamo_(blue_archive)", "count": 100, "type": 4},
        ]
        with patch("httpx.get", return_value=_make_response(tags)):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_tags("wakamo*")
        assert len(result) == 1
        assert result[0]["name"] == "wakamo_(blue_archive)"

    def test_fetch_tags_dict_response_with_tag_key(self) -> None:
        tags_data = {"tag": [{"id": 1, "name": "blue_archive", "count": 5000, "type": 3}]}
        with patch("httpx.get", return_value=_make_response(tags_data)):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_tags("blue*")
        assert len(result) == 1

    def test_fetch_tags_network_error_returns_empty(self) -> None:
        import httpx as _httpx
        with patch("httpx.get", side_effect=_httpx.RequestError("err")):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_tags("wakamo*")
        assert result == []

    def test_fetch_tags_timeout_returns_empty(self) -> None:
        import httpx as _httpx
        with patch("httpx.get", side_effect=_httpx.TimeoutException("t")):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_tags("wakamo*")
        assert result == []


# ---------------------------------------------------------------------------
# 네트워크 오류 — _get() 직접 호출
# ---------------------------------------------------------------------------

class TestNetworkErrors:
    _base_params = {"page": "dapi", "s": "post", "q": "index"}

    def test_timeout_raises_safebooru_error(self) -> None:
        import httpx as _httpx
        with patch("httpx.get", side_effect=_httpx.TimeoutException("timeout")):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            with pytest.raises(SafebooruSourceError, match="Timeout"):
                adapter._get(params=self._base_params)

    def test_request_error_raises_safebooru_error(self) -> None:
        import httpx as _httpx
        with patch("httpx.get", side_effect=_httpx.RequestError("conn refused")):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            with pytest.raises(SafebooruSourceError, match="Request error"):
                adapter._get(params=self._base_params)

    def test_http_500_raises_safebooru_error(self) -> None:
        with patch("httpx.get", return_value=_make_response(None, 500)):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            with pytest.raises(SafebooruSourceError, match="HTTP 500"):
                adapter._get(params=self._base_params)

    def test_http_404_returns_none(self) -> None:
        with patch("httpx.get", return_value=_make_response(None, 404)):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter._get(params=self._base_params)
        assert result is None


# ---------------------------------------------------------------------------
# build_candidates_from_safebooru_posts
# ---------------------------------------------------------------------------

class TestBuildCandidatesFromSafebooruPosts:
    def test_extracts_character_tags_with_series_suffix(self) -> None:
        posts = [
            {"id": 1, "tags": "blue_archive wakamo_(blue_archive) kimono new_year"},
            {"id": 2, "tags": "blue_archive wakamo_(blue_archive) school_uniform"},
            {"id": 3, "tags": "blue_archive shiroko_(blue_archive) school_uniform"},
        ]
        candidates = build_candidates_from_safebooru_posts(posts, series_query="blue_archive")
        tag_names = {c["danbooru_tag"] for c in candidates}
        assert "wakamo_(blue_archive)" in tag_names
        assert "shiroko_(blue_archive)" in tag_names

    def test_excludes_tags_without_series_suffix(self) -> None:
        posts = [
            {"id": 1, "tags": "blue_archive kimono new_year rating:general"},
        ]
        candidates = build_candidates_from_safebooru_posts(posts, series_query="blue_archive")
        assert candidates == []

    def test_parent_series_inferred_from_tag(self) -> None:
        posts = [{"id": 1, "tags": "blue_archive wakamo_(blue_archive)"}]
        candidates = build_candidates_from_safebooru_posts(posts, series_query="blue_archive")
        assert candidates[0]["parent_series"] == "Blue Archive"

    def test_canonical_is_humanized(self) -> None:
        posts = [{"id": 1, "tags": "blue_archive wakamo_(blue_archive)"}]
        candidates = build_candidates_from_safebooru_posts(posts, series_query="blue_archive")
        assert candidates[0]["canonical"] == "Wakamo"

    def test_source_is_safebooru(self) -> None:
        posts = [{"id": 1, "tags": "blue_archive wakamo_(blue_archive)"}]
        candidates = build_candidates_from_safebooru_posts(posts, series_query="blue_archive")
        assert candidates[0]["source"] == "safebooru"

    def test_tag_type_is_character(self) -> None:
        posts = [{"id": 1, "tags": "blue_archive wakamo_(blue_archive)"}]
        candidates = build_candidates_from_safebooru_posts(posts, series_query="blue_archive")
        assert candidates[0]["tag_type"] == "character"

    def test_confidence_score_in_range(self) -> None:
        posts = [{"id": 1, "tags": "blue_archive wakamo_(blue_archive)"}]
        candidates = build_candidates_from_safebooru_posts(posts, series_query="blue_archive")
        assert 0.0 < candidates[0]["confidence_score"] <= 1.0

    def test_evidence_json_has_post_count(self) -> None:
        posts = [
            {"id": 1, "tags": "blue_archive wakamo_(blue_archive)"},
            {"id": 2, "tags": "blue_archive wakamo_(blue_archive)"},
        ]
        candidates = build_candidates_from_safebooru_posts(posts, series_query="blue_archive")
        wakamo = next(c for c in candidates if c["danbooru_tag"] == "wakamo_(blue_archive)")
        assert wakamo["evidence_json"]["post_count"] == 2

    def test_evidence_json_has_total_posts(self) -> None:
        posts = [
            {"id": 1, "tags": "blue_archive wakamo_(blue_archive)"},
            {"id": 2, "tags": "blue_archive shiroko_(blue_archive)"},
        ]
        candidates = build_candidates_from_safebooru_posts(posts, series_query="blue_archive")
        assert candidates[0]["evidence_json"]["total_posts"] == 2

    def test_higher_cooccurrence_means_higher_confidence(self) -> None:
        # wakamo: 9/10 posts, shiroko: 1/10 posts
        posts = (
            [{"id": i, "tags": "blue_archive wakamo_(blue_archive)"} for i in range(9)]
            + [{"id": 9, "tags": "blue_archive shiroko_(blue_archive)"}]
        )
        candidates = build_candidates_from_safebooru_posts(posts, series_query="blue_archive")
        wakamo_conf = next(
            c["confidence_score"] for c in candidates if c["danbooru_tag"] == "wakamo_(blue_archive)"
        )
        shiroko_conf = next(
            c["confidence_score"] for c in candidates if c["danbooru_tag"] == "shiroko_(blue_archive)"
        )
        assert wakamo_conf >= shiroko_conf

    def test_empty_posts_returns_empty(self) -> None:
        assert build_candidates_from_safebooru_posts([], series_query="blue_archive") == []

    def test_custom_series_canonical_used_when_tag_lacks_suffix(self) -> None:
        """태그에 괄호 suffix가 없어 inferred_series=None일 때 series_canonical을 사용한다."""
        # "aru_(some_game)" → inferred "Some Game"
        # "aru" (no suffix) → inferred None → falls back to series_canonical
        posts = [{"id": 1, "tags": "some_game aru_(some_game)"}]
        candidates = build_candidates_from_safebooru_posts(
            posts, series_query="some_game", series_canonical="Some Game"
        )
        assert candidates[0]["parent_series"] == "Some Game"


# ---------------------------------------------------------------------------
# fetch_character_candidates (통합)
# ---------------------------------------------------------------------------

class TestFetchCharacterCandidates:
    def test_returns_character_candidates_from_posts(self) -> None:
        posts = [
            {"id": 1, "tags": "blue_archive wakamo_(blue_archive) kimono"},
            {"id": 2, "tags": "blue_archive wakamo_(blue_archive) new_year"},
        ]
        with patch("httpx.get", return_value=_make_response(posts)):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_character_candidates("blue_archive")
        assert len(result) >= 1
        assert all(c["tag_type"] == "character" for c in result)

    def test_query_filter_applied(self) -> None:
        posts = [
            {"id": 1, "tags": "blue_archive wakamo_(blue_archive)"},
            {"id": 2, "tags": "blue_archive shiroko_(blue_archive)"},
        ]
        with patch("httpx.get", return_value=_make_response(posts)):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_character_candidates("blue_archive", "shiroko")
        assert all("shiroko" in c["danbooru_tag"] for c in result)

    def test_network_error_returns_empty(self) -> None:
        import httpx as _httpx
        with patch("httpx.get", side_effect=_httpx.TimeoutException("t")):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_character_candidates("blue_archive")
        assert result == []


# ---------------------------------------------------------------------------
# fetch_series_candidates (통합)
# ---------------------------------------------------------------------------

class TestFetchSeriesCandidates:
    def test_returns_series_candidates(self) -> None:
        tags = [{"id": 1, "name": "blue_archive", "count": 5000, "type": 3}]
        with patch("httpx.get", return_value=_make_response(tags)):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_series_candidates("blue_archive")
        assert len(result) == 1
        assert result[0]["tag_type"] == "series"
        assert result[0]["canonical"] == "Blue Archive"
        assert result[0]["source"] == "safebooru"

    def test_network_error_returns_empty(self) -> None:
        import httpx as _httpx
        with patch("httpx.get", side_effect=_httpx.TimeoutException("t")):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_series_candidates("blue_archive")
        assert result == []

    def test_series_confidence_includes_high_count_bonus(self) -> None:
        tags = [{"id": 1, "name": "blue_archive", "count": 5000, "type": 3}]
        with patch("httpx.get", return_value=_make_response(tags)):
            adapter = SafebooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_series_candidates("blue_archive")
        assert result[0]["confidence_score"] > 0.35
