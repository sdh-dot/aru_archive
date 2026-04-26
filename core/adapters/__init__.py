"""
소스 사이트 어댑터 레지스트리.
새 사이트 어댑터 추가 시 _ADAPTERS 리스트에 인스턴스를 추가한다.

X(트위터) 어댑터: Post-MVP.
"""
from __future__ import annotations

from core.adapters.base import SourceSiteAdapter
from core.adapters.pixiv import PixivAdapter

_ADAPTERS: list[SourceSiteAdapter] = [
    PixivAdapter(),
    # XAdapter(),  # Post-MVP
]


def get_adapter(url: str) -> SourceSiteAdapter | None:
    """URL에 맞는 어댑터를 반환한다. 매칭 없으면 None."""
    for adapter in _ADAPTERS:
        if adapter.can_handle(url):
            return adapter
    return None
