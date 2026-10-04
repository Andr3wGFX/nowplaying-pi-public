#!/usr/bin/env python3
"""
Camera-mode feasibility check.    ~/np/bin/python ~/np/tools/cameracheck.py

Builds the display object ONCE and changes the SPI clock on the live object.
(Rebuilding it for every speed leaks the GPIO pins, so only the first speed
would ever really run -- an earlier version of this script did exactly that.)

Stage 2 needs you to WATCH THE PANEL, not the terminal.
"""
import glob
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageFont

W, H = 320, 240
SPEEDS_MHZ = [4, 8, 16, 24, 32, 48, 64]
LOOK_SECS = 4.0

notes = []


def say(line=""):
    print(line)
    notes.append(line)


def rule(title):
    print()
    say("=" * 60)
    say(f"  {title}")
    say("=" * 60)


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True,
                              text=True, timeout=15).stdout.strip()
    except Exception as e:
        return f"({e})"


# ----------------------------------------------------- 1. prerequisites ---
rule("1. Prerequisites")

try:
    from st7789 import ST7789
    say("st7789            : ok")
except ImportError as e:
    sys.exit(f"st7789 missing ({e}). Run:  source ~/np/bin/activate")

try:
    import cv2
    say(f"python3-opencv    : ok (cv2 {cv2.__version__})")
    HAVE_CV2 = True
except ImportError:
    say("python3-opencv    : MISSING -> sudo apt install -y python3-opencv")
    HAVE_CV2 = False

vids = sorted(glob.glob("/dev/video*"))
say(f"/dev/video*       : {' '.join(vids) if vids else 'NONE'}")
cam = [l for l in sh("lsusb").splitlines()
       if "logitech" in l.lower() or "webcam" in l.lower()]
say(f"webcam on USB     : {cam[0] if cam else 'not seen'}")

FONT_DIR = "/usr/share/fonts/truetype/quicksand"
try:
    BIG = ImageFont.truetype(f"{FONT_DIR}/Quicksand-Bold.ttf", 32)
    MID = ImageFont.truetype(f"{FONT_DIR}/Quicksand-Bold.ttf", 17)
    SMALL = ImageFont.truetype(f"{FONT_DIR}/Quicksand-Medium.ttf", 14)
except OSError:
    BIG = MID = SMALL = ImageFont.load_default()


def pattern(label, step, n, total):
    """Fine stripes catch corruption; the moving bar catches a frozen panel."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for x in range(0, W, 2):                        # 1 px stripes
        if ((x // 2) + step) % 2 == 0:
            d.rectangle((x, 0, x, 74), fill=(255, 255, 255))
    for i, c in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255),
                           (255, 255, 0), (0, 255, 255), (255, 0, 255)]):
        d.rectangle((i * W // 6, 77, (i + 1) * W // 6 - 1, 119), fill=c)
    for i in range(16):
        v = i * 17
        d.rectangle((i * W // 16, 122, (i + 1) * W // 16 - 1, 142),
                    fill=(v, v, v))
    bx = (step * 11) % (W - 40)                     # sliding block = alive
    d.rectangle((bx, 147, bx + 40, 163), fill=(90, 230, 255))
    d.text((10, 168), label, font=BIG, fill=(255, 255, 255))
    d.text((10, 206), f"pattern {n} of {total}", font=MID, fill=(255, 220, 120))
    d.text((10, 224), "stripes crisp? block sliding?", font=SMALL,
           fill=(170, 195, 220))
    return img


# ------------------------------------------------------ 2. SPI ladder -----
rule("2. SPI speed ladder")

print(f"""
  WATCH THE PANEL. You will see {len(SPEEDS_MHZ)} patterns, {LOOK_SECS:.0f}s each,
  each labelled "pattern N of {len(SPEEDS_MHZ)}" so you know none were skipped.

      CLEAN  - stripes crisp, colours right, blue block sliding smoothly
      BAD    - torn/smeared stripes, speckles, wrong colours, block stuck

  Note the FASTEST speed that still looks clean.
""")
input("  Press Enter when you're looking at the panel... ")

disp = ST7789(port=0, cs=0, dc=25, rst=27, backlight=18, width=W, height=H,
              rotation=0, invert=True, spi_speed_hz=4_000_000)
disp.reset()      # library leaves RST low and never raises it
disp._init()

say("")
say(f"{'asked':>8} {'actual':>9} {'ms/frame':>9} {'fps':>6}")
seen = []
for n, mhz in enumerate(SPEEDS_MHZ, 1):
    try:
        disp._spi.max_speed_hz = int(mhz * 1_000_000)
        actual = disp._spi.max_speed_hz / 1e6      # the Pi rounds to a divisor
        disp.display(pattern(f"{mhz} MHz", 0, n, len(SPEEDS_MHZ)))  # warm-up
        t0, frames = time.monotonic(), 0
        while time.monotonic() - t0 < LOOK_SECS:
            disp.display(pattern(f"{mhz} MHz", frames, n, len(SPEEDS_MHZ)))
            frames += 1
        dt = (time.monotonic() - t0) / frames
        say(f"{mhz:>6}MHz {actual:>8.1f}M {dt*1000:>8.1f} {1/dt:>6.1f}")
        seen.append(mhz)
    except Exception as e:
        say(f"{mhz:>6}MHz  ERROR {type(e).__name__}: {e}")

print()
print(f"  Speeds actually shown: {seen}")
best = input("  Fastest that looked CLEAN: ").strip()
try:
    BEST_MHZ = int(best)
except ValueError:
    BEST_MHZ = 4
say("")
say(f"fastest clean speed: {BEST_MHZ} MHz  (judged by eye)")

# --------------------------------------------------- 3. live webcam ------
rule("3. Live webcam")

if not HAVE_CV2 or not vids:
    say("skipped - need python3-opencv and a camera device")
else:
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    if not cap.isOpened():
        say("camera did NOT open")
    else:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        ok, frame = cap.read()
        if not ok:
            say("camera opened but gave no frame")
        else:
            say(f"frame size        : {frame.shape[1]}x{frame.shape[0]}")
            t0, n = time.monotonic(), 0
            for _ in range(30):
                if cap.read()[0]:
                    n += 1
            say(f"capture only      : {n/(time.monotonic()-t0):.1f} fps")

            disp._spi.max_speed_hz = int(BEST_MHZ * 1_000_000)
            print(f"\n  Live for 15 s at {BEST_MHZ} MHz -- wave at the camera.")
            print("  Smooth enough to aim a shot with?\n")
            t0, shown = time.monotonic(), 0
            while time.monotonic() - t0 < 15:
                ok, frame = cap.read()
                if not ok:
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                disp.display(Image.fromarray(rgb).resize((W, H),
                                                         Image.BILINEAR))
                shown += 1
            say(f"end-to-end        : {shown/(time.monotonic()-t0):.1f} fps "
                f"at {BEST_MHZ} MHz")
        cap.release()

rule("SUMMARY - copy everything below back to Claude")
print()
print("\n".join(notes))
print()
print("Also say: did the live feed feel usable, or too laggy to aim?")
