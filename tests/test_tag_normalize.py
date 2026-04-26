"""core/tag_normalize.py 테스트."""
from __future__ import annotations

import pytest

from core.tag_normalize import normalize_tag_key


class TestNormalizeTagKey:
    def test_empty_string_returns_empty(self) -> None:
        assert normalize_tag_key("") == ""

    def test_none_like_empty(self) -> None:
        # 함수는 str만 받지만 빈 문자열은 빈 값 반환
        assert normalize_tag_key("") == ""

    def test_simple_ascii_lowercase(self) -> None:
        assert normalize_tag_key("Hello") == "hello"

    def test_spaces_removed(self) -> None:
        assert normalize_tag_key("Blue Archive") == "bluearchive"

    def test_underscores_removed(self) -> None:
        assert normalize_tag_key("Blue_Archive") == "bluearchive"

    def test_hyphens_removed(self) -> None:
        assert normalize_tag_key("Blue-Archive") == "bluearchive"

    def test_slash_removed(self) -> None:
        assert normalize_tag_key("Blue/Archive") == "bluearchive"

    def test_nakaguro_removed(self) -> None:
        # 중점 (·)
        assert normalize_tag_key("リクハチマ·アル") == "リクハチマアル"

    def test_katakana_nakaguro_removed(self) -> None:
        # 가타카나 중점 (・)
        assert normalize_tag_key("リクハチマ・アル") == "リクハチマアル"

    def test_fullwidth_ascii_nfkc(self) -> None:
        # ＢｌｕｅＡｒｃｈｉｖｅ → BlueArchive (NFKC) → bluearchive (casefold)
        assert normalize_tag_key("ＢｌｕｅＡｒｃｈｉｖｅ") == "bluearchive"

    def test_blue_archive_variants_all_same(self) -> None:
        """Blue Archive / BlueArchive / ＢｌｕｅＡｒｃｈｉｖｅ 모두 동일 키."""
        key1 = normalize_tag_key("Blue Archive")
        key2 = normalize_tag_key("BlueArchive")
        key3 = normalize_tag_key("ＢｌｕｅＡｒｃｈｉｖｅ")
        assert key1 == key2 == key3 == "bluearchive"

    def test_leading_trailing_spaces_stripped(self) -> None:
        assert normalize_tag_key("  hello  ") == "hello"

    def test_mixed_separators(self) -> None:
        assert normalize_tag_key("Blue_Archive-2") == "bluearchive2"

    def test_japanese_unchanged_except_nfkc(self) -> None:
        # 일본어 문자는 제거되지 않음
        key = normalize_tag_key("ブルーアーカイブ")
        assert key == "ブルーアーカイブ"

    def test_korean_unchanged(self) -> None:
        key = normalize_tag_key("블루 아카이브")
        assert key == "블루아카이브"
