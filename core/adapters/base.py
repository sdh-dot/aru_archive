"""소스 사이트 어댑터 추상 인터페이스."""
from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import AruMetadata


class SourceSiteAdapter(ABC):
    """
    소스 사이트별 파싱/다운로드 전략을 정의하는 추상 클래스.
    새 사이트 추가 시 이 클래스를 상속하고 core/adapters/__init__.py의
    _ADAPTERS 리스트에 등록한다.
    """

    site_name: str = ""

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """이 어댑터가 처리할 수 있는 URL인지 확인."""
        ...

    @abstractmethod
    def parse_page_data(self, raw_data: dict) -> AruMetadata:
        """브라우저 확장이 수집한 raw_data를 AruMetadata로 변환."""
        ...

    @abstractmethod
    def build_download_targets(
        self, metadata: AruMetadata, page_data: list[dict]
    ) -> list[dict]:
        """
        다운로드 대상 목록 생성.
        각 항목: {page_index: int, url: str, filename: str, width: int, height: int}
        """
        ...

    @abstractmethod
    def get_http_headers(self) -> dict[str, str]:
        """다운로드 시 사용할 HTTP 헤더."""
        ...
