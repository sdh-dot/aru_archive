"""첫 실행 폴더 설정 dialog 회귀 테스트 (PR #122 follow-up).

검증 contract:
- input_dir / output_dir 가 독립 picker 로 선택된다 — sibling 자동 파생 없음.
- 관리 폴더 = ``Path.home() / 'AruArchive'`` (또는 명시 app_data_dir) 로 표시.
- managed_dir = ``app_data_dir / 'managed'`` — 사용자 input 의 sibling 이 아니다.
- OK 는 input + output 모두 채워졌을 때만 활성.
- 기존 "Classified / Managed 폴더가 자동 생성됩니다" 문구가 dialog 에 남아 있지 않다.
- 같은 경로 선택 시 경고 표시 (허용은 함).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from app.views.path_setup_dialog import PathSetupDialog


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _make_dialog(
    *,
    start_input_dir: str = "",
    start_output_dir: str = "",
    app_data_dir: str = "",
) -> PathSetupDialog:
    return PathSetupDialog(
        start_input_dir=start_input_dir,
        start_output_dir=start_output_dir,
        app_data_dir=app_data_dir or str(Path.home() / "AruArchive"),
    )


# ---------------------------------------------------------------------------
# Test 1: input/output independent
# ---------------------------------------------------------------------------

class TestInputOutputIndependent:
    def test_1_no_auto_derive_from_input(self, qapp, tmp_path: Path) -> None:
        """input 만 선택했을 때 output 이 자동으로 input/Classified 로 강제되지 않는다."""
        input_path = tmp_path / "아루"
        input_path.mkdir()
        dlg = _make_dialog()
        try:
            dlg._selected_input = str(input_path)
            dlg._input_lbl.setText(str(input_path))
            dlg._summary_input_lbl.setText(str(input_path))
            dlg._refresh_state()
            # output 은 여전히 비어 있어야 한다.
            assert dlg._selected_output == "", (
                "input 선택만으로 output 이 자동 설정됨"
            )
            # OK 는 비활성 (output 미설정).
            assert dlg._ok_btn.isEnabled() is False
            # selected_paths() 는 빈 dict 반환.
            assert dlg.selected_paths() == {}
        finally:
            dlg.close()

    def test_input_change_does_not_change_output(self, qapp, tmp_path: Path) -> None:
        in1 = tmp_path / "Inbox1"; in1.mkdir()
        in2 = tmp_path / "Inbox2"; in2.mkdir()
        out = tmp_path / "OutputUserChoice"; out.mkdir()
        dlg = _make_dialog(
            start_input_dir=str(in1), start_output_dir=str(out)
        )
        try:
            assert dlg._selected_input  == str(in1)
            assert dlg._selected_output == str(out)
            # input 만 변경.
            dlg._selected_input = str(in2)
            dlg._input_lbl.setText(str(in2))
            dlg._summary_input_lbl.setText(str(in2))
            dlg._refresh_state()
            assert dlg._selected_output == str(out), (
                "input 변경이 output 을 건드림"
            )
        finally:
            dlg.close()


# ---------------------------------------------------------------------------
# Test 2: managed_dir 표시
# ---------------------------------------------------------------------------

class TestManagedFolderDisplay:
    def test_2_managed_folder_is_app_data_dir_not_input_sibling(
        self, qapp, tmp_path: Path
    ) -> None:
        r"""input 을 D:\아루로 선택해도 관리 폴더가 D:\Managed 로 표시되지 않는다."""
        input_path = tmp_path / "아루"
        input_path.mkdir()
        custom_app_data = tmp_path / "AruArchive"  # Path.home() 대신 tmp 격리.
        dlg = _make_dialog(
            start_input_dir=str(input_path),
            app_data_dir=str(custom_app_data),
        )
        try:
            managed_text = dlg._summary_managed_lbl.text()
            assert managed_text == str(custom_app_data), (
                f"관리 폴더 표시가 app_data_dir 가 아님: {managed_text!r}"
            )
            # input 의 부모 sibling 이름이 새 나오지 않아야 한다.
            assert "Managed" not in str(input_path.parent), "테스트 전제 깨짐"
            assert "Managed" not in managed_text or managed_text.startswith(
                str(custom_app_data)
            ), f"관리 폴더가 input sibling 으로 잘못 표시됨: {managed_text}"
        finally:
            dlg.close()

    def test_managed_dir_in_paths_is_app_data_managed(
        self, qapp, tmp_path: Path
    ) -> None:
        """selected_paths() 의 managed_dir 가 app_data_dir / 'managed'."""
        input_path = tmp_path / "아루"; input_path.mkdir()
        output_path = tmp_path / "Output"; output_path.mkdir()
        custom_app_data = tmp_path / "AruArchive"
        dlg = _make_dialog(
            start_input_dir=str(input_path),
            start_output_dir=str(output_path),
            app_data_dir=str(custom_app_data),
        )
        try:
            paths = dlg.selected_paths()
            assert paths["managed_dir"] == str(custom_app_data / "managed")
            assert paths["app_data_dir"] == str(custom_app_data)
            # input/output 도 정확히 분리.
            assert paths["input_dir"]  == str(input_path)
            assert paths["output_dir"] == str(output_path)
            # legacy alias 도 동기화돼서 반환된다.
            assert paths["inbox_dir"]      == str(input_path)
            assert paths["classified_dir"] == str(output_path)
        finally:
            dlg.close()


# ---------------------------------------------------------------------------
# Test 3: OK gating
# ---------------------------------------------------------------------------

class TestOkGating:
    def test_3a_ok_disabled_without_output(self, qapp, tmp_path: Path) -> None:
        in_path = tmp_path / "Inbox"; in_path.mkdir()
        dlg = _make_dialog(start_input_dir=str(in_path))
        try:
            assert dlg._ok_btn.isEnabled() is False
            # selected_paths() 도 비어 있어야 한다.
            assert dlg.selected_paths() == {}
        finally:
            dlg.close()

    def test_3b_ok_disabled_without_input(self, qapp, tmp_path: Path) -> None:
        out = tmp_path / "Output"; out.mkdir()
        dlg = _make_dialog(start_output_dir=str(out))
        try:
            assert dlg._ok_btn.isEnabled() is False
            assert dlg.selected_paths() == {}
        finally:
            dlg.close()

    def test_3c_ok_enabled_with_both(self, qapp, tmp_path: Path) -> None:
        in_path = tmp_path / "Inbox"; in_path.mkdir()
        out     = tmp_path / "Output"; out.mkdir()
        dlg = _make_dialog(
            start_input_dir=str(in_path), start_output_dir=str(out)
        )
        try:
            assert dlg._ok_btn.isEnabled() is True
            paths = dlg.selected_paths()
            assert paths
            assert paths["input_dir"]  == str(in_path)
            assert paths["output_dir"] == str(out)
        finally:
            dlg.close()

    def test_same_path_warning_visible(self, qapp, tmp_path: Path) -> None:
        same = tmp_path / "SameFolder"; same.mkdir()
        dlg = _make_dialog(
            start_input_dir=str(same), start_output_dir=str(same),
        )
        try:
            # 경고 라벨이 채워져야 한다 (허용은 됨 — OK 도 활성).
            # offscreen 모드에서 isVisible() 은 dialog show() 전에 False 를
            # 반환하므로 텍스트 / setVisible 호출 결과로 검증한다.
            assert dlg._ok_btn.isEnabled() is True
            assert "분류 대상 폴더와 분류 완료 폴더가 같습니다" in dlg._warn_same_lbl.text()
            assert dlg._warn_same_lbl.isHidden() is False
        finally:
            dlg.close()


# ---------------------------------------------------------------------------
# Test 4: 기존 문구 제거
# ---------------------------------------------------------------------------

class TestLegacyCopyRemoved:
    def test_4_no_auto_classified_managed_wording(self, qapp) -> None:
        """`Classified` / `Managed` 폴더 자동 생성 문구가 dialog 어디에도
        남아 있지 않아야 한다."""
        dlg = _make_dialog()
        try:
            # 모든 QLabel 의 text 를 모아 검사.
            all_labels = dlg.findChildren(QLabel)
            joined = "\n".join(lbl.text() for lbl in all_labels)
            forbidden = [
                "`Classified`, `Managed` 폴더가 자동 생성",
                "Classified, Managed 폴더가 자동 생성",
                "같은 위치에 `Classified`",
                "같은 위치에 Classified",
                "분류 결과는 `Classified`",
                "관리본은 `Managed`",
            ]
            for needle in forbidden:
                assert needle not in joined, (
                    f"제거 대상 문구가 dialog 에 남아 있음: {needle!r}"
                )
            # 새 안내 문구가 있는지 확인 — 분류 대상 / 분류 완료 각각 선택.
            assert "분류 대상 폴더와 분류 완료 폴더를 각각 선택" in joined
        finally:
            dlg.close()

    def test_dialog_has_two_pickers(self, qapp) -> None:
        dlg = _make_dialog()
        try:
            input_btn  = dlg.findChild(QPushButton, "btnPickInputDir")
            output_btn = dlg.findChild(QPushButton, "btnPickOutputDir")
            assert input_btn  is not None, "분류 대상 picker 가 없음"
            assert output_btn is not None, "분류 완료 picker 가 없음"
            assert "분류 대상" in input_btn.text()
            assert "분류 완료" in output_btn.text()
        finally:
            dlg.close()


# ---------------------------------------------------------------------------
# Test 5: managed_dir 의미 (app_data_dir / 'managed')
# ---------------------------------------------------------------------------

class TestManagedDirSemantics:
    def test_5_managed_dir_equals_app_data_dir_managed(
        self, qapp, tmp_path: Path
    ) -> None:
        custom_app_data = tmp_path / "AruArchive"
        in_path  = tmp_path / "Inbox"; in_path.mkdir()
        out_path = tmp_path / "OutputUser"; out_path.mkdir()

        dlg = _make_dialog(
            start_input_dir=str(in_path),
            start_output_dir=str(out_path),
            app_data_dir=str(custom_app_data),
        )
        try:
            paths = dlg.selected_paths()
            # managed_dir 는 항상 app_data_dir / 'managed'. output_dir 와 다름.
            assert paths["managed_dir"] == str(custom_app_data / "managed")
            assert paths["managed_dir"] != paths["output_dir"]
            # 사용자가 출력 폴더를 어떻게 고르더라도 managed_dir 는 변하지 않음.
        finally:
            dlg.close()

    def test_managed_dir_independent_of_output_choice(
        self, qapp, tmp_path: Path
    ) -> None:
        custom_app_data = tmp_path / "AruArchive"
        in_path = tmp_path / "Inbox"; in_path.mkdir()
        first_out  = tmp_path / "Out1"; first_out.mkdir()
        second_out = tmp_path / "Out2"; second_out.mkdir()

        dlg = _make_dialog(
            start_input_dir=str(in_path),
            start_output_dir=str(first_out),
            app_data_dir=str(custom_app_data),
        )
        try:
            first_managed = dlg.selected_paths()["managed_dir"]
            # output 변경.
            dlg._selected_output = str(second_out)
            dlg._output_lbl.setText(str(second_out))
            dlg._summary_output_lbl.setText(str(second_out))
            dlg._refresh_state()
            second_managed = dlg.selected_paths()["managed_dir"]
            assert first_managed == second_managed, (
                "output 변경이 managed_dir 에 영향을 줌"
            )
            assert first_managed == str(custom_app_data / "managed")
        finally:
            dlg.close()


# ---------------------------------------------------------------------------
# Backward-compat alias keyword 보장 (legacy callers 가 start_dir / data_dir
# 형식으로 호출해도 작동).
# ---------------------------------------------------------------------------

class TestLegacyAliasConstructor:
    def test_legacy_start_dir_data_dir_alias(self, qapp, tmp_path: Path) -> None:
        in_path = tmp_path / "Legacy"; in_path.mkdir()
        custom_app_data = tmp_path / "AruArchive"
        dlg = PathSetupDialog(
            start_dir=str(in_path),
            data_dir=str(custom_app_data),
        )
        try:
            assert dlg._selected_input == str(in_path)
            assert dlg._app_data_dir   == str(custom_app_data)
            # output 미선택 상태이므로 selected_paths 는 빈 dict.
            assert dlg.selected_paths() == {}
            assert dlg._ok_btn.isEnabled() is False
        finally:
            dlg.close()
