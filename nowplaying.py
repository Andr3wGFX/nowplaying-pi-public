#!/usr/bin/env python3
"""
Spotify now-playing display, photo slideshow, photo booth and timelapse.
Waveshare 2inch LCD Module (ST7789V, 320x240) on a Raspberry Pi 5 (or Pi 4
without the hamster filter). See README.md for setup.

  * photo background image        ~/np/background.png
  * Mochi Boom for words          ~/np/fonts/MochiBoom.ttf (optional)
  * animated "snake" progress bar, drawn with partial-window SPI updates
  * photo slideshow after the music has been paused for a while

Wiring:
  VCC pin17  GND pin20  DIN pin19  CLK pin23
  CS  pin24  DC  pin22  RST pin13  BL  pin12
  Buttons: prev pin29 (GPIO5), play/pause pin31 (GPIO6), next pin37 (GPIO26)
"""

import colorsys
import io
import json
import math
import os
import queue
import random
import sys
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

import requests
import spotipy
from gpiozero import Button
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from spotipy.oauth2 import SpotifyOAuth
from st7789 import ST7789

# ----------------------------------------------------------------- config ---

W, H = 320, 240
# Measured on this wiring with cameracheck.py: 64 MHz asked, ~62.5 MHz actual,
# clean. A whole frame is ~20 ms instead of the 307 ms we had at 4 MHz.
# If the panel ever shows torn stripes, step down to 32_000_000.
SPI_HZ = 64_000_000
POLL = 3.0          # seconds between Spotify API calls
TICK = 0.1          # main loop period -> 10 animation frames a second
LOCKOUT = 0.4       # ignore repeat button presses inside this window
FLASH = 0.8         # how long a pressed on-screen button stays lit

HOME = Path.home() / "np"
# hamster.py may sit next to this script or in ~/np -- accept either, rather
# than depending on which directory it happened to get copied to
if str(HOME) not in sys.path:
    sys.path.insert(0, str(HOME))

ENV_FILE = HOME / ".env"

# Read ~/np/.env before any setting below, so location, timezone and
# credentials can all live there instead of in the code.
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip("'\""))
CACHE_FILE = HOME / ".spotify-cache"
BG_FILE = HOME / "background.png"
FONT_FILE = HOME / "fonts" / "MochiBoom.ttf"
PHOTO_DIR = HOME / "photos"

# ---- slideshow ---------------------------------------------------------
PAUSE_AFTER = 10.0   # seconds paused before the photos take over
PHOTO_SECS = 8.0     # seconds each photo is held
FADE_STEPS = 4       # crossfade frames; set to 0 for a hard cut
SHUFFLE = True

# ---- camera mode -------------------------------------------------------
CAMERA_ENABLED = True
CAM_INDEX = 0
# 1024x768 is 4:3, so it maps to the panel with no cropping. Drop to 640x480
# if the viewfinder feels choppy; 1280x960 is the C270's max but is slower.
CAM_W, CAM_H = 1024, 768
CAPTURE_DIR = HOME / "captures"
HOLD_SECS = 3.0          # how long to hold the middle button to get here
COUNTDOWN = 3            # seconds after pressing next
SAVED_SECS = 1.6         # how long the captured shot stays on screen
MIRROR = True            # preview left-right flipped, like a mirror.
                         # Flipping happens once, before the filter and before
                         # saving, so what you see is exactly what you get and
                         # the hamsters are never drawn back-to-front.
JPEG_QUALITY = 92

# ---- hamster filter ----------------------------------------------------
FILTER_ENABLED = True
STICKER_DIR = HOME / "stickers"
FILTER_COVER = 3.0       # sticker width in multiples of its own eye separation
FILTER_EVERY = 2         # run face detection every Nth frame
FILTER_FACES = 4         # most people the filter will hamster at once
# MediaPipe face landmarks + expression scores, one model for both jobs.
# Downloaded by setup.sh, or by hand:
#   wget -O ~/np/face_landmarker.task https://storage.googleapis.com/\
#     mediapipe-models/face_landmarker/face_landmarker/float16/1/\
#     face_landmarker.task
FACE_MODEL = HOME / "face_landmarker.task"

# ---- timelapse ---------------------------------------------------------
# Hold the shutter in camera mode to start one; middle press stops it and
# leaves you in camera mode; middle again returns to Spotify.
TL_DIR = HOME / "timelapse"
TL_HOLD = 3.0            # hold the shutter this long to start
TL_INTERVAL = 4.0        # one frame every N seconds
TL_MAX_SECS = 1800.0     # and stop on its own after half an hour
TL_FPS = 30              # 1800 / 4 = 450 frames = 15 s of video
TL_TICK = 0.25           # how often the loop wakes between frames

# ---- idle overlay: clock, date and weather over the photos -------------
SHOW_OVERLAY = True
CLOCK_24H = False
# Where you are, for the weather, and which clock to show. Set in ~/np/.env
# so the code carries nobody's address and the device can travel with you:
#
#   NP_TIMEZONE=Europe/London        an IANA zone name. Pin the real one: some
#                                    places skip daylight saving, so a generic
#                                    zone like "Mountain Time" can be an hour
#                                    out for half the year.
#   NP_LAT=51.5                      anywhere near you -- a postcode or town
#   NP_LON=-0.1                      centre is plenty for a weather reading
#
# Unset timezone -> the Pi's own system clock. Unset location -> the overlay
# shows the clock and date only, and no weather request is ever made.
TIMEZONE = os.environ.get("NP_TIMEZONE", "").strip()
try:
    LAT, LON = float(os.environ["NP_LAT"]), float(os.environ["NP_LON"])
except (KeyError, ValueError):
    LAT = LON = None
TEMP_UNIT = "fahrenheit"         # or "celsius"
WEATHER_EVERY = 900.0            # seconds between weather refreshes
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

OVL_X = 18                       # left margin of the overlay block
OVL_CLOCK_BASE = 192             # baselines, measured from the top of the screen
OVL_DATE_BASE = 214
OVL_WX_BASE = 234
OVL_BAND = (0, 138, 279, H - 1)  # the strip re-sent when the minute ticks

# ---- background treatment ----------------------------------------------
BG_BLUR = 3.0        # softens the streaks so text sits on top of them
BG_DIM = 0.35        # 0 = untouched, 1 = black. Raise if text is hard to read
BG_SAT = 0.90        # colour intensity

