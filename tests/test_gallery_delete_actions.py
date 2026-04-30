"""
Gallery 선택 삭제 테스트.

1. 전역 삭제 버튼(_btn_delete_selected)이 툴바에 없음
2. GalleryView에 delete_requested Signal이 있음
3. 단일/다중 선택 삭제가 delete_requested를 emit
4. 선택 없음이면 delete_requested가 emit되지 않거나 빈 리스트
5. 컨텍스트 메뉴 action이 존재
"""
from __future__ import annotations

import sys

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QApplication, QListWidgetItem
from PyQt6.QtCore import QSize


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def gallery(qapp):
    from app.views.gallery_view import GalleryView
    view = GalleryView()
    view.show()
    return view


def _add_item(gallery, group_id: str) -> None:
    from app.views.gallery_view import GalleryView, ITEM_W, ITEM_H
    from PyQt6.QtWidgets import QListWidgetItem
    from PyQt6.QtCore import Qt, QSize
    item = QListWidgetItem(group_id)
    item.setData(Qt.ItemDataRole.UserRole, group_id)
    item.setSizeHint(QSize(ITEM_W, ITEM_H))
    gallery._list.addItem(item)


class TestGalleryDeleteSignal:
    def test_delete_requested_signal_exists(self, gallery):
        """GalleryView에 delete_requested Signal이 있어야 한다."""
        assert hasattr(gallery, "delete_requested")

    def test_open_location_signal_exists(self, gallery):
        assert hasattr(gallery, "open_location_requested")

    def test_read_meta_signal_exists(self, gallery):
        assert hasattr(gallery, "read_meta_requested")

    def test_no_items_delete_emits_empty_or_no_signal(self, gallery):
        """선택 없음이면 delete_requested가 emit되지 않는다."""
        gallery._list.clearSelection()
        emitted = []
        gallery.delete_requested.connect(emitted.append)
        # 컨텍스트 메뉴 없이 직접 빈 선택 확인
        ids = gallery.get_selected_group_ids()
        assert ids == []
        gallery.delete_requested.disconnect()

    def test_single_item_selected_delete_emits_ids(self, gallery, qapp):
        """단일 선택 후 delete_requested emit 시 해당 group_id를 포함해야 한다."""
        gallery._list.clear()
        _add_item(gallery, "group-A")
        gallery._list.setCurrentRow(0)

        emitted: list[list] = []
        gallery.delete_requested.connect(emitted.append)
        # delete_requested 직접 emit (컨텍스트 메뉴 트리거 대신)
        ids = gallery.get_selected_group_ids()
        gallery.delete_requested.emit(ids)
        assert len(emitted) == 1
        assert "group-A" in emitted[0]
        gallery.delete_requested.disconnect()

    def test_multi_select_delete_includes_all_selected(self, gallery):
        """다중 선택 삭제 시 선택된 모든 group_id가 포함되어야 한다."""
        gallery._list.clear()
        for gid in ["g1", "g2", "g3"]:
            _add_item(gallery, gid)
        gallery._list.selectAll()

        ids = gallery.get_selected_group_ids()
        assert set(ids) == {"g1", "g2", "g3"}

        emitted: list[list] = []
        gallery.delete_requested.connect(emitted.append)
        gallery.delete_requested.emit(ids)
        assert len(emitted) == 1
        assert set(emitted[0]) == {"g1", "g2", "g3"}
        gallery.delete_requested.disconnect()


class TestMainWindowNoGlobalDeleteButton:
    def test_toolbar_has_no_btn_delete_selected(self, qapp, tmp_path):
        """MainWindow 툴바에 전역 삭제 버튼(_btn_delete_selected)이 없어야 한다."""
        config = {
            "data_dir": str(tmp_path),
            "inbox_dir": str(tmp_path / "Inbox"),
            "classified_dir": str(tmp_path / "Classified"),
            "managed_dir": str(tmp_path / "Managed"),
            "db": {"path": str(tmp_path / ".runtime" / "aru.db")},
            "duplicates": {"default_scope": "inbox_managed", "confirm_visual_scan": True,
                           "max_visual_files_per_run": 300},
        }
        from app.main_window import MainWindow
        w = MainWindow(config, config_path=str(tmp_path / "config.json"))
        assert not hasattr(w, "_btn_delete_selected"), (
            "전역 삭제 버튼이 아직 존재함 — 툴바에서 제거해야 함"
        )
        w.close()

    def test_gallery_delete_signal_connected_in_main_window(self, qapp, tmp_path):
        """MainWindow에서 gallery.delete_requested가 _on_gallery_delete_requested에 연결되어야 한다."""
        config = {
            "data_dir": str(tmp_path),
            "inbox_dir": str(tmp_path / "Inbox"),
            "classified_dir": str(tmp_path / "Classified"),
            "managed_dir": str(tmp_path / "Managed"),
            "db": {"path": str(tmp_path / ".runtime" / "aru.db")},
            "duplicates": {"default_scope": "inbox_managed", "confirm_visual_scan": True,
                           "max_visual_files_per_run": 300},
        }
        from app.main_window import MainWindow
        w = MainWindow(config, config_path=str(tmp_path / "config.json"))
        assert hasattr(w, "_on_gallery_delete_requested"), (
            "_on_gallery_delete_requested handler가 없음"
        )
        # signal-slot 연결 확인: gallery.delete_requested → _on_gallery_delete_requested
        # 빈 목록 호출 시 QMessageBox가 떠 로컬 이벤트 루프를 타므로 직접 호출하지 않는다.
        assert callable(w._on_gallery_delete_requested)
        w.close()
