#!/usr/bin/env python3
"""
Head turn and head tilt, from the face model you are already running.

    source ~/np/bin/activate
    python ~/np/tools/headcheck.py

catherpiee's hammyhamster repo pulls two more expressions out of MediaPipe's
`facial_transformation_matrixes` -- a 4x4 rotation matrix that comes from the
SAME FaceLandmarker you already run, for no extra model and no extra pass. Its
README flags that the pitch sign was never verified against a live camera, so
this verifies it against yours before any of it goes into the filter.

Four poses. Watch the sign and the size of the numbers.
"""
import math
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


def yaw_degrees(m):
    """R[0][2] tracks rotation about the vertical axis (turning left/right)."""
    return math.degrees(math.asin(max(-1.0, min(1.0, m[0][2]))))


def pitch_degrees(m):
    """R[1][2] tracks rotation about the horizontal axis (nodding).
    Sign taken from hammyhamster's code; this script exists to check it."""
    return math.degrees(math.asin(max(-1.0, min(1.0, -m[1][2]))))


lm = vision.FaceLandmarker.create_from_options(
    vision.FaceLandmarkerOptions(
        base_options=mpp.BaseOptions(model_asset_path=str(MODEL)),
        running_mode=vision.RunningMode.VIDEO, num_faces=1,
        output_face_blendshapes=True,
        output_facial_transformation_matrixes=True))   # <- the new flag

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
if not cap.isOpened():
    sys.exit("camera didn't open")
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1024)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 768)
for _ in range(5):
    cap.read()

POSES = [("STRAIGHT AHEAD", "look at the lens"),
         ("TURN LEFT",      "turn your head to your left, eyes follow"),
         ("TURN RIGHT",     "turn your head to your right"),
         ("LOOK DOWN",      "tilt your chin down, sad-hamster style"),
         ("LOOK UP",        "tilt your chin up")]
SECS = 3.0
out = {}
t_base = time.monotonic()

print("\nFive poses, three seconds each. Hold each one still.\n")
for name, hint in POSES:
    for n in (3, 2, 1):
        print(f"\r  next: {name} ({hint})   in {n}...", end="", flush=True)
        time.sleep(1)
    print(f"\r  >>> {name}  --  {hint}" + " " * 28)
    yaws, pitches, frames = [], [], 0
    t0 = time.monotonic()
    while time.monotonic() - t0 < SECS:
        ok, f = cap.read()
        if not ok:
            continue
        h, w = f.shape[:2]
        sc = min(1.0, 480 / max(h, w))
        small = cv2.resize(f, (int(w * sc), int(h * sc)))
        img = mp.Image(image_format=mp.ImageFormat.SRGB,
                       data=cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
        r = lm.detect_for_video(img, int((time.monotonic() - t_base) * 1000))
        frames += 1
        if not r.facial_transformation_matrixes:
            continue
        m = r.facial_transformation_matrixes[0]
        yaws.append(yaw_degrees(m))
        pitches.append(pitch_degrees(m))
    out[name] = (yaws, pitches, frames)
    print(f"      {len(yaws)}/{frames} frames gave a matrix")
lm.close()
cap.release()

print("\n" + "=" * 62)
print("  copy this back to Claude")
print("=" * 62)
print(f"  {'pose':<18}{'yaw mean':>11}{'yaw p10-p90':>18}{'pitch mean':>13}")
for name, _ in POSES:
    y, p, _ = out[name]
    if not y:
        print(f"  {name:<18}{'no matrix':>11}")
        continue
    y, p = np.array(y), np.array(p)
    print(f"  {name:<18}{y.mean():>11.1f}"
          f"{np.percentile(y, 10):>9.1f}{np.percentile(y, 90):>9.1f}"
          f"{p.mean():>13.1f}")

if out["LOOK DOWN"][1] and out["LOOK UP"][1]:
    down = np.mean(out["LOOK DOWN"][1])
    up = np.mean(out["LOOK UP"][1])
    print(f"\n  pitch sign check: looking DOWN gives {down:+.1f}, "
          f"UP gives {up:+.1f}")
    print("  -> " + ("sign is correct as written (down is positive)"
                     if down > up else
                     "SIGN IS FLIPPED for this camera -- hammyhamster's README warned "
                     "about exactly this"))
