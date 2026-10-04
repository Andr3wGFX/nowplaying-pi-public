"""Draw a contact sheet of every sticker in stickers/stickers.json.

    ~/np/bin/python ~/np/tools/sticker_sheet.py            # writes docs/stickers.png
    ~/np/bin/python ~/np/tools/sticker_sheet.py out.png

Each tile shows the sticker, its mood and file name, with a magenta ring on
each eye coordinate -- so after adding a sticker you can check at a glance that
the eyes landed on the eyes. Safe to run while the service is up (no camera or
display involved).
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
STICKERS = ROOT / "stickers"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "stickers.png"

COLS, TILE_W, IMG_H, LABEL_H, PAD = 5, 200, 186, 48, 6
BG, CARD, INK, RING = (244, 246, 248), (255, 255, 255), (60, 64, 72), (230, 0, 200)
MOOD = {"blink": (130, 80, 200), "down": (40, 110, 200), "happy": (50, 150, 70),
        "neutral": (90, 100, 115), "open": (215, 60, 60), "turn": (200, 140, 20)}
ORDER = list(MOOD)


def font(size, bold=False):
    names = (["DejaVuSans-Bold.ttf"] if bold else []) + ["DejaVuSans.ttf", "Quicksand-Regular.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def main():
    entries = json.loads((STICKERS / "stickers.json").read_text())["stickers"]
    entries.sort(key=lambda s: (ORDER.index(s["expr"]) if s["expr"] in ORDER else 99, s["file"]))
    rows = -(-len(entries) // COLS)
    tile_h = IMG_H + LABEL_H
    sheet = Image.new("RGB", (COLS * TILE_W, rows * tile_h), BG)
    draw = ImageDraw.Draw(sheet)
    f_mood, f_name = font(13, bold=True), font(13)

    for i, s in enumerate(entries):
        x0, y0 = (i % COLS) * TILE_W, (i // COLS) * tile_h
        im = ImageOps.exif_transpose(Image.open(STICKERS / s["file"])).convert("RGBA")
        flat = Image.new("RGBA", im.size, CARD + (255,))
        im = Image.alpha_composite(flat, im).convert("RGB")   # transparent -> white
        scale = min((TILE_W - 2 * PAD) / im.width, (IMG_H - 2 * PAD) / im.height)
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        ix = x0 + (TILE_W - im.width) // 2
        iy = y0 + (IMG_H - im.height) // 2
        sheet.paste(im, (ix, iy))
        for ex, ey in (s["eye_left"], s["eye_right"]):
            cx, cy = ix + ex * scale, iy + ey * scale
            draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), outline=RING, width=2)
        draw.text((x0 + PAD, y0 + IMG_H + 4), s["expr"], font=f_mood,
                  fill=MOOD.get(s["expr"], INK))
        draw.text((x0 + PAD, y0 + IMG_H + 22), s["file"], font=f_name, fill=INK)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT, optimize=True)
    print(f"{len(entries)} stickers -> {OUT}")


if __name__ == "__main__":
    main()
