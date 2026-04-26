"""
core/dictionary_sources/danbooru_source.py 테스트.

네트워크 호출 없이 unittest.mock으로 httpx를 mock한다.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.dictionary_sources.danbooru_source import (
    DanbooruSourceAdapter,
    DanbooruSourceError,
    extract_parent_series_from_danbooru_character_tag,
    humanize_danbooru_tag,
    map_danbooru_category_to_aru_type,
)


# ---------------------------------------------------------------------------
# map_danbooru_category_to_aru_type
# ---------------------------------------------------------------------------

class TestMapCategory:
    def test_copyright_to_series(self) -> None:
        assert map_danbooru_category_to_aru_type("copyright") == "series"

    def test_character_to_character(self) -> None:
        assert map_danbooru_category_to_aru_type("character") == "character"

    def test_general_to_general(self) -> None:
        assert map_danbooru_category_to_aru_type("general") == "general"

    def test_artist_to_artist(self) -> None:
        assert map_danbooru_category_to_aru_type("artist") == "artist"

    def test_meta_to_general(self) -> None:
        assert map_danbooru_category_to_aru_type("meta") == "general"

    def test_int_3_copyright(self) -> None:
        assert map_danbooru_category_to_aru_type(3) == "series"

    def test_int_4_character(self) -> None:
        assert map_danbooru_category_to_aru_type(4) == "character"

    def test_int_0_general(self) -> None:
        assert map_danbooru_category_to_aru_type(0) == "general"

    def test_int_1_artist(self) -> None:
        assert map_danbooru_category_to_aru_type(1) == "artist"

    def test_unknown_falls_back_to_general(self) -> None:
        assert map_danbooru_category_to_aru_type("unknown_type") == "general"


# ---------------------------------------------------------------------------
# humanize_danbooru_tag
# ---------------------------------------------------------------------------

class TestHumanizeDanbooruTag:
    def test_simple_snake_case(self) -> None:
        assert humanize_danbooru_tag("blue_archive") == "Blue Archive"

    def test_removes_series_suffix(self) -> None:
        assert humanize_danbooru_tag("wakamo_(blue_archive)") == "Wakamo"

    def test_multi_word(self) -> None:
        assert humanize_danbooru_tag("kosaka_wakamo") == "Kosaka Wakamo"

    def test_single_word(self) -> None:
        assert humanize_danbooru_tag("wakamo") == "Wakamo"

    def test_aru_blue_archive(self) -> None:
        assert humanize_danbooru_tag("aru_(blue_archive)") == "Aru"

    def test_empty_string(self) -> None:
        # 빈 문자열 → 빈 문자열
        assert humanize_danbooru_tag("") == ""


# ---------------------------------------------------------------------------
# extract_parent_series_from_danbooru_character_tag
# ---------------------------------------------------------------------------

class TestExtractParentSeries:
    def test_blue_archive_known(self) -> None:
        result = extract_parent_series_from_danbooru_character_tag("wakamo_(blue_archive)")
        assert result == "Blue Archive"

    def test_shiroko_blue_archive(self) -> None:
        result = extract_parent_series_from_danbooru_character_tag("shiroko_(blue_archive)")
        assert result == "Blue Archive"

    def test_no_parentheses_returns_none(self) -> None:
        result = extract_parent_series_from_danbooru_character_tag("wakamo")
        assert result is None

    def test_unknown_series_humanized(self) -> None:
        result = extract_parent_series_from_danbooru_character_tag("char_(some_game)")
        assert result == "Some Game"


# ---------------------------------------------------------------------------
# DanbooruSourceAdapter — mock 기반
# ---------------------------------------------------------------------------

def _make_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


class TestFetchTag:
    def test_fetch_tag_success(self) -> None:
        tag_data = [{"name": "blue_archive", "category": 3, "post_count": 5000}]
        with patch("httpx.get", return_value=_make_response(tag_data)):
            adapter = DanbooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_tag("blue_archive")
        assert result is not None
        assert result["name"] == "blue_archive"

    def test_fetch_tag_not_found_returns_none(self) -> None:
        with patch("httpx.get", return_value=_make_response([], 200)):
            adapter = DanbooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_tag("nonexistent_tag_xyz")
        assert result is None

    def test_fetch_tag_404_returns_none(self) -> None:
        with patch("httpx.get", return_value=_make_response(None, 404)):
            adapter = DanbooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_tag("missing")
        assert result is None

    def test_fetch_tag_cached(self) -> None:
        tag_data = [{"name": "blue_archive", "category": 3, "post_count": 100}]
        with patch("httpx.get", return_value=_make_response(tag_data)) as mock_get:
            adapter = DanbooruSourceAdapter(rate_limit_seconds=0)
            adapter.fetch_tag("blue_archive")
            adapter.fetch_tag("blue_archive")  # cached
        assert mock_get.call_count == 1


class TestFetchTagAliases:
    def test_fetch_aliases_success(self) -> None:
        alias_data = [
            {"antecedent_name": "ba", "consequent_name": "blue_archive", "status": "active"}
        ]
        with patch("httpx.get", return_value=_make_response(alias_data)):
            adapter = DanbooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_tag_aliases("blue_archive")
        assert len(result) == 1
        assert result[0]["antecedent_name"] == "ba"

    def test_fetch_aliases_non_list_returns_empty(self) -> None:
        with patch("httpx.get", return_value=_make_response({"error": "bad"})):
            adapter = DanbooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_tag_aliases("x")
        assert result == []


class TestNetworkError:
    def test_timeout_raises_danbooru_error(self) -> None:
        import httpx as _httpx
        with patch("httpx.get", side_effect=_httpx.TimeoutException("timeout")):
            adapter = DanbooruSourceAdapter(rate_limit_seconds=0)
            with pytest.raises(DanbooruSourceError, match="Timeout"):
                adapter.fetch_tag("blue_archive")

    def test_request_error_raises_danbooru_error(self) -> None:
        import httpx as _httpx
        with patch("httpx.get", side_effect=_httpx.RequestError("conn refused")):
            adapter = DanbooruSourceAdapter(rate_limit_seconds=0)
            with pytest.raises(DanbooruSourceError):
                adapter.fetch_tag("blue_archive")

    def test_http_500_raises_danbooru_error(self) -> None:
        with patch("httpx.get", return_value=_make_response(None, 500)):
            adapter = DanbooruSourceAdapter(rate_limit_seconds=0)
            with pytest.raises(DanbooruSourceError, match="HTTP 500"):
                adapter.fetch_tag("blue_archive")


class TestFetchSeriesCandidates:
    def test_returns_series_candidates(self) -> None:
        tags = [{"name": "blue_archive", "category": 3, "post_count": 5000}]
        with patch("httpx.get", return_value=_make_response(tags)):
            adapter = DanbooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_series_candidates("blue_archive")
        assert len(result) == 1
        assert result[0]["tag_type"] == "series"
        assert result[0]["canonical"] == "Blue Archive"

    def test_network_error_returns_empty(self) -> None:
        import httpx as _httpx
        with patch("httpx.get", side_effect=_httpx.TimeoutException("t")):
            adapter = DanbooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_series_candidates("blue_archive")
        assert result == []


class TestFetchCharacterCandidates:
    def test_returns_character_candidates(self) -> None:
        tags = [
            {"name": "wakamo_(blue_archive)", "category": 4, "post_count": 800},
        ]
        with patch("httpx.get", return_value=_make_response(tags)):
            adapter = DanbooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_character_candidates("blue_archive")
        assert len(result) == 1
        c = result[0]
        assert c["tag_type"] == "character"
        assert c["canonical"] == "Wakamo"
        assert c["parent_series"] == "Blue Archive"
        assert c["confidence_score"] > 0

    def test_parent_series_inferred_from_tag(self) -> None:
        tags = [{"name": "aru_(blue_archive)", "category": 4, "post_count": 200}]
        with patch("httpx.get", return_value=_make_response(tags)):
            adapter = DanbooruSourceAdapter(rate_limit_seconds=0)
            result = adapter.fetch_character_candidates("blue_archive")
        assert result[0]["parent_series"] == "Blue Archive"
