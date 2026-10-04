#!/usr/bin/env python3
"""Geometry test for the MediaPipe filter, with a fake model.

Verifies BY PIXEL that the hamster lands where the eyes are and is scaled to
the measured eye separation -- not that some number of pastes happened.
"""
import json
import shutil
import time
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "stubs_mp"))  # fake mediapipe only -- NOT the
                                           # stubs/ dir, which also holds a fake
                                           # cv2 that would shadow the real one
sys.path.insert(0, str(HERE.parent))   # repo root: hamster.py

import cv2
import numpy as np
import mediapipe as mp
from hamster import HamsterFilter, MIN_DWELL, OPEN_EXIT_DWELL

fails = []
def check(name, got, want, tol=0):
    ok = abs(got - want) <= tol if isinstance(want, (int, float)) else got == want
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}: {got}" + ("" if ok else f"  (want {want})"))
    if not ok:
        fails.append(name)

# ---- a sticker with eyes in known places -----------------------------------
tmp = Path(tempfile.mkdtemp())
S_W, S_H = 200, 200
img = np.zeros((S_H, S_W, 3), np.uint8)
img[:] = (30, 60, 200)                      # solid, so it's unmistakable
cv2.imwrite(str(tmp / "test.jpg"), img)
(tmp / "stickers.json").write_text(json.dumps({"stickers": [
    {"file": "test.jpg", "eye_left": [60, 80], "eye_right": [140, 80],
     "expr": "neutral"}]}))
STICKER_SEP = 80.0

# ---- a frame with a "face" whose eyes are 80 px apart -----------------------
FW, FH = 640, 480
EYE_L, EYE_R, EYE_Y = 200.0, 280.0, 150.0
WANT_SEP = EYE_R - EYE_L
MID = ((EYE_L + EYE_R) / 2, EYE_Y)

marks = [(0.30, 0.20)] * 478                 # a plausible face blob
marks[0] = (0.30, 0.20)                      # bbox corner
marks[1] = (0.55, 0.62)                      # bbox other corner
marks[468] = (EYE_L / FW, EYE_Y / FH)        # iris A
marks[473] = (EYE_R / FW, EYE_Y / FH)        # iris B
mp.FAKE_LANDMARKS = [marks]
mp.FAKE_BLENDSHAPES = [{"jawOpen": 0.0, "mouthSmileLeft": 0.0,
                        "mouthSmileRight": 0.0,
                        "eyeBlinkLeft": 0.31, "eyeBlinkRight": 0.30}]

COVER_W, COVER_H = 3.0, 3.3
f = HamsterFilter(tmp, model_path=__file__,          # any existing file
                  cover_w=COVER_W, cover_h=COVER_H,
                  detect_every=2, max_side=320)

print("1. running mode")
check("VIDEO mode chosen", f.video_mode, True)

frame = np.full((FH, FW, 3), 90, np.uint8)
for _ in range(3):                            # detect, skip, detect -> confirmed
    f.apply(frame)

print("\n2. landmark handling")
check("iris landmarks seen", f.n_landmarks, 478)
t = f.tracks[0]
check("measured eye separation", round(t["sep"], 3), WANT_SEP, tol=0.01)
check("eye midpoint x", round(t["ex"], 3), MID[0], tol=0.01)
check("eye midpoint y", round(t["ey"], 3), MID[1], tol=0.01)
check("expression", t["expr"], "neutral")

print("\n3. where the sticker actually landed, measured in pixels")
changed = np.any(frame != 90, axis=2)
ys, xs = np.nonzero(changed)
x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
w, h = x1 - x0 + 1, y1 - y0 + 1
print(f"  pasted rect: x {x0}..{x1}  y {y0}..{y1}   ({w} x {h})")
check("width  == eye_sep * cover_w", w, WANT_SEP * COVER_W, tol=1)
check("height == eye_sep * cover_h", h, WANT_SEP * COVER_H, tol=1)

# the hamster's eyes should sit exactly on the person's eyes
k = WANT_SEP / STICKER_SEP
ham_eye_x = x0 + (100 - (100 - STICKER_SEP * COVER_W / 2)) * k
ham_eye_y = y0 + (80 - (80 - STICKER_SEP * COVER_H / 2)) * k
check("hamster's eye-line x sits on the face's", round(ham_eye_x, 1), MID[0], tol=1)
check("hamster's eye-line y sits on the face's", round(ham_eye_y, 1), MID[1], tol=1)

