"""PixivAdapter — fetch_metadata / to_aru_metadata 테스트."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.adapters.pixiv import (
    PixivAdapter,
    PixivFetchError,
    PixivNetworkError,
    PixivParseError,
    PixivRestrictedError,
)


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture()
def adapter() -> PixivAdapter:
    return PixivAdapter()


def _pixiv_body(
    illust_id: str = "12345678",
    title: str = "Test Title",
    user_id: str = "999",
    user_name: str = "ArtistName",
    page_count: int = 1,
    illust_type: int = 0,
    tags: list[str] | None = None,
) -> dict:
    if tags is None:
        tags = ["タグ1", "タグ2"]
    return {
        "illustId": illust_id,
        "title": title,
        "userId": user_id,
        "userName": user_name,
        "pageCount": page_count,
        "illustType": illust_type,
        "tags": {"tags": [{"tag": t} for t in tags]},
        "xRestrict": 0,
    }


def _mock_resp(status: int, body: dict | None = None, json_error: bool = False):
    resp = MagicMock()
    resp.status_code = status
    if json_error:
        resp.json.side_effect = ValueError("bad json")
    elif body is not None:
        resp.json.return_value = body
    return resp


# ---------------------------------------------------------------------------
# fetch_metadata
# ---------------------------------------------------------------------------

class TestFetchMetadata:
    def test_success(self, adapter: PixivAdapter) -> None:
        body = _pixiv_body()
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = (
                _mock_resp(200, {"error": False, "body": body})
            )
            result = adapter.fetch_metadata("12345678")
        assert result["illustId"] == "12345678"
        assert result["title"] == "Test Title"

    def test_restricted_403(self, adapter: PixivAdapter) -> None:
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = (
                _mock_resp(403)
            )
            with pytest.raises(PixivRestrictedError):
                adapter.fetch_metadata("12345678")

    def test_not_found_404(self, adapter: PixivAdapter) -> None:
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = (
                _mock_resp(404)
            )
            with pytest.raises(PixivFetchError):
                adapter.fetch_metadata("12345678")

    def test_api_error_true(self, adapter: PixivAdapter) -> None:
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = (
                _mock_resp(200, {"error": True, "message": "작품 없음"})
            )
            with pytest.raises(PixivFetchError, match="작품 없음"):
                adapter.fetch_metadata("12345678")

    def test_other_http_error(self, adapter: PixivAdapter) -> None:
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = (
                _mock_resp(500)
            )
            with pytest.raises(PixivFetchError):
                adapter.fetch_metadata("12345678")

    def test_network_error(self, adapter: PixivAdapter) -> None:
        import httpx
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = (
                httpx.NetworkError("refused")
            )
            with pytest.raises(PixivNetworkError):
                adapter.fetch_metadata("12345678")

    def test_timeout(self, adapter: PixivAdapter) -> None:
        import httpx
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = (
                httpx.TimeoutException("timed out")
            )
            with pytest.raises(PixivNetworkError):
                adapter.fetch_metadata("12345678")

    def test_invalid_json(self, adapter: PixivAdapter) -> None:
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = (
                _mock_resp(200, json_error=True)
            )
            with pytest.raises(PixivParseError):
                adapter.fetch_metadata("12345678")

    def test_body_not_dict(self, adapter: PixivAdapter) -> None:
        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = (
                _mock_resp(200, {"error": False, "body": "unexpected string"})
            )
            with pytest.raises(PixivParseError):
                adapter.fetch_metadata("12345678")


# ---------------------------------------------------------------------------
# to_aru_metadata
# ---------------------------------------------------------------------------

class TestToAruMetadata:
    def test_basic_fields(self, adapter: PixivAdapter) -> None:
        raw = _pixiv_body(illust_id="99999", title="작품 제목", user_id="777", user_name="작가")
        meta = adapter.to_aru_metadata(raw, page_index=0, original_filename="99999_p0.jpg")

        assert meta.artwork_id == "99999"
        assert meta.artwork_title == "작품 제목"
        assert meta.artist_id == "777"
        assert meta.artist_name == "작가"
        assert meta.artwork_url == "https://www.pixiv.net/artworks/99999"
        assert meta.artist_url == "https://www.pixiv.net/users/777"
        assert meta.original_filename == "99999_p0.jpg"
        assert meta.source_site == "pixiv"

    def test_tags_extracted(self, adapter: PixivAdapter) -> None:
        raw = _pixiv_body(tags=["東方Project", "霊夢", "魔理沙"])
        meta = adapter.to_aru_metadata(raw)
        assert meta.tags == ["東方Project", "霊夢", "魔理沙"]

    def test_empty_tags(self, adapter: PixivAdapter) -> None:
        raw = _pixiv_body(tags=[])
        meta = adapter.to_aru_metadata(raw)
        assert meta.tags == []

    def test_ugoira_detection(self, adapter: PixivAdapter) -> None:
        raw = _pixiv_body(illust_type=2)
        meta = adapter.to_aru_metadata(raw)
        assert meta.is_ugoira is True

    def test_non_ugoira(self, adapter: PixivAdapter) -> None:
        raw = _pixiv_body(illust_type=0)
        meta = adapter.to_aru_metadata(raw)
        assert meta.is_ugoira is False

    def test_page_index_propagated(self, adapter: PixivAdapter) -> None:
        raw = _pixiv_body(page_count=5)
        meta = adapter.to_aru_metadata(raw, page_index=3)
        assert meta.page_index == 3
        assert meta.total_pages == 5

    def test_provenance_set(self, adapter: PixivAdapter) -> None:
        raw = _pixiv_body()
        meta = adapter.to_aru_metadata(raw)
        assert meta._provenance.get("source") == "pixiv_ajax_api"
        assert meta._provenance.get("confidence") == "high"
