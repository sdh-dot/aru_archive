"""
Windows release build 에서 subprocess 호출이 cmd 창을 깜빡이는 문제를 막기 위한
공용 helper.

PyInstaller windowed mode (console=False) 로 빌드된 Aru Archive 가
ExifTool 같은 콘솔 프로그램을 spawn 하면, Windows 가 자식 프로세스용 콘솔을 새로
할당해 화면에 검은 창이 잠깐 떴다 사라진다. 메타데이터 입력처럼 다수 파일을
순차 처리할 때는 cmd 창이 반복적으로 깜빡여 사용자 입력을 빼앗는다.

해결: ``creationflags=subprocess.CREATE_NO_WINDOW`` 를 모든 subprocess 호출에
적용하면 자식 프로세스의 콘솔이 만들어지지 않는다.

사용법::

    from core.subprocess_util import no_window_kwargs

    subprocess.run([exe, "-ver"], capture_output=True, **no_window_kwargs())

규칙:
- ExifTool 등 외부 CLI 를 호출하는 모든 subprocess 사용처는 이 helper 를 거친다.
- macOS / Linux 에서는 빈 dict 를 반환해 동작 변화가 없다.
- shell=True 는 여전히 금지 — 인자 리스트를 사용한다.
"""
from __future__ import annotations

import os
import subprocess
from typing import Any


def no_window_kwargs() -> dict[str, Any]:
    """Windows 에서는 subprocess 자식 콘솔을 숨기는 kwargs, 그 외 OS 는 빈 dict.

    반환된 dict 를 ``subprocess.run`` / ``subprocess.Popen`` 의 kwargs 로 펼쳐
    전달한다. ``CREATE_NO_WINDOW`` 가 stdlib 에 없는 환경 (비-Windows 또는
    아주 오래된 Python) 에서는 빈 dict 를 반환하므로 항상 안전하다.
    """
    if os.name != "nt":
        return {}
    kwargs: dict[str, Any] = {}
    flag = getattr(subprocess, "CREATE_NO_WINDOW", None)
    if flag is not None:
        kwargs["creationflags"] = flag
    return kwargs
