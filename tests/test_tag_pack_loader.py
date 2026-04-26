"""core/tag_pack_loader.py 테스트."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from db.database import initialize_database


@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    yield c
    c.close()


@pytest.fixture
def blue_archive_pack():
    """실제 blue_archive.json 로드."""
    pack_path = Path(__file__).parent.parent / "resources" / "tag_packs" / "blue_archive.json"
    from core.tag_pack_loader import load_tag_pack
    return load_tag_pack(pack_path)


class TestLoadTagPack:
    def test_load_blue_archive_json(self, blue_archive_pack) -> None:
        pack = blue_archive_pack
        assert pack["pack_id"] == "blue_archive"
        assert pack["name"] == "Blue Archive"
        assert "series" in pack
        assert "characters" in pack

    def test_load_from_path_string(self, tmp_path) -> None:
        pack_data = {
            "pack_id": "test", "name": "Test", "version": "1.0",
            "source": "test", "series": [], "characters": [],
        }
        p = tmp_path / "test_pack.json"
        p.write_text(json.dumps(pack_data), encoding="utf-8")
        from core.tag_pack_loader import load_tag_pack
        result = load_tag_pack(str(p))
        assert result["pack_id"] == "test"


class TestValidateTagPack:
    def test_valid_pack_passes(self, blue_archive_pack) -> None:
        from core.tag_pack_loader import validate_tag_pack
        validate_tag_pack(blue_archive_pack)  # 예외 없어야 함

    def test_missing_pack_id_raises(self) -> None:
        from core.tag_pack_loader import validate_tag_pack
        with pytest.raises(ValueError, match="pack_id"):
            validate_tag_pack({"name": "X", "version": "1.0"})

    def test_missing_name_raises(self) -> None:
        from core.tag_pack_loader import validate_tag_pack
        with pytest.raises(ValueError, match="name"):
            validate_tag_pack({"pack_id": "x", "version": "1.0"})

    def test_missing_version_raises(self) -> None:
        from core.tag_pack_loader import validate_tag_pack
        with pytest.raises(ValueError, match="version"):
            validate_tag_pack({"pack_id": "x", "name": "X"})

    def test_series_must_be_list(self) -> None:
        from core.tag_pack_loader import validate_tag_pack
        with pytest.raises(ValueError, match="series"):
            validate_tag_pack({"pack_id": "x", "name": "X", "version": "1", "series": "bad"})


class TestSeedTagPack:
    def test_seed_inserts_series_aliases(self, conn, blue_archive_pack) -> None:
        from core.tag_pack_loader import seed_tag_pack
        result = seed_tag_pack(conn, blue_archive_pack)
        assert result["series_aliases"] > 0

        aliases = {r[0] for r in conn.execute(
            "SELECT alias FROM tag_aliases WHERE tag_type = 'series'"
        ).fetchall()}
        assert "ブルーアーカイブ" in aliases
        assert "BlueArchive" in aliases
        assert "블루 아카이브" in aliases

    def test_seed_inserts_character_aliases(self, conn, blue_archive_pack) -> None:
        from core.tag_pack_loader import seed_tag_pack
        result = seed_tag_pack(conn, blue_archive_pack)
        assert result["character_aliases"] > 0

        aliases = {r[0] for r in conn.execute(
            "SELECT alias FROM tag_aliases WHERE tag_type = 'character'"
        ).fetchall()}
        assert "伊落マリー" in aliases
        assert "Iochi Mari" in aliases
        assert "陸八魔アル" in aliases

    def test_seed_inserts_localizations(self, conn, blue_archive_pack) -> None:
        from core.tag_pack_loader import seed_tag_pack
        result = seed_tag_pack(conn, blue_archive_pack)
        assert result["localizations"] > 0

        locs = {(r[0], r[1]) for r in conn.execute(
            "SELECT canonical, locale FROM tag_localizations"
        ).fetchall()}
        assert ("Blue Archive", "ko") in locs
        assert ("Blue Archive", "ja") in locs

    def test_seed_source_tag(self, conn, blue_archive_pack) -> None:
        from core.tag_pack_loader import seed_tag_pack
        seed_tag_pack(conn, blue_archive_pack)
        row = conn.execute(
            "SELECT source FROM tag_aliases WHERE alias = 'ブルーアーカイブ'"
        ).fetchone()
        assert row is not None
        assert row[0] == "built_in_pack:blue_archive"

    def test_seed_character_parent_series(self, conn, blue_archive_pack) -> None:
        from core.tag_pack_loader import seed_tag_pack
        seed_tag_pack(conn, blue_archive_pack)
        row = conn.execute(
            "SELECT parent_series FROM tag_aliases WHERE alias = '伊落マリー'"
        ).fetchone()
        assert row is not None
        assert row[0] == "Blue Archive"

    def test_reseed_no_duplicates(self, conn, blue_archive_pack) -> None:
        from core.tag_pack_loader import seed_tag_pack
        r1 = seed_tag_pack(conn, blue_archive_pack)
        r2 = seed_tag_pack(conn, blue_archive_pack)
        # 두 번째 시드는 0개 삽입 (INSERT OR IGNORE)
        assert r2["series_aliases"] == 0
        assert r2["character_aliases"] == 0
        assert r2["localizations"] == 0

        # DB 총 개수는 첫 번째와 동일
        total = conn.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0]
        assert total == r1["series_aliases"] + r1["character_aliases"]

    def test_seed_builtin_packs(self, conn) -> None:
        from core.tag_pack_loader import seed_builtin_tag_packs
        result = seed_builtin_tag_packs(conn)
        assert result["series_aliases"] > 0
        assert result["character_aliases"] > 0