# ---- palette -----------------------------------------------------------
INK = (255, 255, 255)
INK_SOFT = (208, 228, 240)
SHADOW = (0, 12, 28)
ON_ACCENT = (12, 24, 40)          # glyph inside the filled play button
DEFAULT_ACCENT = (126, 236, 220)  # until album art says otherwise
RAIL_RGBA = (255, 255, 255, 78)   # unplayed part of the progress track

# ---- geometry ----------------------------------------------------------
PAD = 18
ART = 112
ART_X, ART_Y = 16, 24
ART_R = 13
TEXT_X = 142
TEXT_W = W - 14 - TEXT_X    # Mochi Boom is wide; the text column needs room

CTRL_Y = 166
CTRL_X = W // 2
CTRL_GAP = 48
CTRL_R = 16
CTRL_W, CTRL_H = 176, 48
CTRL_BX, CTRL_BY = CTRL_X - CTRL_W // 2, CTRL_Y - CTRL_H // 2
# the transport row also gets its own strip, so a button press lights up in
# about 35 ms instead of waiting 300 ms for a whole new frame
CTRL_BAND = (CTRL_BX, CTRL_BY, CTRL_BX + CTRL_W - 1, CTRL_BY + CTRL_H - 1)

WAVE_Y = 202         # centre line of the progress wave
WAVE_AMP = 6.0       # how far it swings
WAVE_LEN = 44.0      # wavelength in pixels
WAVE_SECS = 1.2      # seconds for the wave to travel one wavelength
WAVE_W = 3           # line thickness
BAR_X0, BAR_X1 = PAD, W - PAD
TIME_Y = 214

# The strip that gets re-sent on its own while the wave animates.
BAND = (0, 190, W - 1, 234)

SS = 4               # supersample factor for everything round

SCOPE = (
    "user-read-currently-playing "
    "user-read-playback-state "
    "user-modify-playback-state"
)

# ------------------------------------------------------------ credentials ---

auth = SpotifyOAuth(scope=SCOPE, cache_path=str(CACHE_FILE), open_browser=False)
sp = spotipy.Spotify(auth_manager=auth, requests_timeout=8)

# ---------------------------------------------------------------- display ---

disp = ST7789(
    port=0, cs=0, dc=25, rst=27, backlight=18,
    width=W, height=H, rotation=0, invert=True,
    spi_speed_hz=SPI_HZ,
)
disp.reset()    # st7789 1.0.1 requests RST as a LOW output and never raises it
disp._init()    # so release it by hand, then re-run the startup sequence


def push(img, box=None):
    """Send a frame, or just one horizontal strip of it, to the panel.

    A full 320x240 frame takes about 0.3 s at 4 MHz. The progress-bar strip
    is a seventh of that, which is what makes the animation affordable.
    """
    if box is None:
        disp.display(img)
        return
    x0, y0, x1, y1 = box              # img is already exactly this region
    disp.set_window(x0, y0, x1, y1)
    raw = disp.image_to_data(img, disp._rotation)
    for i in range(0, len(raw), 4096):
        disp.data(raw[i: i + 4096])

# ------------------------------------------------------------------ fonts ---
# Mochi Boom DEMO has real letters but its ten DIGITS are replaced by a
# "buy the full version" watermark, so the clock has to borrow another face.

QUICKSAND = "/usr/share/fonts/truetype/quicksand"
DEJAVU = "/usr/share/fonts/truetype/dejavu"


def pick_font(size, *candidates):
    for path in candidates:
        if path and Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default()


def word_font(size):
    return pick_font(size, str(FONT_FILE),
                     f"{QUICKSAND}/Quicksand-Bold.ttf",
                     f"{DEJAVU}/DejaVuSans-Bold.ttf")


def digit_font(size):
    return pick_font(size, f"{QUICKSAND}/Quicksand-Medium.ttf",
                     f"{DEJAVU}/DejaVuSans.ttf")


F_TITLE = word_font(20)
F_ARTIST = word_font(15)
F_MSG = word_font(18)
F_SMALL = digit_font(13)

F_CLOCK = pick_font(46, f"{QUICKSAND}/Quicksand-Bold.ttf",
                    f"{DEJAVU}/DejaVuSans-Bold.ttf")
F_AMPM = digit_font(15)
F_OVL_W = word_font(14)          # Mochi Boom for the words
F_OVL_D = digit_font(15)         # Quicksand for anything Mochi can't draw

# Mochi Boom's digits are a watermark, so numbers (and the symbols that sit
# with them) are drawn in Quicksand and the rest in Mochi, run by run.
DIGITISH = set("0123456789°:/")

# Mochi Boom carries no accented characters, so fold them down to plain
# letters rather than letting Pillow draw empty boxes for Bjork or Sigur Ros.
KEEP = {chr(c) for c in range(0x20, 0x7F)} | {"…"}
SUBSTITUTE = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "‐": "-", "·": "-",
    "×": "x", "ß": "ss", "æ": "ae", "Æ": "AE",
    "œ": "oe", "Œ": "OE", "ø": "o", "Ø": "O",
    "đ": "d", "Đ": "D", "ł": "l", "Ł": "L",
}


def safe(text):
    out = []
    for ch in unicodedata.normalize("NFKD", text or ""):
        if unicodedata.combining(ch):      # the accent itself, now detached
            continue
        if ch in KEEP:
            out.append(ch)
        elif ch in SUBSTITUTE:
            out.append(SUBSTITUTE[ch])
    return "".join(out).strip()

# ------------------------------------------------------------- background ---


def fit_cover(im, w, h):
    """Scale to fill w x h, then centre-crop the overflow."""
    scale = max(w / im.width, h / im.height)
    im = im.resize((max(w, round(im.width * scale)),
                    max(h, round(im.height * scale))), Image.LANCZOS)
    left, top = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


