"""Pixiv 소스 사이트 어댑터."""
from __future__ import annotations

from datetime import datetime, timezone

from core.adapters.base import SourceSiteAdapter
from core.models import AruMetadata


# ---------------------------------------------------------------------------
# 예외 계층
# ---------------------------------------------------------------------------

class PixivFetchError(Exception):
    """Pixiv API가 오류 응답을 반환했거나 예상치 못한 상태."""

class PixivNetworkError(PixivFetchError):
    """네트워크 수준 오류 (타임아웃, 연결 거부 등)."""

class PixivRestrictedError(PixivFetchError):
    """작품 접근 제한 (로그인 필요 또는 R-18 차단)."""

class PixivParseError(PixivFetchError):
    """응답 body를 AruMetadata로 변환할 수 없음."""


class PixivAdapter(SourceSiteAdapter):
    """
    Pixiv 전용 어댑터.
    content_script가 수집한 preload_data를 AruMetadata로 변환하고,
    다운로드 대상 URL 목록을 생성한다.
    """

    site_name = "pixiv"

    def can_handle(self, url: str) -> bool:
        return "pixiv.net" in url

    def parse_page_data(self, raw_data: dict) -> AruMetadata:
        """
        Pixiv preload_data 구조를 AruMetadata로 변환.
        raw_data: {
            artwork_id, illust: {title, tags: {tags: [{tag}]}},
            user: {userId, name},
            is_ugoira, ...
        }
        """
        artwork_id = str(raw_data.get("artwork_id", ""))
        illust = raw_data.get("illust", {})
        user = raw_data.get("user", {})

        tags_raw = illust.get("tags", {}).get("tags", [])
        tags = [t.get("tag", "") for t in tags_raw if t.get("tag")]

        now = datetime.now(timezone.utc).isoformat()

        return AruMetadata(
            source_site=self.site_name,
            artwork_id=artwork_id,
            artwork_url=f"https://www.pixiv.net/artworks/{artwork_id}",
            artwork_title=illust.get("title", ""),
            artist_id=str(user.get("userId", "")),
            artist_name=user.get("name", ""),
            artist_url=f"https://www.pixiv.net/users/{user.get('userId', '')}",
            tags=tags,
            is_ugoira=bool(raw_data.get("is_ugoira", False)),
            downloaded_at=now,
            _provenance={
                "source": "extension_dom",
                "confidence": "high",
                "captured_at": now,
            },
        )

    def build_download_targets(
        self, metadata: AruMetadata, page_data: list[dict]
    ) -> list[dict]:
        """
        Pixiv /ajax/illust/{id}/pages 응답을 다운로드 대상으로 변환.
        page_data 각 항목: {urls: {original: ...}, width, height}
        """
        targets = []
        for i, page in enumerate(page_data):
            url = page.get("urls", {}).get("original", "")
            ext = url.rsplit(".", 1)[-1] if "." in url else "jpg"
            filename = f"{metadata.artwork_id}_p{i}.{ext}"
            targets.append(
                {
                    "page_index": i,
                    "url": url,
                    "filename": filename,
                    "width": page.get("width", 0),
                    "height": page.get("height", 0),
                }
            )
        return targets

    def get_http_headers(self) -> dict[str, str]:
        return {
            "Referer": "https://www.pixiv.net",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }

    # ------------------------------------------------------------------
    # HTTP fetch (MVP-B)
    # ------------------------------------------------------------------

    def fetch_metadata(self, artwork_id: str) -> dict:
        """
        Pixiv AJAX API로 일러스트 메타데이터를 가져온다.

        URL: https://www.pixiv.net/ajax/illust/{artwork_id}?lang=ja

        Returns: raw body dict (illustId, title, tags, userId, userName, …)
        Raises:
            PixivNetworkError   — 타임아웃 / 연결 오류
            PixivRestrictedError — HTTP 403
            PixivFetchError     — HTTP 404 / API error:true / 기타 HTTP 오류
            PixivParseError     — JSON 파싱 실패 / body 구조 불일치
        """
        try:
            import httpx
        except ImportError as exc:
            raise PixivNetworkError(
                "httpx 패키지가 필요합니다: pip install httpx"
            ) from exc

        url = f"https://www.pixiv.net/ajax/illust/{artwork_id}?lang=ja"
        try:
            with httpx.Client(headers=self.get_http_headers(), timeout=15.0) as client:
                resp = client.get(url)
        except httpx.TimeoutException as exc:
            raise PixivNetworkError(f"Pixiv 요청 타임아웃: {exc}") from exc
        except httpx.NetworkError as exc:
            raise PixivNetworkError(f"Pixiv 네트워크 오류: {exc}") from exc

        if resp.status_code == 403:
            raise PixivRestrictedError(
                f"Pixiv 접근 제한 (403): artwork_id={artwork_id}"
            )
        if resp.status_code == 404:
            raise PixivFetchError(
                f"Pixiv 아트워크를 찾을 수 없음 (404): artwork_id={artwork_id}"
            )
        if resp.status_code != 200:
            raise PixivFetchError(
                f"Pixiv API 오류 HTTP {resp.status_code}: artwork_id={artwork_id}"
            )

        try:
            data = resp.json()
        except Exception as exc:
            raise PixivParseError(f"Pixiv 응답 JSON 파싱 실패: {exc}") from exc

        if data.get("error"):
            raise PixivFetchError(
                f"Pixiv API 오류: {data.get('message', 'unknown')}"
            )

        body = data.get("body")
        if not isinstance(body, dict):
            raise PixivParseError(
                f"Pixiv API 응답 body 구조 불일치: {type(body)}"
            )

        return body

    def to_aru_metadata(
        self,
        raw: dict,
        page_index: int = 0,
        original_filename: str = "",
    ) -> AruMetadata:
        """
        fetch_metadata() 반환값(body dict)을 AruMetadata로 변환한다.

        raw keys: illustId, title, tags.tags, userId, userName,
                  pageCount, illustType (2=ugoira), xRestrict
        """
        from core.tag_classifier import classify_pixiv_tags

        artwork_id = str(raw.get("illustId", ""))
        user_id    = str(raw.get("userId", ""))
        tags_raw   = raw.get("tags", {}).get("tags", [])
        all_tags   = [t.get("tag", "") for t in tags_raw if t.get("tag")]
        classified = classify_pixiv_tags(all_tags)
        page_count = int(raw.get("pageCount", 1))
        is_ugoira  = int(raw.get("illustType", 0)) == 2
        now        = datetime.now(timezone.utc).isoformat()

        return AruMetadata(
            source_site=self.site_name,
            artwork_id=artwork_id,
            artwork_url=f"https://www.pixiv.net/artworks/{artwork_id}",
            artwork_title=raw.get("title", ""),
            page_index=page_index,
            total_pages=page_count,
            original_filename=original_filename,
            artist_id=user_id,
            artist_name=raw.get("userName", ""),
            artist_url=f"https://www.pixiv.net/users/{user_id}",
            tags=classified["tags"],
            series_tags=classified["series_tags"],
            character_tags=classified["character_tags"],
            is_ugoira=is_ugoira,
            downloaded_at=now,
            _provenance={
                "source": "pixiv_ajax_api",
                "confidence": "high",
                "captured_at": now,
            },
        )
