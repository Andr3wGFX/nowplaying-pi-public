#!/usr/bin/env python3
"""
Re-measure the expression thresholds under the settings that actually ship.

    source ~/np/bin/activate
    python ~/np/tools/recal.py

An earlier calibration measured faces at full resolution in IMAGE mode. The
filter runs VIDEO mode on a downscaled frame, and that changes the
numbers a lot -- mouthSmile during an open mouth read 0.72 at 320 px and 0.01
at 640 px. Thresholds set from the wrong configuration are just a different
kind of guess.

So: the same four poses, run twice, at the two candidate sizes, through the
identical code path the filter uses. About a minute and a half.
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

HOME = Path.home() / "np"
MODEL = HOME / "face_landmarker.task"

import cv2                                            # noqa: E402
import numpy as np                                    # noqa: E402
import mediapipe as mp                                # noqa: E402
from mediapipe.tasks import python as mpp             # noqa: E402
from mediapipe.tasks.python import vision             # noqa: E402

SIZES = [480, 640]
PHASES = [("NEUTRAL", "relaxed, look at the lens"),
          ("SMILE",   "grin -- a normal one, not a rictus"),
          ("OPEN",    "mouth wide open, and do NOT smile"),
          ("BLINK",   "eyes shut, keep them shut")]
SECS = 4.0

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
if not cap.isOpened():
    sys.exit("camera didn't open")
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
for _ in range(5):
    cap.read()

data = {}
print("\nFour poses, twice over. Hold each one steadily for four seconds.")
print("The OPEN pose matters most: open wide and keep your face otherwise")
print("blank, because that is the case that has been misreading.\n")

for side in SIZES:
    lm = vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(
            base_options=mpp.BaseOptions(model_asset_path=str(MODEL)),
            running_mode=vision.RunningMode.VIDEO, num_faces=4,
            output_face_blendshapes=True))
    print(f"--- detection at {side} px " + "-" * 40)
    t_base = time.monotonic()
    for name, hint in PHASES:
        for n in (3, 2, 1):
            print(f"\r  next: {name} ({hint})   in {n}...", end="", flush=True)
            time.sleep(1)
        print(f"\r  >>> {name}  --  {hint}" + " " * 24)
        jaw, smile, blink = [], [], []
        t0 = time.monotonic()
        while time.monotonic() - t0 < SECS:
            ok, f = cap.read()
            if not ok:
                continue
            h, w = f.shape[:2]
            sc = min(1.0, side / max(h, w))
            small = cv2.resize(f, (int(w * sc), int(h * sc))) if sc < 1 else f
            img = mp.Image(image_format=mp.ImageFormat.SRGB,
                           data=cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
            r = lm.detect_for_video(img, int((time.monotonic() - t_base) * 1000))
            if not r.face_blendshapes:
                continue
            c = {b.category_name: b.score for b in r.face_blendshapes[0]}
            jaw.append(c.get("jawOpen", 0.0))
            smile.append((c.get("mouthSmileLeft", 0.0)
                          + c.get("mouthSmileRight", 0.0)) / 2)
            blink.append((c.get("eyeBlinkLeft", 0.0)
                          + c.get("eyeBlinkRight", 0.0)) / 2)
        data[(side, name)] = {"jaw": jaw, "smile": smile, "blink": blink}
        print(f"      {len(jaw)} readings")
    lm.close()
cap.release()


def stat(side, phase, key):
    v = data.get((side, phase), {}).get(key) or [0.0]
    a = np.array(v)
    return a.mean(), np.percentile(a, 10), np.percentile(a, 90)


print("\n" + "=" * 74)
print("  copy this whole block back to Claude")
print("=" * 74)
for key in ("jaw", "smile", "blink"):
    print(f"\n  {key.upper()}      " + "".join(f"{p:>16}" for p, _ in PHASES))
    for side in SIZES:
        line = f"  {side}px mean " + "".join(
            f"{stat(side, p, key)[0]:>16.3f}" for p, _ in PHASES)
        print(line)
        print(f"        p10-p90 " + "".join(
            f"{stat(side, p, key)[1]:>8.2f}{stat(side, p, key)[2]:>8.2f}"
            for p, _ in PHASES))

print("\n  separation (how far the target pose sits above the worst other pose):")
for key, target in (("jaw", "OPEN"), ("smile", "SMILE"), ("blink", "BLINK")):
    for side in SIZES:
        on = stat(side, target, key)[0]
        off = max(stat(side, p, key)[0] for p, _ in PHASES if p != target)
        print(f"  {key:<6} {side}px:  {target} {on:.3f}   worst other {off:.3f}"
              f"   gap {on - off:+.3f}")
