# Build notes — the Pi 4 era

The original build: **Raspberry Pi 4 Model B (2 GB) + Waveshare 2inch LCD Module (ST7789V,
320×240)**, three tactile buttons on a breadboard, Logitech C270 webcam. The device has since moved
to a Pi 5 — see `build-notes-pi5.md` for everything after that. These notes are kept because every
lesson in them still applies.

## ⚠ Three bugs that each cost real time — read before debugging anything

**1. `st7789` 1.0.1 never releases RST.** It requests the reset pin as an output driven LOW
(`LineSettings(direction=OUTPUT, output_value=INACTIVE)`) and `__init__` never calls `self.reset()`.
RST is active-low, so the controller sits in permanent hardware reset: backlight on, panel uniformly
lit, **no image and no error**. Always call `disp.reset()` then `disp._init()` after constructing.

**2. Absolute coordinates on a cropped strip.** Partial-update code crops a band out of the frame and
draws into it. Any helper that draws at *screen* coordinates lands off-canvas there and silently
blanks the strip. This wiped the transport row on every pause. Every band-drawing helper now takes an
explicit `origin`/`at`. **Test partial updates by pixel, never by push count** — the push-count test
reported "full +0, partial +2" and sailed straight past a completely blank strip.

**3. GPIO pins leak when you rebuild `ST7789` in a loop.** `disp = ST7789(...)` evaluates the RHS
before rebinding, so the old object still holds GPIO 25/27/18 and the new one dies with
`OSError [Errno 16] Device or resource busy`. This made the first SPI benchmark only ever run its
*first* speed while appearing to run all seven. **Don't rebuild the display to change speed; set
`disp._spi.max_speed_hz` on the live object.** And put a moving element in any test pattern, or a
frozen panel looks identical to a working one.

## SPI speed — 64 MHz, measured

`tools/cameracheck.py` ran a ladder 4→64 MHz. **64 MHz asked (~62.5 actual) is clean on jumper
wiring.** An earlier "32 MHz is unreliable" note was a false inference made while bug #1 meant
nothing displayed at any speed.

Full frame 320×240×2 = 153,600 B: **307 ms at 4 MHz → ~20 ms at 62.5 MHz.** `SPI_HZ = 64_000_000`,
`TICK = 0.1`. Step down to 32 MHz if torn stripes ever appear.

## Wiring — Waveshare 2inch LCD

Via the module's **PH2.0 socket**. **Wire colours are not a spec**; count positions from the VCC end.

| Pos | Module | Signal | BCM | Pin |
|---|---|---|---|---|
| 1 | VCC | 3.3 V | — | 17 |
| 2 | GND | GND | — | 20 |
| 3 | DIN | SPI0 MOSI | 10 | 19 |
| 4 | CLK | SPI0 SCLK | 11 | 23 |
| 5 | CS | SPI0 CE0 | 8 | 24 |
| 6 | DC | data/command | 25 | 22 |
| 7 | RST | reset | 27 | 13 |
| 8 | BL | backlight | 18 | 12 |

Buttons: prev pin 29 (GPIO5), middle pin 31 (GPIO6), next pin 37 (GPIO26), grounds joined to pin 39.
Identical on the Pi 5.

**Pi 4 header orientation.** Component side up, header along the top edge, Ethernet right: **pin 1 is
far LEFT of the BOTTOM row**; **top row = EVEN, bottom row = ODD**. Confirmed against the board's own
`pinout` output — at least one popular online Pi 4 pinout article has this backwards.

## Spotify OAuth

`SpotifyOAuth(..., open_browser=False)` skips spotipy's local-server branch entirely and uses the
**interactive paste** flow: it prints the authorize URL and reads the redirected URL from stdin.
**No SSH port-forward is needed.** The "can't reach this site" page at
`127.0.0.1:8080/callback?code=…` is expected; the address bar is the payload. Token caches to
`~/np/.spotify-cache`.

Spotify stops reporting a track a few seconds after pause (`item: null`). Don't blank the screen —
hold the last track and only say "nothing playing" if nothing was ever seen.

## Partial-window SPI updates

`set_window(x0,y0,x1,y1)` is public and `image_to_data()` returns plain bytes, so a strip can be sent
alone. Verified byte-exact: strip-pushes vs a full-frame render gave **0 differing pixels of 76,800**
(compare RGB565-to-RGB565, never against a full-precision PIL image). Bands in use: progress
(320×45), transport (176×48), idle overlay (280×102).

