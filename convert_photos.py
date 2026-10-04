#!/usr/bin/env python3
"""
Prepare photos for the 320x240 panel.

    python3 convert_photos.py <source folder> [output folder]

Reads any common image format, honours the rotation tag your phone writes,
crops to the screen's 4:3 shape from the centre, and writes numbered PNGs.
Doing this once means the display never has to resize anything at runtime.
"""
import sys
from pathlib import Path

from PIL import Image, ImageOps

W, H = 320, 240
EXT = {".png", ".jpg", ".jpeg", ".heic", ".bmp", ".gif", ".webp", ".tif", ".tiff"}


def fit_cover(im, w, h):
    scale = max(w / im.width, h / im.height)
    im = im.resize((max(w, round(im.width * scale)),
                    max(h, round(im.height * scale))), Image.LANCZOS)
    left, top = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1]).expanduser()
    out = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else src / "converted"
    out.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in src.iterdir() if p.suffix.lower() in EXT)
    if not files:
        sys.exit(f"no images found in {src}")

    for n, path in enumerate(files, 1):
        try:
            im = Image.open(path)
            im = ImageOps.exif_transpose(im)      # phones store rotation in EXIF
            im = im.convert("RGB")
            portrait = im.height > im.width
            im = fit_cover(im, W, H)
            dest = out / f"{n:03d}-{path.stem[:30]}.png"
            im.save(dest)
            note = "  (portrait — cropped hard, check it)" if portrait else ""
            print(f"{path.name}  ->  {dest.name}{note}")
        except Exception as e:
            print(f"{path.name}  ->  SKIPPED ({e})")

    print(f"\n{len(list(out.glob('*.png')))} photos ready in {out}")


if __name__ == "__main__":
    main()
