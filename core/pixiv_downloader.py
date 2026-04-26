"""
Pixiv 이미지 다운로더.
httpx를 사용하여 Pixiv CDN(i.pximg.net)에서 이미지를 임시 파일로 받아 rename한다.
"""
from __future__ import annotations

from pathlib import Path


class PixivDownloadError(Exception):
    pass


def download_pixiv_image(
    image_url: str,
    dest_path: str | Path,
    *,
    referer: str,
    cookies: dict | None = None,
    timeout: int = 60,
) -> int:
    """
    Pixiv CDN에서 이미지를 다운로드하여 dest_path에 저장한다.

    임시 파일(.tmp)에 먼저 쓰고 성공 시 dest_path로 rename한다.
    HTTP 오류 / IO 오류 시 PixivDownloadError를 발생시키고 임시 파일을 삭제한다.

    Returns: 다운로드한 바이트 수
    """
    try:
        import httpx
    except ImportError as exc:
        raise PixivDownloadError("httpx 패키지가 필요합니다: pip install httpx") from exc

    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")

    headers = {
        "Referer": referer,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    try:
        with httpx.Client(cookies=cookies or {}, timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", image_url, headers=headers) as resp:
                resp.raise_for_status()
                total = 0
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
                        total += len(chunk)
        tmp.rename(dest)
        return total
    except httpx.HTTPStatusError as exc:
        tmp.unlink(missing_ok=True)
        raise PixivDownloadError(f"HTTP {exc.response.status_code}: {image_url}") from exc
    except PixivDownloadError:
        raise
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise PixivDownloadError(f"다운로드 실패 ({image_url}): {exc}") from exc