## Display design

- **Background** `background.png`, fit-cover, `BG_BLUR=3 BG_SAT=0.9 BG_DIM=0.35`. The raw aurora
  image is unreadable behind text; blur + dim fixes it while keeping the colour.
- **Font: Mochi Boom DEMO** — ⚠ **its ten digits are watermark glyphs** (identical 1148-point
  outlines vs ~48 for letters, found with fontTools `RecordingPen`). Words use Mochi, anything with
  digits uses Quicksand. This bit four times: the clock, the progress times, the capture filename,
  and the timelapse screen. **Check any free/demo font for watermarked or missing glyphs before
  designing around it.**
- Mochi has **no accented characters**; `safe()` does NFKD + drops combining marks, so
  "Sigur Rós & Björk" → "Sigur Ros & Bjork" rather than empty boxes.
- **Snake progress bar**: `y = WAVE_Y + amp·sin(2πx/WAVE_LEN − phase)`, amplitude eased to 0 at both
  ends; the flat grey rail is drawn **from the playhead rightwards only** so none shows under the wave.
- All round shapes drawn at **4× and LANCZOS-shrunk** (Pillow doesn't antialias polygons/ellipses).
  RGBA layers must start as **background colour at alpha 0**, never transparent black, or the
  downscale bleeds dark fringes.
- **Slideshow** after `PAUSE_AFTER = 10 s` paused; 8 s per photo, 4-step crossfade; prev/next step
  photos. Photos in `~/np/photos/`, pre-converted to 320×240 by `convert_photos.py`.
- **Idle overlay**: big clock + date + weather, bottom left, blurred dark halo. Location and timezone
  come from `.env` (`NP_LAT`, `NP_LON`, `NP_TIMEZONE`). Pin a real IANA zone: places without DST are
  an hour out half the year under a generic zone like "Mountain Time". Weather from **Open-Meteo** (no API key),
  fetched on a **daemon thread** so a 10 s network timeout can never stall the display.

## Camera mode

- **Middle button held 3 s** enters; short press exits. The middle button therefore acts on
  **release**: `when_held` sets a flag, `when_released` checks it and stays quiet — otherwise a long
  press also fires play/pause. There is a regression test for exactly this (`tests/testcamera.py`).
- Saves `~/np/captures/YYYY-MM-DD_HHMMSS.jpg` at 1024×768 (4:3 so it maps to the panel with no crop).
  C270 measured at **19.2 fps at 640×480** — with SPI at 62.5 MHz the camera, not the panel, is the
  bottleneck.
- `cv2` is imported **inside** `open_camera()` so the program still runs with no webcam or OpenCV.
  Use the apt `python3-opencv` (the venv has `--system-site-packages`); pip's OpenCV tries to build
  from source on ARM.

## Google upload — why Drive, not Photos

- **Google Photos**: `photoslibrary.appendonly` survived the 31 Mar 2025 scope purge, but Photos API
  apps must pass OAuth verification review, and an app left in **Testing** has **all refresh tokens
  expire after exactly 7 days** — weekly re-auth on a headless device.
- **Google Drive `drive.file`** is classified **non-sensitive**, touches only app-created files, and
  can be published to production without restricted-scope review — so the refresh token persists.

## Test harness

`tests/stubs/` holds fake `st7789`, `gpiozero`, `spotipy` and `cv2`. The fake `ST7789` keeps a real
**framebuffer** and decodes RGB565 back to RGB, so `import nowplaying` runs the real program
unmodified and every push can be inspected. The fake `cv2` yields synthetic moving frames.

## Enclosure constraints

- Module PCB 58 × 35 mm; active glass 40.8 × 30.6 mm → window 41 × 31 mm.
- `st7789` refuses rotation 90/270 on a non-square panel → **0 or 180 only**, so the pin edge must end
  up LEFT or RIGHT, never top/bottom.
- Recess the panel 1–2 mm; lean the front back ~15°. Internal depth ≥ 25 mm, width ≥ 75 mm.
- Keep the wire run short — it carries 62.5 MHz.

## Method note

Every large time sink here — the RST bug, a phantom SSH port-forward, the watermarked digits, the
blanked transport strip, the GPIO leak that invalidated a whole benchmark — was an assumption that
minutes of reading source or one pixel-level assertion would have caught. Read the library. Verify by
looking at the actual output, not at a proxy metric.
