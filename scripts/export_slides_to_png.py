"""PPTX 슬라이드를 PNG로 일괄 내보내기 (PowerPoint COM 자동화)."""
from __future__ import annotations
import sys
import time
from pathlib import Path

PPTX = Path(r"D:\AruArchive-v0.6.3-win-x64\AruArchive_User_Guide_v0.6.3.pptx")
OUT  = Path(r"D:\AruArchive-v0.6.3-win-x64\slides_png")

# 출력 해상도 (px) — 1920×1080 기준. 더 크게 원하면 값을 높이세요.
WIDTH  = 1920
HEIGHT = 1080

def main() -> None:
    if not PPTX.exists():
        sys.exit(f"파일 없음: {PPTX}")

    OUT.mkdir(parents=True, exist_ok=True)

    import win32com.client
    import win32com.client as wc

    print("PowerPoint 실행 중…")
    ppt = wc.DispatchEx("PowerPoint.Application")
    ppt.Visible = True   # False 시 일부 환경에서 오류 발생

    try:
        print(f"파일 열기: {PPTX}")
        prs = ppt.Presentations.Open(str(PPTX), ReadOnly=True, Untitled=False, WithWindow=True)
        n = prs.Slides.Count
        print(f"총 {n}슬라이드 → {OUT}")

        for i in range(1, n + 1):
            out_path = OUT / f"slide_{i:02d}.png"
            prs.Slides(i).Export(str(out_path), "PNG", WIDTH, HEIGHT)
            print(f"  [{i:02d}/{n}] {out_path.name}")

        prs.Close()
        print(f"\n완료: {n}장 → {OUT}")
    finally:
        ppt.Quit()


if __name__ == "__main__":
    main()
