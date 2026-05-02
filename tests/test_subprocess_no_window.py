"""
Windows release build 에서 subprocess 자식 콘솔이 깜빡이는 사고 (메타데이터 입력
중 cmd 창 반복 출력) 재발 방지 회귀 테스트.

검증:
1. ``no_window_kwargs()`` 가 Windows 에서는 CREATE_NO_WINDOW 를 포함하고
   다른 OS 에서는 빈 dict 를 반환한다.
2. ExifTool 을 spawn 하는 모든 ``subprocess.run`` 호출이 helper 를 사용한다.
   AST 로 호출만 추출하므로 docstring 안의 언급은 무시된다.
3. Windows 에서 launch 되는 ``subprocess.Popen(["explorer", ...])`` 호출도
   helper 를 사용한다.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# helper 단위 테스트
# ---------------------------------------------------------------------------

def test_no_window_kwargs_empty_on_non_windows():
    from core.subprocess_util import no_window_kwargs

    with mock.patch.object(os, "name", "posix"):
        assert no_window_kwargs() == {}


def test_no_window_kwargs_sets_create_no_window_on_windows():
    from core.subprocess_util import no_window_kwargs

    flag = getattr(subprocess, "CREATE_NO_WINDOW", None)
    if flag is None:
        with mock.patch.object(os, "name", "nt"), mock.patch.object(
            subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True
        ):
            assert no_window_kwargs() == {"creationflags": 0x08000000}
        return

    with mock.patch.object(os, "name", "nt"):
        assert no_window_kwargs() == {"creationflags": flag}


def test_subprocess_util_does_not_break_helper_run():
    """helper kwargs 가 stdlib subprocess 와 호환되는지 실 호출로 검증."""
    from core.subprocess_util import no_window_kwargs

    proc = subprocess.run(
        [sys.executable, "-c", "pass"],
        capture_output=True,
        timeout=10,
        **no_window_kwargs(),
    )
    assert proc.returncode == 0


# ---------------------------------------------------------------------------
# AST source-inspection 가드
# ---------------------------------------------------------------------------

def _ast_calls(rel_path: str) -> tuple[ast.Module, list[ast.Call]]:
    text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    tree = ast.parse(text)
    return tree, [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


def _is_subprocess_attr(call: ast.Call, attr: str) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == attr
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
    )


def _has_no_window_helper(call: ast.Call) -> bool:
    """call 의 ``**kwargs`` 또는 명시 ``creationflags=...`` 가 helper 를 통해 주입됐는지 검사."""
    for kw in call.keywords:
        # ``**no_window_kwargs()`` → keyword.arg is None
        if kw.arg is None and isinstance(kw.value, ast.Call):
            inner_func = kw.value.func
            if isinstance(inner_func, ast.Name) and inner_func.id == "no_window_kwargs":
                return True
            if isinstance(inner_func, ast.Attribute) and inner_func.attr == "no_window_kwargs":
                return True
    return False


def _is_explorer_popen(call: ast.Call) -> bool:
    """첫 인자가 list 이고 첫 element 가 'explorer' 문자열인 Popen."""
    if not _is_subprocess_attr(call, "Popen"):
        return False
    if not call.args:
        return False
    first = call.args[0]
    if not isinstance(first, ast.List) or not first.elts:
        return False
    head = first.elts[0]
    return isinstance(head, ast.Constant) and head.value == "explorer"


def _assert_all_runs_use_helper(rel_path: str, expected_min: int):
    _tree, calls = _ast_calls(rel_path)
    runs = [c for c in calls if _is_subprocess_attr(c, "run")]
    assert len(runs) >= expected_min, (
        f"{rel_path}: subprocess.run 호출이 예상보다 적다 "
        f"(min={expected_min}, found={len(runs)}). 테스트 기대값을 갱신하라."
    )
    missing = [c for c in runs if not _has_no_window_helper(c)]
    assert not missing, (
        f"{rel_path}: {len(missing)}개의 subprocess.run 호출이 no_window_kwargs() 를 사용하지 않는다 "
        f"(라인 {[c.lineno for c in missing]}). Windows release build 에서 cmd 창이 깜빡인다."
    )


def test_core_exiftool_run_calls_use_helper():
    _assert_all_runs_use_helper("core/exiftool.py", expected_min=3)


def test_core_metadata_writer_run_calls_use_helper():
    _assert_all_runs_use_helper("core/metadata_writer.py", expected_min=2)


def test_explorer_popen_calls_use_helper():
    """Windows 의 explorer Popen 호출이 모두 helper 를 적용한다."""
    targets = [
        "app/main_window.py",
        "app/views/workflow_wizard_view.py",
    ]
    for rel in targets:
        _tree, calls = _ast_calls(rel)
        explorers = [c for c in calls if _is_explorer_popen(c)]
        assert explorers, f"{rel}: explorer Popen 호출이 사라졌다. 테스트를 갱신하라."
        missing = [c for c in explorers if not _has_no_window_helper(c)]
        assert not missing, (
            f"{rel}: explorer Popen 호출에 no_window_kwargs() 누락 "
            f"(라인 {[c.lineno for c in missing]})."
        )