print("\n4. scale really follows the eyes, not the bounding box")
# Move the eyes closer together; the sticker must shrink by the same ratio.
marks[468] = ((MID[0] - 20) / FW, EYE_Y / FH)
marks[473] = ((MID[0] + 20) / FW, EYE_Y / FH)
mp.FAKE_LANDMARKS = [marks]
f2 = HamsterFilter(tmp, model_path=__file__, cover_w=COVER_W, cover_h=COVER_H,
                   detect_every=2, max_side=320)
frame2 = np.full((FH, FW, 3), 90, np.uint8)
for _ in range(3):
    f2.apply(frame2)
ys2, xs2 = np.nonzero(np.any(frame2 != 90, axis=2))
w2 = xs2.max() - xs2.min() + 1
print(f"  eyes 80 px apart -> {w} px wide;  eyes 40 px apart -> {w2} px wide")
check("halving eye separation halves the sticker", w2, w / 2, tol=1)

print("\n5. no face -> the hamster survives a couple of misses, then goes")
mp.FAKE_LANDMARKS, mp.FAKE_BLENDSHAPES = [], []
# max_miss=2 with detect_every=2 means the track is DESIGNED to outlive a few
# frames, so it keeps pasting while it drains. That is the point -- it stops a
# hamster flickering off on one missed detection. Drain it on a scratch frame,
# then check a fresh frame is left alone.
scratch = np.full((FH, FW, 3), 90, np.uint8)
n = 0
while f.tracks and n < 40:
    f.apply(scratch)
    n += 1
check("tracks cleared", len(f.tracks), 0)
print(f"  took {n} frames to drain")
check("drains in a few frames, not indefinitely", n <= 10, True)
frame3 = np.full((FH, FW, 3), 90, np.uint8)
for _ in range(4):
    f.apply(frame3)
check("a fresh frame is then untouched", int(np.any(frame3 != 90)), 0)

print("\n6. expressions drive the sticker choice")
(tmp / "stickers.json").write_text(json.dumps({"stickers": [
    {"file": "test.jpg", "eye_left": [60, 80], "eye_right": [140, 80], "expr": "neutral"},
    {"file": "test.jpg", "eye_left": [60, 80], "eye_right": [140, 80], "expr": "open"},
    {"file": "test.jpg", "eye_left": [60, 80], "eye_right": [140, 80], "expr": "blink"}]}))
marks[468] = (EYE_L / FW, EYE_Y / FH)
marks[473] = (EYE_R / FW, EYE_Y / FH)
mp.FAKE_LANDMARKS = [marks]
f3 = HamsterFilter(tmp, model_path=__file__, detect_every=1, max_side=320)
frame4 = np.full((FH, FW, 3), 90, np.uint8)
OPEN_POSE  = {"jawOpen": 0.51, "mouthSmileLeft": 0.02,
              "mouthSmileRight": 0.01, "eyeBlinkLeft": 0.24, "eyeBlinkRight": 0.24}
BLINK_POSE = {"jawOpen": 0.025, "mouthSmileLeft": 0.00,
              "mouthSmileRight": 0.00, "eyeBlinkLeft": 0.70, "eyeBlinkRight": 0.68}

def drive(pose, n=12):
    mp.FAKE_BLENDSHAPES = [pose]
    for _ in range(n):
        f3.apply(frame4)
    return f3.tracks[0]

t = drive(OPEN_POSE)
check("state open", t["expr"], "open")
check("...wearing an 'open' sticker", f3.stickers[t["sticker"]]["expr"], "open")

# MIN_DWELL: a second pose arriving immediately must NOT take the state.
t = drive(BLINK_POSE)
# leaving `open` is the slowest transition of all, on purpose
check("blocked right after an open", t["expr"], "open")
time.sleep(OPEN_EXIT_DWELL + 0.05)
t = drive(BLINK_POSE)
check("...then allowed through", t["expr"], "blink")
check("...wearing a 'blink' sticker", f3.stickers[t["sticker"]]["expr"], "blink")

print("\n7. sticker variety: one face, many mood changes")
seen = set()
for i in range(40):
    time.sleep(OPEN_EXIT_DWELL / 4)
    t = drive(OPEN_POSE if i % 2 else BLINK_POSE, n=2)
    seen.add(t["sticker"])
print(f"  distinct stickers worn over 40 mood changes: {len(seen)} of 3")
check("more than the single frozen pick the old seed gave", len(seen) > 1, True)

shutil.rmtree(tmp)
print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURES: {fails}"))
sys.exit(1 if fails else 0)