def make_background():
    if BG_FILE.exists():
        try:
            bg = fit_cover(Image.open(BG_FILE).convert("RGB"), W, H)
            if BG_BLUR:
                bg = bg.filter(ImageFilter.GaussianBlur(BG_BLUR))
            if BG_SAT != 1.0:
                bg = ImageEnhance.Color(bg).enhance(BG_SAT)
            if BG_DIM:
                bg = Image.blend(bg, Image.new("RGB", bg.size, (0, 0, 0)),
                                 BG_DIM)
            return bg
        except Exception:
            pass
    # fallback when background.png is missing: a pastel gradient
    bg = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(bg)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)],
               fill=tuple(int(a + (b - a) * t)
                          for a, b in zip((34, 92, 132), (12, 40, 74))))
    return bg


def make_mask(size, radius, scale=SS):
    """Antialiased rounded-square mask: draw big, shrink down."""
    big = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(big).rounded_rectangle(
        (0, 0, size * scale - 1, size * scale - 1),
        radius=radius * scale, fill=255)
    return big.resize((size, size), Image.LANCZOS)


BG = make_background()
ART_MASK = make_mask(ART, ART_R)

# ------------------------------------------------------------------ state ---

state = {
    "track_id": None, "title": "", "artist": "", "art": None,
    "accent": DEFAULT_ACCENT, "playing": False, "progress": 0.0,
    "duration": 0.0, "device": None, "message": "starting up",
}

last_poll = 0.0
lock_until = 0.0
flash_what = None
flash_until = 0.0
paused_since = None
phase = 0.0

# ------------------------------------------------------------- text bits ----


def shadow_text(d, xy, text, fnt, fill):
    x, y = xy
    d.text((x + 1, y + 2), text, font=fnt, fill=SHADOW)
    d.text((x, y), text, font=fnt, fill=fill)


