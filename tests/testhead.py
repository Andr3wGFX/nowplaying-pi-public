#!/usr/bin/env python3
"""Does the adaptive head-pose baseline actually work?

The thresholds are deviations from a moving baseline, not from zero, because
the resting angle between the camera and a face depends on where the person is
looking -- and in the photo booth the tester looks at the panel, not the lens.
This drives the real filter through the fake model to check three things:

  * an off-axis RESTING pose is absorbed instead of firing
  * a real turn on top of that offset still fires
  * HOLDING the turn does not let the baseline drift up and cancel it
"""
import json
import math
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "stubs_mp"))
sys.path.insert(0, str(HERE.parent))   # repo root: hamster.py

import cv2
import numpy as np
import mediapipe as mp
from hamster import HamsterFilter, MIN_DWELL

fails = []
def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}: {got}"
          + ("" if ok else f"  (want {want})"))
    if not ok:
        fails.append(name)

tmp = Path(tempfile.mkdtemp())
cv2.imwrite(str(tmp / "t.jpg"), np.full((200, 200, 3), 200, np.uint8))
(tmp / "stickers.json").write_text(json.dumps({"stickers": [
    {"file": "t.jpg", "eye_left": [60, 80], "eye_right": [140, 80], "expr": e}
    for e in ("neutral", "turn", "down")]}))


def yaw_matrix(deg):
    r = math.sin(math.radians(deg))
    return [[1, 0, r, 0], [0, 1, 0, 0], [-r, 0, 1, 0], [0, 0, 0, 1]]


marks = [(0.30, 0.20)] * 478
marks[0], marks[1] = (0.30, 0.20), (0.55, 0.62)
marks[468], marks[473] = (0.31, 0.30), (0.44, 0.30)
mp.FAKE_LANDMARKS = [marks]
mp.FAKE_BLENDSHAPES = [{"jawOpen": 0.0, "mouthSmileLeft": 0.0,
                        "mouthSmileRight": 0.0,
                        "eyeBlinkLeft": 0.31, "eyeBlinkRight": 0.30}]
f = HamsterFilter(tmp, model_path=__file__, detect_every=1, max_side=320)
frame = np.full((480, 640, 3), 90, np.uint8)

RESTING_OFFSET = 30.0        # as if the panel sits well off to one side


def drive(deg, n):
    mp.FAKE_MATRICES = [yaw_matrix(deg)]
    for _ in range(n):
        f.apply(frame)
    t = f.tracks[0]
    return t["expr"], t["yaw_dev"]

print("a face whose RESTING pose is 30 degrees off-axis")
st, dev = drive(RESTING_OFFSET, 1)
check("first sight is not a turn", st, "neutral")
st, dev = drive(RESTING_OFFSET, 200)
check("still not a turn after sitting there", st, "neutral")
check("deviation collapsed to ~0", abs(dev) < 1.0, True)

time.sleep(MIN_DWELL)
st, dev = drive(RESTING_OFFSET + 45, 30)
check("a real 45deg turn on top of it fires", st, "turn")
st, dev = drive(RESTING_OFFSET + 45, 400)
check("holding the turn does NOT let it fade", st, "turn")
check("deviation stayed large while held", dev > 40, True)

time.sleep(MIN_DWELL)
st, dev = drive(RESTING_OFFSET, 40)
check("returning to rest clears it", st, "neutral")

f.close()
shutil.rmtree(tmp)
print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURES: {fails}"))
sys.exit(1 if fails else 0)
