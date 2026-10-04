#!/usr/bin/env python3
"""
Watch the filter's live numbers while you use it the way you actually use it.

    source ~/np/bin/activate
    python ~/np/tools/livestate.py

recal.py measured jawOpen at 0.513 with you square-on to the lens at 640x480.
The camera mode captures at 1024x768 with you looking at the PANEL, not the
camera, and probably closer to it. This runs the real filter at the real
camera settings and prints the smoothed numbers four times a second, so we can
see what the signal looks like in the situation that is actually failing.

Sit exactly where you sit when you use the photo booth. Look at the panel, not
the webcam. Open your mouth the way you would for a photo -- not the
exaggerated calibration version. Then try it again square-on to the lens.
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

HOME = Path.home() / "np"
if str(HOME) not in sys.path:
    sys.path.insert(0, str(HOME))

import cv2                                            # noqa: E402
from hamster import (HamsterFilter, OPEN_ON, OPEN_OFF,   # noqa: E402
                     SMILE_ON, BLINK_ON)

CAM_W, CAM_H = 1024, 768          # exactly what nowplaying.py uses
SECONDS = 30

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
if not cap.isOpened():
    sys.exit("camera didn't open")
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
for _ in range(5):
    cap.read()
ok, probe = cap.read()
print(f"capture: {probe.shape[1]}x{probe.shape[0]}"
      f"   thresholds: open>{OPEN_ON} (off {OPEN_OFF}), "
      f"smile>{SMILE_ON}, blink>{BLINK_ON}")

ham = HamsterFilter(HOME / "stickers", HOME / "face_landmarker.task",
                    detect_every=2, max_side=480)
print(f"detect every {ham.detect_every} frames at max_side {ham.max_side}, "
      f"{'VIDEO' if ham.video_mode else 'IMAGE'} mode\n")
print("  30 seconds. Open and close your mouth as you normally would.\n")
print(f"  {'t':>5}{'faces':>7}{'jaw':>8}{'smile':>8}{'blink':>8}"
      f"{'state':>9}{'face % of frame':>17}")

t0 = time.monotonic()
frames, last = 0, 0.0
jaw_peak, jaw_over = 0.0, 0
samples = 0
while time.monotonic() - t0 < SECONDS:
    ok, frame = cap.read()
    if not ok:
        continue
    frame = cv2.flip(frame, 1)          # nowplaying mirrors before filtering
    ham.apply(frame)
    frames += 1
    now = time.monotonic() - t0
    if now - last < 0.25:
        continue
    last = now
    if not ham.tracks:
        print(f"  {now:5.1f}{0:>7}{'-':>8}{'-':>8}{'-':>8}{'-':>9}"
              f"{'NO FACE':>17}")
        continue
    t = ham.tracks[0]
    s = t["s"] or {"jaw": 0, "smile": 0, "blink": 0}
    samples += 1
    jaw_peak = max(jaw_peak, s["jaw"])
    if s["jaw"] > OPEN_ON:
        jaw_over += 1
    pct = t["w"] / frame.shape[1] * 100
    print(f"  {now:5.1f}{len(ham.tracks):>7}{s['jaw']:>8.3f}{s['smile']:>8.3f}"
          f"{s['blink']:>8.3f}{t['expr']:>9}{pct:>16.0f}%")

fps = frames / (time.monotonic() - t0)
ham.close()
cap.release()
print(f"\n  loop ran at {fps:.1f} fps -> about {fps / ham.detect_every:.1f} "
      f"detections a second")
print(f"  smoothed jawOpen peaked at {jaw_peak:.3f} "
      f"(recal.py measured 0.513 square-on at 640x480)")
if samples:
    print(f"  cleared OPEN_ON in {jaw_over * 100 // samples}% of samples")
print("\n  copy this back to Claude")