def mmss(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def ellipsize(d, text, fnt, max_w):
    if d.textlength(text, font=fnt) <= max_w:
        return text
    while text and d.textlength(text + "…", font=fnt) > max_w:
        text = text[:-1]
    return text + "…"


def wrap_two(d, text, fnt, max_w):
    """At most two lines. If words are left over, say so with an ellipsis."""
    lines, cur, leftover = [], "", False
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if not cur or d.textlength(trial, font=fnt) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
            if len(lines) == 2:
                leftover = True     # this word and the rest have nowhere to go
                break
    if cur and not leftover:
        lines.append(cur)
    lines = [ellipsize(d, ln, fnt, max_w) for ln in lines[:2]] or [""]
    if leftover:
        i = len(lines) - 1
        ln = lines[i].rstrip("…")
        while ln and d.textlength(ln + "…", font=fnt) > max_w:
            ln = ln[:-1]
        lines[i] = ln.rstrip() + "…"
    return lines


def accent_from(img):
    """Most characterful colour in the cover art, brightened for a dark ground."""
    q = img.resize((48, 48)).quantize(colors=8)
    palette = q.getpalette()
    best, best_score = DEFAULT_ACCENT, -1.0
    for count, idx in q.getcolors():
        r, g, b = palette[idx * 3: idx * 3 + 3]
        _, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if v < 0.20 or v > 0.98:
            continue
        score = s * (v ** 0.5) * (count ** 0.4)
        if score > best_score:
            best_score, best = score, (r, g, b)
    h, s, v = colorsys.rgb_to_hsv(*[c / 255 for c in best])
    if s < 0.18:                       # a black-and-white cover stays neutral
        return DEFAULT_ACCENT
    r, g, b = colorsys.hsv_to_rgb(h, min(max(s, 0.5), 0.85), max(v, 0.82))
    return int(r * 255), int(g * 255), int(b * 255)


def load_art(item):
    images = (item.get("album") or {}).get("images") or []
    pick = None
    for im in images:                      # Spotify lists largest first
        if im.get("width") and im["width"] >= ART:
            pick = im
    pick = pick or (images[0] if images else None)
    if not pick:
        state["art"] = None
        return
    try:
        raw = requests.get(pick["url"], timeout=6).content
        art = Image.open(io.BytesIO(raw)).convert("RGB")
        state["art"] = art.resize((ART, ART), Image.LANCZOS)
        state["accent"] = accent_from(state["art"])
    except Exception:
        state["art"] = None

# -------------------------------------------------------------- drawing -----


def transport_layer(lit):
    """Prev / play-pause / next, drawn 4x oversized then shrunk."""
    bw, bh = CTRL_W, CTRL_H
    bx, by = CTRL_BX, CTRL_BY
    layer = Image.new("RGBA", (bw * SS, bh * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    def px(x, y):
        return ((x - bx) * SS, (y - by) * SS)

    def tri(a, b, c, colour):
        d.polygon([px(*a), px(*b), px(*c)], fill=colour)

    prev_c = state["accent"] if lit == "prev" else INK_SOFT
    next_c = state["accent"] if lit == "next" else INK_SOFT
    disc = INK if lit == "play" else state["accent"]

    lx = CTRL_X - CTRL_GAP
    tri((lx - 11, CTRL_Y), (lx - 1, CTRL_Y - 8), (lx - 1, CTRL_Y + 8), prev_c)
    tri((lx + 1, CTRL_Y), (lx + 11, CTRL_Y - 8), (lx + 11, CTRL_Y + 8), prev_c)

    rx = CTRL_X + CTRL_GAP
    tri((rx + 11, CTRL_Y), (rx + 1, CTRL_Y - 8), (rx + 1, CTRL_Y + 8), next_c)
    tri((rx - 1, CTRL_Y), (rx - 11, CTRL_Y - 8), (rx - 11, CTRL_Y + 8), next_c)

    x0, y0 = px(CTRL_X - CTRL_R, CTRL_Y - CTRL_R)
    x1, y1 = px(CTRL_X + CTRL_R, CTRL_Y + CTRL_R)
    d.ellipse((x0, y0, x1, y1), fill=disc)

    if state["playing"]:                                  # showing pause
        for off in (-6, 2):
            a, b = px(CTRL_X + off, CTRL_Y - 8)
            c, e = px(CTRL_X + off + 4, CTRL_Y + 8)
            d.rounded_rectangle((a, b, c, e), radius=2 * SS, fill=ON_ACCENT)
    else:                                                 # showing play
        tri((CTRL_X - 5, CTRL_Y - 8), (CTRL_X - 5, CTRL_Y + 8),
            (CTRL_X + 8, CTRL_Y), ON_ACCENT)

    return layer.resize((bw, bh), Image.LANCZOS)


def paste_transport(img, lit, at=(CTRL_BX, CTRL_BY)):
    """`at` is (0, 0) when img is the cropped CTRL_BAND strip rather than a
    whole frame -- pasting at absolute coordinates there lands off-canvas and
    silently wipes the row."""
    small = transport_layer(lit)
    img.paste(small, at, small)


def draw_static():
    """Everything except the progress wave. Cached between wave frames."""
    img = BG.copy()
    d = ImageDraw.Draw(img)

    if state["message"]:
        w = d.textlength(state["message"], font=F_MSG)
        shadow_text(d, ((W - w) / 2, H / 2 - 14), state["message"],
                    F_MSG, INK_SOFT)
        return img

    art = state["art"] or Image.new("RGB", (ART, ART), (40, 66, 92))
    img.paste(art, (ART_X, ART_Y), ART_MASK)

    lines = wrap_two(d, state["title"], F_TITLE, TEXT_W)
    line_h, gap, artist_h = 25, 8, 19
    block = len(lines) * line_h + gap + artist_h
    y = ART_Y + (ART - block) // 2
    for line in lines:
        shadow_text(d, (TEXT_X, y), line, F_TITLE, INK)
        y += line_h
    shadow_text(d, (TEXT_X, y + gap),
                ellipsize(d, state["artist"], F_ARTIST, TEXT_W),
                F_ARTIST, INK_SOFT)
    return img          # transport and wave are pasted on by compose()


def draw_wave(band):
    """Draw the progress track onto a crop of the frame. Modifies in place."""
    bx, by = BAND[0], BAND[1]
    bw, bh = band.size
    layer = Image.new("RGBA", (bw * SS, bh * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    def px(x, y):
        return ((x - bx) * SS, (y - by) * SS)

    dur = state["duration"] or 1
    frac = min(max(state["progress"] / dur, 0.0), 1.0)
    head = BAR_X0 + (BAR_X1 - BAR_X0) * frac

    # the flat track, drawn only from the playhead rightwards so it never
    # shows through underneath the wave
    rail_from = max(BAR_X0, head)
    if rail_from < BAR_X1:
        d.line([px(rail_from, WAVE_Y), px(BAR_X1, WAVE_Y)],
               fill=RAIL_RGBA, width=WAVE_W * SS)

    if head > BAR_X0 + 1:
        span = head - BAR_X0
        pts = []
        x = BAR_X0
        while x <= head:
            # ease the swing in at the start and back out at the playhead so
            # the wave meets the flat track without a kink
            ramp = min(1.0, (x - BAR_X0) / 10.0, (head - x) / 14.0)
            amp = WAVE_AMP * max(0.0, ramp) if span > 8 else 0.0
            y = WAVE_Y + amp * math.sin(2 * math.pi * x / WAVE_LEN - phase)
            pts.append(px(x, y))
            x += 2
        pts.append(px(head, WAVE_Y))
        if len(pts) > 1:
            d.line(pts, fill=state["accent"] + (255,),
                   width=WAVE_W * SS, joint="curve")
        r = 4
        hx, hy = px(head, WAVE_Y)
        d.ellipse((hx - r * SS, hy - r * SS, hx + r * SS, hy + r * SS),
                  fill=state["accent"] + (255,))

    small = layer.resize((bw, bh), Image.LANCZOS)
    band.paste(small, (0, 0), small)

    d2 = ImageDraw.Draw(band)
    shadow_text(d2, (BAR_X0, TIME_Y - by), mmss(state["progress"]),
                F_SMALL, INK_SOFT)
    right = mmss(dur)
    shadow_text(d2, (BAR_X1 - d2.textlength(right, font=F_SMALL), TIME_Y - by),
                right, F_SMALL, INK_SOFT)


def compose(static_img, lit):
    """A whole frame: cached static part, plus transport and wave on top."""
    img = static_img.copy()
    if not state["message"]:
        paste_transport(img, lit)
        band = img.crop((BAND[0], BAND[1], BAND[2] + 1, BAND[3] + 1))
        draw_wave(band)
        img.paste(band, (BAND[0], BAND[1]))
    return img


def crop_band(img, box):
    return img.crop((box[0], box[1], box[2] + 1, box[3] + 1))

# ------------------------------------------------------------- overlay -----

WMO = {
    0: "Clear", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Cloudy",
    45: "Foggy", 48: "Rime Fog",
    51: "Light Drizzle", 53: "Drizzle", 55: "Heavy Drizzle",
    56: "Freezing Drizzle", 57: "Freezing Drizzle",
    61: "Light Rain", 63: "Rain", 65: "Heavy Rain",
    66: "Freezing Rain", 67: "Freezing Rain",
    71: "Light Snow", 73: "Snow", 75: "Heavy Snow", 77: "Snow Grains",
    80: "Light Showers", 81: "Showers", 82: "Heavy Showers",
    85: "Snow Showers", 86: "Snow Showers",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm Hail",
}

weather = {"temp": None, "code": None, "ok": False}

TZ = None
if ZoneInfo is not None and TIMEZONE:
    try:
        TZ = ZoneInfo(TIMEZONE)
    except Exception:
        TZ = None          # fall back to whatever the Pi's clock is set to


def weather_worker():
    """Refresh the weather forever, off the main loop so it can never stall
    the display. Open-Meteo needs no API key."""
    if LAT is None:
        return             # no location configured: clock only, no requests
    params = {
        "latitude": LAT, "longitude": LON,
        "current": "temperature_2m,weather_code",
        "temperature_unit": TEMP_UNIT, "timezone": TIMEZONE or "auto",
    }
    while True:
        try:
            r = requests.get(WEATHER_URL, params=params, timeout=10)
            cur = r.json()["current"]
            weather.update(temp=round(cur["temperature_2m"]),
                           code=int(cur["weather_code"]), ok=True)
        except Exception:
            pass           # keep whatever we last had; the clock still works
        time.sleep(WEATHER_EVERY)


def now_local():
    return datetime.now(TZ) if TZ else datetime.now()


def overlay_lines():
    n = now_local()
    if CLOCK_24H:
        clock, ampm = f"{n.hour}:{n.minute:02d}", ""
    else:
        clock, ampm = f"{n.hour % 12 or 12}:{n.minute:02d}", n.strftime("%p")
    date = f"{n.strftime('%A')}  {n.strftime('%B')} {n.day}"
    if weather["ok"] and weather["temp"] is not None:
        wx = f"{weather['temp']}°  {WMO.get(weather['code'], 'Weather')}"
    else:
        wx = ""
    return clock, ampm, date, wx


def font_runs(text):
    """Split into stretches of digits-and-symbols versus everything else, so
    each stretch keeps its own kerning."""
    out, cur, cur_is = [], "", None
    for ch in text:
        is_d = ch in DIGITISH
        if cur_is is None or is_d == cur_is:
            cur, cur_is = cur + ch, is_d
        else:
            out.append((cur, cur_is))
            cur, cur_is = ch, is_d
    if cur:
        out.append((cur, cur_is))
    return out


def draw_runs(d, x, baseline, text, fill):
    for run, is_digit in font_runs(text):
        f = F_OVL_D if is_digit else F_OVL_W
        d.text((x, baseline), run, font=f, fill=fill, anchor="ls")
        x += d.textlength(run, font=f)
    return x


def draw_overlay(img, origin=(0, 0)):
    """Clock, date and weather, bottom left, with a soft dark halo so it
    stays readable over a bright photo. `origin` is img's top-left in screen
    coordinates -- (0,0) for a whole frame, OVL_BAND's corner for the strip."""
    if not SHOW_OVERLAY:
        return
    ox, oy = origin
    clock, ampm, date, wx = overlay_lines()

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    d.text((OVL_X - ox, OVL_CLOCK_BASE - oy), clock,
           font=F_CLOCK, fill=(255, 255, 255, 255), anchor="ls")
    if ampm:
        w = d.textlength(clock, font=F_CLOCK)
        d.text((OVL_X - ox + w + 7, OVL_CLOCK_BASE - oy), ampm,
               font=F_AMPM, fill=(255, 255, 255, 235), anchor="ls")
    draw_runs(d, OVL_X - ox, OVL_DATE_BASE - oy, date, (255, 255, 255, 240))
    if wx:
        draw_runs(d, OVL_X - ox, OVL_WX_BASE - oy, wx, (255, 255, 255, 240))

    # halo: blur the text's own alpha and lay it down underneath
    glow = layer.getchannel("A").filter(ImageFilter.GaussianBlur(4))
    glow = glow.point(lambda v: min(255, int(v * 2.2)))
    halo = Image.new("RGBA", img.size, (0, 6, 16, 255))
    halo.putalpha(glow)

    img.paste(halo, (0, 1), halo)
    img.paste(layer, (0, 0), layer)


def overlay_key():
    return overlay_lines()


def with_overlay(photo):
    framed = photo.copy()
    draw_overlay(framed)
    return framed

# ------------------------------------------------------------- slideshow ----

PHOTO_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


_photo_cache = ([], 0.0)


def photo_list(force=False):
    """Directory listing, re-read at most every few seconds."""
    global _photo_cache
    files, when = _photo_cache
    now = time.monotonic()
    if force or now - when > 5.0:
        try:
            files = sorted(p for p in PHOTO_DIR.iterdir()
                           if p.suffix.lower() in PHOTO_EXT)
        except OSError:
            files = []
        _photo_cache = (files, now)
    return files


def load_photo(path):
    try:
        im = Image.open(path).convert("RGB")
        return im if im.size == (W, H) else fit_cover(im, W, H)
    except Exception:
        return None

# ---------------------------------------------------------------- camera ---

camera_on = False
cam_shoot_at = None
cam_mirror = MIRROR
cam_filter = False
cam_last_saved = None
_ham = None              # the filter, built the first time it's switched on
timelapse_on = False     # capturing; the camera loop is in timelapse mode
_tl = None               # the live Timelapse session

F_COUNT = pick_font(96, f"{QUICKSAND}/Quicksand-Bold.ttf",
                    f"{DEJAVU}/DejaVuSans-Bold.ttf")
F_HINT = word_font(13)
F_FILE = digit_font(12)      # filenames are mostly digits -> not Mochi Boom
F_SAVED = word_font(22)


def open_camera():
    """cv2 is imported here, not at the top, so the rest of the program still
    runs on a Pi that has no webcam and no opencv installed."""
    try:
        import cv2
    except ImportError:
        return None, None
    cap = cv2.VideoCapture(CAM_INDEX, cv2.CAP_V4L2)
    if not cap.isOpened():
        cap.release()
        return None, cv2
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)      # show now, not three frames ago
    return cap, cv2


def big_centred(img, text, font, fill=(255, 255, 255)):
    """Centred text with a blurred dark halo, so it reads over any scene."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text((W // 2, H // 2), text, font=font, fill=fill + (255,), anchor="mm")
    glow = layer.getchannel("A").filter(ImageFilter.GaussianBlur(6))
    halo = Image.new("RGBA", img.size, (0, 4, 12, 255))
    halo.putalpha(glow.point(lambda v: min(255, int(v * 2.4))))
    img.paste(halo, (0, 2), halo)
    img.paste(layer, (0, 0), layer)


def hint_bar(img, text, font=None):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle((0, H - 24, W, H), fill=(0, 6, 16, 150))
    d.text((W // 2, H - 12), text, font=font or F_HINT,
           fill=(230, 240, 250, 255), anchor="mm")
    img.paste(layer, (0, 0), layer)


def get_filter():
    """Built lazily -- loading 15 stickers and the landmark model takes a
    moment, and most sessions never turn the filter on."""
    global _ham
    if _ham is None:
        from hamster import HamsterFilter
        _ham = HamsterFilter(STICKER_DIR, FACE_MODEL,
                             cover_w=FILTER_COVER,
                             cover_h=FILTER_COVER * 1.1,
                             detect_every=FILTER_EVERY,
                             max_faces=FILTER_FACES)
        print(f"hamster: {len(_ham.stickers)} stickers, "
              f"{'VIDEO' if _ham.video_mode else 'IMAGE'} mode, moods "
              f"{sorted(_ham.by_expr)}")
    return _ham


def frame_to_panel(frame, cv2):
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb)
    if img.size != (W, H):
        img = fit_cover(img, W, H)
    return img


def save_capture(frame, cv2):
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    stamp = now_local().strftime("%Y-%m-%d_%H%M%S")
    path = CAPTURE_DIR / f"{stamp}.jpg"
    Image.fromarray(rgb).save(path, "JPEG", quality=JPEG_QUALITY)
    queue_upload(path)
    return path


F_TL_BIG = pick_font(40, f"{QUICKSAND}/Quicksand-Bold.ttf",
                     f"{DEJAVU}/DejaVuSans-Bold.ttf")


def timelapse_screen(base, tl, stopping=False):
    """Progress over a dimmed still of the last frame captured.

    Everything with digits in it uses Quicksand: Mochi Boom's digits are
    watermark glyphs, which has now bitten this project four times.
    """
    img = ImageEnhance.Brightness(base).enhance(0.35)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    left = max(0.0, TL_MAX_SECS - tl.elapsed)
    mins, secs = divmod(int(left), 60)
    d.text((W // 2, 60), f"{mins}:{secs:02d}", font=F_TL_BIG,
           fill=(235, 245, 255, 255), anchor="mm")
    d.text((W // 2, 92), "left" if not stopping else "finishing",
           font=F_HINT, fill=(150, 175, 200, 255), anchor="mm")

    d.text((W // 2, 132),
           # ASCII arrow on purpose: Quicksand has no U+2192 and draws a
           # tofu box instead. Same family of bug as Mochi Boom's digits --
           # check the glyph exists before designing around it.
           f"{tl.count} frames  ->  {tl.out_seconds:.1f} s of video",
           font=F_FILE, fill=(210, 225, 240, 255), anchor="mm")

    # progress bar
    done = min(1.0, tl.elapsed / TL_MAX_SECS) if TL_MAX_SECS else 0.0
    x0, x1, y = 40, W - 40, 160
    d.rounded_rectangle((x0, y, x1, y + 8), radius=4, fill=(70, 90, 110, 200))
    if done > 0:
        d.rounded_rectangle((x0, y, x0 + (x1 - x0) * done, y + 8), radius=4,
                            fill=(120, 215, 255, 255))
    # Recording dot, top right. Not drawn while rendering -- by then the
    # capture has stopped, and a dot that keeps burning would say otherwise.
    if not stopping:
        cx, cy, r = W - 18, 18, 6
        halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(halo).ellipse((cx - r * 2, cy - r * 2,
                                      cx + r * 2, cy + r * 2),
                                     fill=(230, 40, 50, 90))
        layer.alpha_composite(halo.filter(ImageFilter.GaussianBlur(3)))
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(235, 45, 55, 255))

    img.paste(layer, (0, 0), layer)
    hint_bar(img, "recording  \u2014  MID = stop" if not stopping
             else "rendering the video...")
    return img


def run_timelapse(cap, cv2):
    """Capture until stopped or TL_MAX_SECS, then encode and queue the upload.

    Runs INSIDE run_camera's loop rather than on a thread of its own: one
    camera handle, one owner of the panel, no locking.
    """
    global timelapse_on, _tl, cam_filter
    from timelapse import Timelapse
    stamp = now_local().strftime("%Y-%m-%d_%H%M%S")
    _tl = Timelapse(TL_DIR, stamp, TL_INTERVAL, TL_FPS)
    print(f"timelapse: started, one frame every {TL_INTERVAL:.0f}s "
          f"for up to {TL_MAX_SECS / 60:.0f} min")
    last_panel = None

    while timelapse_on and camera_on:
        if _tl.elapsed >= TL_MAX_SECS:
            break
        if not _tl.due():
            time.sleep(TL_TICK)
            continue
        # The camera buffers frames while we sleep, so the next read would
        # hand back something several seconds stale. Drop those first.
        for _ in range(4):
            cap.grab()
        ok, frame = cap.retrieve()
        if not ok:
            time.sleep(TL_TICK)
            continue
        if cam_mirror:
            frame = cv2.flip(frame, 1)
        if cam_filter:
            try:
                get_filter().apply(frame)     # hamsters get recorded too
            except Exception as e:
                cam_filter = False
                print(f"hamster: {e}")
        _tl.add(frame, cv2)
        last_panel = frame_to_panel(frame, cv2)
        push(timelapse_screen(last_panel, _tl))

    timelapse_on = False
    if last_panel is not None:
        push(timelapse_screen(last_panel, _tl, stopping=True))
    try:
        out = _tl.encode()
        size = out.stat().st_size
        print(f"timelapse: {_tl.count} frames -> {out.name} "
              f"({size / 1e6:.2f} MB, {_tl.out_seconds:.1f} s)")
        _tl.cleanup()
        if size < 5_000_000:
            queue_upload(out)
        else:
            print("timelapse: too big for a multipart upload, kept locally")
    except Exception as e:
        print(f"timelapse: {e}")
        if last_panel is not None:
            img = last_panel.copy()
            big_centred(img, "render failed", F_SAVED, (255, 190, 190))
            hint_bar(img, str(e)[:40], F_FILE)
            push(img)
            time.sleep(3.0)
    finally:
        _tl = None


def run_camera():
    """Owns the panel until the middle button is pressed again."""
    global camera_on, cam_shoot_at, cam_last_saved, cam_filter

    cap, cv2 = open_camera()
    if cap is None:
        img = BG.copy()
        big_centred(img, "no camera" if cv2 else "opencv missing", F_SAVED)
        push(img)
        time.sleep(2.0)
        camera_on = False
        return

    cam_shoot_at = None
    filter_error = None
    entered = time.monotonic()
    shown = 0
    try:
        while camera_on:
            if timelapse_on:
                run_timelapse(cap, cv2)
                entered = time.monotonic()   # bring the hint bar back
                continue
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.02)
                continue
            if cam_mirror:
                frame = cv2.flip(frame, 1)     # once, up front
            if cam_filter:
                try:
                    get_filter().apply(frame)  # hamsters land on the saved
                except Exception as e:         # shot too, not just the preview
                    cam_filter = False         # don't retry 20 times a second
                    filter_error = str(e)[:44]
                    print(f"hamster: {e}")
            now = time.monotonic()

            if cam_shoot_at is not None:
                left = cam_shoot_at - now
                if left <= 0:
                    cam_shoot_at = None
                    path = save_capture(frame, cv2)
                    cam_last_saved = path
                    shot = frame_to_panel(frame, cv2)
                    big_centred(shot, "SAVED", F_SAVED, (140, 255, 200))
                    hint_bar(shot, path.name, F_FILE)
                    push(shot)
                    time.sleep(SAVED_SECS)
                    continue
                img = frame_to_panel(frame, cv2)
                big_centred(img, str(int(left) + 1), F_COUNT)
                push(img)
            else:
                img = frame_to_panel(frame, cv2)
                if filter_error:
                    hint_bar(img, filter_error, F_FILE)
                elif now - entered < 4.0:        # fades out of the way
                    hint_bar(img, "NEXT = photo (hold = timelapse)   MID = exit")
                elif cam_filter:
                    hint_bar(img, "hamster on")
                push(img)
            shown += 1
    finally:
        cap.release()
        if _ham is not None:
            _ham.close()      # MediaPipe's own destructor raises during
                              # interpreter shutdown; close it while the
                              # module globals it needs still exist
        if shown:
            print(f"camera: {shown / max(time.monotonic() - entered, 0.1):.1f} "
                  f"fps at {CAM_W}x{CAM_H}")

# -------------------------------------------------------------- uploads ----
# Google Drive, drive.file scope. Authorise once with gdrive_auth.py.
# Plain HTTP with requests -- no google-api-python-client needed.

GDRIVE_TOKEN = HOME / ".gdrive-token.json"
LEDGER = HOME / ".uploaded.json"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
TOKEN_URL = "https://oauth2.googleapis.com/token"

upload_q = queue.Queue()
_access = {"token": None, "expires": 0.0}


def _ledger():
    try:
        return set(json.loads(LEDGER.read_text()))
    except Exception:
        return set()


def _mark_uploaded(name):
    done = _ledger()
    done.add(name)
    try:
        LEDGER.write_text(json.dumps(sorted(done)))
    except OSError:
        pass


def queue_upload(path):
    upload_q.put(Path(path))


def _access_token(cfg):
    """Swap the long-lived refresh token for a short-lived access token."""
    if _access["token"] and time.monotonic() < _access["expires"]:
        return _access["token"]
    r = requests.post(TOKEN_URL, timeout=20, data={
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        "refresh_token": cfg["refresh_token"],
        "grant_type": "refresh_token"})
    r.raise_for_status()
    tok = r.json()
    _access["token"] = tok["access_token"]
    # renew a minute early rather than discovering expiry mid-upload
    _access["expires"] = time.monotonic() + int(tok.get("expires_in", 3600)) - 60
    return _access["token"]


def _upload_one(path, cfg):
    token = _access_token(cfg)
    meta = {"name": path.name, "parents": [cfg["folder_id"]]}
    boundary = "----npbooth" + str(int(time.time() * 1000))
    # Drive stores whatever type we declare, so a video sent as image/jpeg
    # lands as a file that will not preview or play.
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".mp4": "video/mp4"}.get(
        path.suffix.lower(), "application/octet-stream")
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(meta)}\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    r = requests.post(
        UPLOAD_URL, timeout=90, data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": f"multipart/related; boundary={boundary}"})
    if r.status_code == 401:                 # token died early; force a refresh
        _access["expires"] = 0
        raise RuntimeError("401, will retry with a fresh token")
    r.raise_for_status()
    return r.json().get("id")


def upload_worker():
    """Daemon thread. Never lets a network problem reach the display."""
    try:
        cfg = json.loads(GDRIVE_TOKEN.read_text())
    except Exception:
        print("gdrive: not set up (run gdrive_auth.py) - saving locally only")
        while True:                          # drain so the queue can't grow
            upload_q.get()

    # Anything captured while offline, or before setup, goes up now.
    # This used to look only at CAPTURE_DIR, so a timelapse recorded away from
    # wifi was encoded, queued into a queue nothing was draining, and then lost
    # on the next restart -- the mp4 sat on disk forever with no retry. Both
    # folders are swept now.
    done = _ledger()
    stranded = sorted(CAPTURE_DIR.glob("*.jpg")) + sorted(TL_DIR.glob("*.mp4"))
    for old in stranded:
        if old.name not in done and old.stat().st_size < 5_000_000:
            upload_q.put(old)

    backoff = 5
    while True:
        path = upload_q.get()
        if not path.exists():
            continue
        while True:
            try:
                _upload_one(path, cfg)
                _mark_uploaded(path.name)
                print(f"gdrive: uploaded {path.name}")
                backoff = 5
                break
            except Exception as e:
                print(f"gdrive: {path.name} failed ({e}); retry in {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 600)

# --------------------------------------------------------------- polling ----


def poll():
    global paused_since
    try:
        cur = sp.current_playback()
    except Exception:
        state["message"] = "can't reach Spotify"
        return

    if not cur or not cur.get("item"):
        state["playing"] = False
        if paused_since is None:
            paused_since = time.monotonic()
        # Spotify stops reporting a track a few seconds after you pause. Hold
        # the last one on screen instead of blanking it -- only say "nothing
        # playing" if there has never been anything to show. The slideshow
        # takes over on its own timer.
        state["message"] = None if state["track_id"] else "nothing playing"
        return

    state["message"] = None
    item = cur["item"]
    state["device"] = (cur.get("device") or {}).get("id")
    state["playing"] = bool(cur.get("is_playing"))
    state["progress"] = (cur.get("progress_ms") or 0) / 1000
    state["duration"] = (item.get("duration_ms") or 1) / 1000
    state["title"] = safe(item.get("name", ""))
    state["artist"] = safe(", ".join(a["name"] for a in item.get("artists", [])))

    paused_since = None if state["playing"] else (paused_since or time.monotonic())

    if item.get("id") != state["track_id"]:
        state["track_id"] = item.get("id")
        load_art(item)

# --------------------------------------------------------------- buttons ----

photo_step = 0          # bumped by prev/next while the slideshow is up


def allowed():
    global lock_until
    now = time.monotonic()
    if now < lock_until:
        return False
    lock_until = now + LOCKOUT
    return True


def light(which):
    global flash_what, flash_until
    flash_what, flash_until = which, time.monotonic() + FLASH


def reconverge():
    global last_poll
    last_poll = time.monotonic() - POLL + 0.8


def call(fn):
    try:
        fn(device_id=state["device"])
    except spotipy.SpotifyException as e:
        state["message"] = ("no active device" if e.http_status == 404
                            else "Spotify said no")
    except Exception:
        state["message"] = "can't reach Spotify"


def in_photo_mode():
    return (paused_since is not None
            and time.monotonic() - paused_since >= PAUSE_AFTER)


def on_prev():
    global photo_step, cam_filter
    if not allowed():
        return
    if camera_on:
        if not FILTER_ENABLED:
            return
        cam_filter = not cam_filter
        if cam_filter and _ham is not None:
            _ham.tracks = []               # fresh hamsters each time it's on
        return
    if in_photo_mode():
        photo_step -= 1                    # step back through the photos
        return
    light("prev")
    call(sp.previous_track)
    reconverge()


# The shutter now does two jobs as well -- press for a photo, hold for a
# timelapse -- so it acts on RELEASE for the same reason the middle button
# does. Without this a long hold would also fire a photo on the way in.
next_held = False


def on_next_hold():
    """Shutter held for TL_HOLD: start a timelapse, if we're in camera mode."""
    global next_held, timelapse_on
    next_held = True
    if camera_on and not timelapse_on:
        timelapse_on = True


def on_next():
    global photo_step, cam_shoot_at, next_held
    if next_held:
        next_held = False                  # the hold already did the work
        return
    if not allowed():
        return
    if timelapse_on:
        return                             # the shutter does nothing mid-capture
    if camera_on:
        if cam_shoot_at is None:           # ignore a second press mid-count
            cam_shoot_at = time.monotonic() + COUNTDOWN
        return
    if in_photo_mode():
        photo_step += 1
        return
    light("next")
    call(sp.next_track)
    reconverge()


def on_playpause():
    global paused_since
    if not allowed():
        return
    light("play")
    state["playing"] = not state["playing"]        # optimistic: redraw first
    paused_since = None if state["playing"] else time.monotonic()
    call(sp.start_playback if state["playing"] else sp.pause_playback)
    reconverge()


# The middle button does two jobs, so it acts on RELEASE. A long press fires
# when_held first and sets a flag; the release then knows to stay quiet.
held_fired = False


def on_hold():
    """Middle button held for HOLD_SECS."""
    global held_fired, camera_on
    held_fired = True
    if CAMERA_ENABLED and not camera_on:
        camera_on = True


def on_middle_release():
    global held_fired, camera_on, cam_shoot_at, cam_filter, timelapse_on
    if held_fired:
        held_fired = False                 # the hold already did the work
        return
    if timelapse_on:
        timelapse_on = False               # stop the capture, STAY in camera
        return                             # mode; another press then exits
    if camera_on:
        cam_shoot_at = None
        camera_on = False                  # short press leaves camera mode
        cam_filter = False
        return
    on_playpause()


btn_prev = Button(5)
btn_play = Button(6, hold_time=HOLD_SECS)
btn_next = Button(26, hold_time=TL_HOLD)
btn_prev.when_pressed = on_prev
btn_play.when_held = on_hold
btn_play.when_released = on_middle_release
btn_next.when_held = on_next_hold
btn_next.when_released = on_next

# ------------------------------------------------------------------ main ----


def main():
    global last_poll, phase, photo_step

    if SHOW_OVERLAY:
        threading.Thread(target=weather_worker, daemon=True).start()
    if CAMERA_ENABLED:
        threading.Thread(target=upload_worker, daemon=True).start()

    static_img = None
    static_key = None
    ctrl_key = None
    mode = None
    photos, p_index, p_shown_at, p_current = [], 0, 0.0, None
    ovl_key = None

    while True:
        if camera_on:
            run_camera()                  # owns the panel until it returns
            static_key = ctrl_key = None  # force a full repaint on the way back
            mode = None
            continue

        now = time.monotonic()

        if now - last_poll >= POLL:
            last_poll = now
            poll()
        elif state["playing"] and state["duration"]:
            state["progress"] = min(state["progress"] + TICK, state["duration"])

        want = "photo" if in_photo_mode() and photo_list() else "music"

        # ---------------------------------------------------- slideshow ---
        if want == "photo":
            if mode != "photo":
                mode = "photo"
                photos = photo_list(force=True)
                if SHUFFLE:
                    photos = list(photos)
                    random.shuffle(photos)
                p_index, p_shown_at, p_current = 0, 0.0, None
                static_key = None        # force a full redraw on the way back
                ctrl_key = None

            step = photo_step
            photo_step = 0
            due = p_current is None or step or now - p_shown_at >= PHOTO_SECS
            if due and photos:
                if p_current is not None:
                    p_index = (p_index + (step or 1)) % len(photos)
                nxt = load_photo(photos[p_index])
                p_shown_at = now
                if nxt is not None:
                    if p_current is not None and FADE_STEPS:
                        for i in range(1, FADE_STEPS + 1):
                            push(with_overlay(
                                Image.blend(p_current, nxt, i / FADE_STEPS)))
                    else:
                        push(with_overlay(nxt))
                    p_current = nxt           # kept clean, without the overlay
                    ovl_key = overlay_key()
            elif p_current is not None and SHOW_OVERLAY:
                k = overlay_key()
                if k != ovl_key:              # the minute ticked, or new weather
                    ovl_key = k
                    band = crop_band(p_current, OVL_BAND)
                    draw_overlay(band, origin=(OVL_BAND[0], OVL_BAND[1]))
                    push(band, OVL_BAND)      # ~7 ms, once a minute
            time.sleep(TICK)
            continue

        # -------------------------------------------------------- music ---
        mode = "music"
        lit = flash_what if now < flash_until else None
        key = (state["track_id"], state["message"],
               state["title"], state["artist"])
        ctrl = (state["playing"], lit)

        if key != static_key:
            static_key, ctrl_key = key, ctrl
            static_img = draw_static()
            push(compose(static_img, lit))               # whole frame, ~20 ms
        elif ctrl != ctrl_key and not state["message"]:
            ctrl_key = ctrl
            band = crop_band(static_img, CTRL_BAND)
            paste_transport(band, lit, at=(0, 0))
            push(band, CTRL_BAND)                        # ~2 ms
        elif not state["message"]:
            if state["playing"]:
                phase += 2 * math.pi * TICK / WAVE_SECS
            band = crop_band(static_img, BAND)
            draw_wave(band)
            push(band, BAND)                             # ~4 ms

        time.sleep(TICK)


if __name__ == "__main__":
    main()
