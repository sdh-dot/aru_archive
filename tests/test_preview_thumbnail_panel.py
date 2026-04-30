"""
썸네일 패널 / PreviewThumbnailCache 테스트.

1. PreviewThumbnailCache 인스턴스를 생성할 수 있다
2. 실제 이미지 파일에서 QPixmap 썸네일을 생성한다
3. 존재하지 않는 파일은 None 반환 (placeholder)
4. 캐시에 저장된 항목은 파일을 다시 읽지 않는다 (LRU)
5. _Step7Preview에 _thumb_lbl 위젯이 존재한다
6. _on_preview_row_changed가 빈 rows에서도 안전하게 동작한다
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")

from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _make_png(path: Path) -> Path:
    """최소한의 유효한 1×1 흰색 PNG를 생성한다."""
    def _chunk(tag: bytes, data: bytes) -> bytes:
        c = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", c)

    sig  = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw  = b"\x00\xff\xff\xff"
    idat = _chunk(b"IDAT", zlib.compress(raw))
    iend = _chunk(b"IEND", b"")
    path.write_bytes(sig + ihdr + idat + iend)
    return path


def _make_wizard(tmp_path):
    from db.database import initialize_database

    db_path = str(tmp_path / "aru.db")
    conn = initialize_database(db_path)
    conn.close()

    config = {
        "classified_dir": str(tmp_path / "Classified"),
        "classification": {"folder_locale": "ko"},
    }

    class _MockWizard:
        _config = config

        def _conn_factory(self):
            return initialize_database(db_path)

        def _db_path(self):
            return db_path

    return _MockWizard()


class TestPreviewThumbnailCache:
    def test_instantiation(self, qapp):
        from app.views.workflow_wizard_view import PreviewThumbnailCache
        cache = PreviewThumbnailCache(max_items=10)
        assert cache._max == 10
        assert len(cache._cache) == 0

    def test_load_real_image(self, qapp, tmp_path):
        from app.views.workflow_wizard_view import PreviewThumbnailCache
        img = _make_png(tmp_path / "test.png")
        cache = PreviewThumbnailCache(max_items=10)
        px = cache.load(str(img))
        assert px is not None
        assert not px.isNull()
        assert px.width() <= 160
        assert px.height() <= 160

    def test_missing_file_returns_none(self, qapp, tmp_path):
        from app.views.workflow_wizard_view import PreviewThumbnailCache
        cache = PreviewThumbnailCache(max_items=10)
        result = cache.load(str(tmp_path / "nonexistent.jpg"))
        assert result is None

    def test_empty_path_returns_none(self, qapp):
        from app.views.workflow_wizard_view import PreviewThumbnailCache
        cache = PreviewThumbnailCache(max_items=10)
        assert cache.load("") is None

    def test_cache_hit_returns_same_object(self, qapp, tmp_path):
        """동일 경로 2회 요청 시 동일 QPixmap 객체를 반환해야 한다."""
        from app.views.workflow_wizard_view import PreviewThumbnailCache
        img = _make_png(tmp_path / "cached.png")
        cache = PreviewThumbnailCache(max_items=10)
        px1 = cache.load(str(img))
        px2 = cache.load(str(img))
        assert px1 is px2

    def test_lru_eviction(self, qapp, tmp_path):
        """max_items 초과 시 가장 오래된 항목이 제거된다."""
        from app.views.workflow_wizard_view import PreviewThumbnailCache
        cache = PreviewThumbnailCache(max_items=2)
        imgs = [_make_png(tmp_path / f"img{i}.png") for i in range(3)]
        p0 = cache.load(str(imgs[0]))
        cache.load(str(imgs[1]))
        cache.load(str(imgs[2]))
        # imgs[0]은 LRU에서 제거돼 cache miss → 다시 읽어야 함 (다른 객체)
        p0_again = cache.load(str(imgs[0]))
        assert p0 is not p0_again

    def test_max_items_respected(self, qapp, tmp_path):
        from app.views.workflow_wizard_view import PreviewThumbnailCache
        cache = PreviewThumbnailCache(max_items=3)
        for i in range(5):
            img = _make_png(tmp_path / f"lru{i}.png")
            cache.load(str(img))
        assert len(cache._cache) == 3


class TestStep7ThumbnailPanel:
    @pytest.fixture()
    def step7(self, qapp, tmp_path):
        from app.views.workflow_wizard_view import _Step7Preview
        wizard = _make_wizard(tmp_path)
        step = _Step7Preview(wizard)
        step.show()
        return step

    def test_thumb_lbl_exists(self, step7):
        assert hasattr(step7, "_thumb_lbl")

    def test_thumb_cache_exists(self, step7):
        assert hasattr(step7, "_thumb_cache")

    def test_on_row_changed_negative_index_safe(self, step7):
        step7._preview_rows.clear()
        step7._on_preview_row_changed(-1)  # should not raise

    def test_on_row_changed_out_of_bounds_safe(self, step7):
        step7._preview_rows.clear()
        step7._on_preview_row_changed(99)  # should not raise

    def test_on_row_changed_missing_file_shows_placeholder(self, step7, tmp_path):
        step7._preview_rows = [{"source_path": str(tmp_path / "ghost.jpg")}]
        step7._on_preview_row_changed(0)
        # 파일 없으면 pixmap이 None이거나 placeholder 텍스트가 설정돼야 한다
        px = step7._thumb_lbl.pixmap()
        txt = step7._thumb_lbl.text()
        assert (px is None or px.isNull()) or txt != ""

    def test_on_row_changed_real_image_sets_pixmap(self, step7, tmp_path):
        img = _make_png(tmp_path / "thumb_test.png")
        step7._preview_rows = [{"source_path": str(img)}]
        step7._on_preview_row_changed(0)
        px = step7._thumb_lbl.pixmap()
        assert px is not None and not px.isNull()
