"""
core/pixiv_downloader.py 테스트.
httpx를 mock하여 성공 / HTTP 오류 / 임시 파일 정리를 검증한다.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_mock_client(content: bytes | None = None, status_error=None):
    """httpx.Client context-manager mock을 생성한다."""
    mock_resp = MagicMock()
    if status_error:
        mock_resp.raise_for_status.side_effect = status_error
    else:
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_bytes.return_value = [content or b""]

    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    return mock_client


def test_download_success(tmp_path):
    """정상 다운로드 시 파일이 생성되고 바이트 수가 반환된다."""
    from core.pixiv_downloader import download_pixiv_image

    content = b"FAKE_IMAGE_BYTES" * 20
    mock_client = _make_mock_client(content)

    with patch("httpx.Client", return_value=mock_client):
        dest = tmp_path / "12345_p0.jpg"
        n = download_pixiv_image(
            "https://i.pximg.net/img-original/12345_p0.jpg",
            dest,
            referer="https://www.pixiv.net/artworks/12345",
        )

    assert dest.exists()
    assert dest.read_bytes() == content
    assert n == len(content)


def test_download_http_error_raises_and_cleans_tmp(tmp_path):
    """HTTP 오류 시 PixivDownloadError가 발생하고 임시 파일이 삭제된다."""
    import httpx
    from core.pixiv_downloader import PixivDownloadError, download_pixiv_image

    err = httpx.HTTPStatusError("403", request=MagicMock(), response=MagicMock(status_code=403))
    mock_client = _make_mock_client(status_error=err)

    dest = tmp_path / "fail.jpg"
    with patch("httpx.Client", return_value=mock_client):
        with pytest.raises(PixivDownloadError, match="403"):
            download_pixiv_image(
                "https://i.pximg.net/fail.jpg",
                dest,
                referer="https://www.pixiv.net",
            )

    assert not dest.exists()
    assert not dest.with_suffix(".jpg.tmp").exists()


def test_download_creates_parent_dirs(tmp_path):
    """dest_path의 부모 디렉토리가 없어도 자동으로 생성된다."""
    from core.pixiv_downloader import download_pixiv_image

    content = b"data"
    mock_client = _make_mock_client(content)

    dest = tmp_path / "sub" / "deep" / "test.jpg"
    with patch("httpx.Client", return_value=mock_client):
        download_pixiv_image(
            "https://i.pximg.net/test.jpg",
            dest,
            referer="https://www.pixiv.net",
        )

    assert dest.exists()


def test_download_uses_referer_header(tmp_path):
    """Referer 헤더가 올바르게 설정된다."""
    from core.pixiv_downloader import download_pixiv_image

    mock_client = _make_mock_client(b"ok")
    dest = tmp_path / "img.jpg"

    with patch("httpx.Client", return_value=mock_client) as MockClient:
        download_pixiv_image(
            "https://i.pximg.net/img.jpg",
            dest,
            referer="https://www.pixiv.net/artworks/999",
        )
        # stream 호출 시 headers 인자 확인
        call_kwargs = mock_client.stream.call_args
        headers = call_kwargs.kwargs.get("headers") or {}
        assert headers.get("Referer") == "https://www.pixiv.net/artworks/999"


def test_download_with_cookies(tmp_path):
    """cookies가 httpx.Client에 전달된다."""
    from core.pixiv_downloader import download_pixiv_image

    mock_client = _make_mock_client(b"data")
    dest = tmp_path / "c.jpg"
    cookies = {"PHPSESSID": "abc123"}

    with patch("httpx.Client", return_value=mock_client) as MockClient:
        download_pixiv_image(
            "https://i.pximg.net/c.jpg",
            dest,
            referer="https://www.pixiv.net",
            cookies=cookies,
        )
        init_kwargs = MockClient.call_args.kwargs
        assert init_kwargs.get("cookies") == cookies
