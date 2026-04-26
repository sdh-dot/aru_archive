"""
Aru Archive icon asset generator.

Usage:
    python build/generate_icons.py
    python build/generate_icons.py --source docs/icon_1.png
"""
from __future__ import annotations

import argparse
import sys
from collections import deque
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required: pip install Pillow")

ROOT = Path(__file__).parent.parent

SOURCE_DEFAULT  = ROOT / "docs" / "icon_1.png"
MASTER_OUT      = ROOT / "assets" / "icon" / "aru_archive_icon_master.png"
ASSET_DIR       = ROOT / "assets" / "icon"
EXT_ICONS_DIR   = ROOT / "extension" / "icons"
DOCS_ICON       = ROOT / "docs" / "icon.png"
ICO_OUT         = ROOT / "assets" / "icon" / "aru_archive_icon.ico"

PNG_SIZES       = [1024, 512, 256, 128, 64, 48, 32, 16]
ICO_SIZES       = [256, 128, 64, 48, 32, 16]
EXT_SIZES       = [16, 32, 48, 128]

BG_TOLERANCE    = 30   # max Euclidean distance per channel from reference corner color


# ---------------------------------------------------------------------------
# Background removal
# ---------------------------------------------------------------------------

def _color_distance(a: tuple, b: tuple) -> float:
    return max(abs(int(a[i]) - int(b[i])) for i in range(3))


