"""Dictionary source adapters for external tag/localization candidate import."""
from core.dictionary_sources.base import DictionarySourceAdapter
from core.dictionary_sources.danbooru_source import DanbooruSourceAdapter, DanbooruSourceError
from core.dictionary_sources.safebooru_source import SafebooruSourceAdapter, SafebooruSourceError

__all__ = [
    "DictionarySourceAdapter",
    "DanbooruSourceAdapter",
    "DanbooruSourceError",
    "SafebooruSourceAdapter",
    "SafebooruSourceError",
]
