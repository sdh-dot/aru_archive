"""Dictionary source adapter 공통 인터페이스."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DictionarySourceAdapter(ABC):
    """외부 태그 사전 소스의 공통 인터페이스."""

    source_name: str = "unknown"

    @abstractmethod
    def fetch_series_candidates(self, query: str) -> list[dict[str, Any]]:
        """시리즈(copyright) 후보를 조회한다."""
        ...

    @abstractmethod
    def fetch_character_candidates(
        self,
        series: str,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        """캐릭터 후보를 조회한다."""
        ...