def remove_white_background(img: Image.Image, tolerance: int = BG_TOLERANCE) -> Image.Image:
    """Flood-fill background from all four corners and make it transparent."""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    pixels = rgba.load()

    # Determine background color from four corners
    corners = [
        pixels[0, 0][:3],
        pixels[w - 1, 0][:3],
        pixels[0, h - 1][:3],
        pixels[w - 1, h - 1][:3],
    ]
    bg_ref = tuple(sum(c[i] for c in corners) // 4 for i in range(3))

    visited = bytearray(w * h)
    queue: deque[tuple[int, int]] = deque()

    def _enqueue(x: int, y: int) -> None:
        if 0 <= x < w and 0 <= y < h and not visited[y * w + x]:
            if _color_distance(pixels[x, y][:3], bg_ref) <= tolerance:
                visited[y * w + x] = 1
                queue.append((x, y))

    for sx, sy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        _enqueue(sx, sy)

    while queue:
        x, y = queue.popleft()
        r, g, b, a = pixels[x, y]
        dist = _color_distance((r, g, b), bg_ref)
        # Fully transparent for pixels within tolerance (clean pixel-art edges)
        new_alpha = 0 if dist <= tolerance else a
        pixels[x, y] = (r, g, b, new_alpha)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            _enqueue(x + dx, y + dy)

    return rgba


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_alpha(img: Image.Image, path: str) -> bool:
    if "A" not in img.mode:
        print(f"  [WARN] {path}: alpha channel not present")
        return False
    alpha = img.getchannel("A")
    mn, mx = alpha.getextrema()
    pixels = list(alpha.getdata())
    transparent = sum(1 for p in pixels if p == 0)
    total = len(pixels)
    print(f"  alpha range: {mn}-{mx}, transparent pixels: {transparent}/{total} ({100*transparent/total:.1f}%)")
    if transparent == 0:
        print("  [WARN] no fully transparent pixels found — background may not be removed")
        return False
    return True


# ---------------------------------------------------------------------------
# Generation helpers
# ---------------------------------------------------------------------------

def _resize(img: Image.Image, size: int) -> Image.Image:
    """High-quality resize preserving RGBA."""
    return img.resize((size, size), Image.LANCZOS)


def generate_png_set(master: Image.Image, sizes: list[int], out_dir: Path, prefix: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for sz in sizes:
        out_path = out_dir / f"{prefix}{sz}.png"
        _resize(master, sz).save(out_path, format="PNG")
        print(f"  {out_path.relative_to(ROOT)}")


def generate_ico(master: Image.Image, ico_sizes: list[int], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames = [_resize(master, s).convert("RGBA") for s in ico_sizes]
    frames[0].save(
        out_path,
        format="ICO",
        sizes=[(s, s) for s in ico_sizes],
        append_images=frames[1:],
    )
    print(f"  {out_path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Aru Archive icon assets")
    parser.add_argument("--source", default=str(SOURCE_DEFAULT), help="Source PNG (default: docs/icon_1.png)")
    parser.add_argument("--tolerance", type=int, default=BG_TOLERANCE,
                        help="Background removal tolerance 0-255 (default: 30)")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        sys.exit(f"Source not found: {source}")

    # ------------------------------------------------------------------ 1
    print(f"\n[1] Loading source: {source}")
    raw = Image.open(source)
    print(f"  mode={raw.mode}  size={raw.size}")

    # ------------------------------------------------------------------ 2
    print("\n[2] Background removal / alpha validation")
    if "A" in raw.mode:
        alpha = raw.getchannel("A")
        mn, mx = alpha.getextrema()
        pixels = list(alpha.getdata())
        transparent = sum(1 for p in pixels if p == 0)
        total = len(pixels)
        print(f"  Already RGBA. alpha range: {mn}-{mx}")
        print(f"  Transparent pixels: {transparent}/{total} ({100*transparent/total:.1f}%)")
        if transparent < total * 0.01:
            print("  [WARN] Very few transparent pixels. Running background removal anyway.")
            master_rgba = remove_white_background(raw, args.tolerance)
        else:
            master_rgba = raw.convert("RGBA")
            print("  Skipping background removal (already transparent)")
    else:
        print(f"  RGB image detected. Attempting white-background removal (tolerance={args.tolerance})...")
        master_rgba = remove_white_background(raw, args.tolerance)

    ok = validate_alpha(master_rgba, str(source))
    if not ok:
        print("  [WARN] Transparent background validation FAILED — proceeding but review the output")

    # ------------------------------------------------------------------ 3 master
    print("\n[3] Saving master asset")
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    master_rgba.save(MASTER_OUT, format="PNG")
    print(f"  {MASTER_OUT.relative_to(ROOT)}")

    # ------------------------------------------------------------------ 4 PNG set
    print("\n[4] Generating PNG size set")
    for sz in PNG_SIZES:
        out_path = ASSET_DIR / f"aru_archive_icon_{sz}.png"
        _resize(master_rgba, sz).save(out_path, format="PNG")
        print(f"  {out_path.relative_to(ROOT)}")

    # ------------------------------------------------------------------ 5 ICO
    print("\n[5] Generating Windows ICO")
    generate_ico(master_rgba, ICO_SIZES, ICO_OUT)

    # ------------------------------------------------------------------ 6 Extension icons
    print("\n[6] Generating extension icon set")
    EXT_ICONS_DIR.mkdir(parents=True, exist_ok=True)
    for sz in EXT_SIZES:
        out_path = EXT_ICONS_DIR / f"icon{sz}.png"
        _resize(master_rgba, sz).save(out_path, format="PNG")
        print(f"  {out_path.relative_to(ROOT)}")

    # ------------------------------------------------------------------ 7 docs/icon.png
    print("\n[7] Updating docs/icon.png (256px representative)")
    _resize(master_rgba, 256).save(DOCS_ICON, format="PNG")
    print(f"  {DOCS_ICON.relative_to(ROOT)}")

    # ------------------------------------------------------------------ done
    print("\nDone. Summary:")
    print(f"  master      : {MASTER_OUT.relative_to(ROOT)}")
    print(f"  ico         : {ICO_OUT.relative_to(ROOT)}")
    print(f"  png sizes   : {PNG_SIZES}")
    print(f"  ext icons   : {EXT_SIZES}")
    print(f"  docs icon   : {DOCS_ICON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
