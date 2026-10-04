#!/usr/bin/env python3
"""Hardware-free tests for the MediaPipe hamster filter.

No camera and no model file needed: these exercise the parts that are pure
logic, driven by the tester's own measured blendshape values.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root

from hamster import (classify, head_angles, SMOOTH, BLINK_SMOOTH,
                     TURN_ON, TURN_OFF, DOWN_ON, DOWN_OFF,
                     OPEN_ON, OPEN_OFF, SMILE_ON, SMILE_OFF,
                     BLINK_ON, BLINK_OFF)

# The tester's poses as recal.py measured them, at 480 px in VIDEO mode -- the
# configuration the filter actually runs. Means per pose.
PHASE = {
    "NEUTRAL": {"jaw": 0.001, "smile": 0.001, "blink": 0.324},
    "SMILE":   {"jaw": 0.000, "smile": 0.394, "blink": 0.304},
    "MOUTH":   {"jaw": 0.513, "smile": 0.015, "blink": 0.242},
    "EYES":    {"jaw": 0.025, "smile": 0.000, "blink": 0.689},
}
# The p10 of each target pose: the WEAK end of a real pose, which is what a
# threshold actually has to catch. Passing on the mean proves very little.
WEAK = {
    "SMILE":   {"jaw": 0.000, "smile": 0.32, "blink": 0.304},
    "MOUTH":   {"jaw": 0.51,  "smile": 0.015, "blink": 0.242},
    "EYES":    {"jaw": 0.025, "smile": 0.000, "blink": 0.70},
}
# The FIRST calibration, at full resolution in IMAGE mode, where an open mouth
# scored 0.70 on smile -- partly the tester grinning through the pose, partly the
# low-resolution smile inflation measured at 320 px. Kept as a regression case: the
# jaw-first ordering must survive a badly contaminated smile reading.
CONTAMINATED_OPEN = {"jaw": 0.326, "smile": 0.704, "blink": 0.311}
WANT = {"NEUTRAL": "neutral", "SMILE": "happy", "MOUTH": "open", "EYES": "blink"}

fails = []

def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}: {got}" + ("" if ok else f"  (want {want})"))
    if not ok:
        fails.append(name)

def settle(phase, start="neutral", n=30):
    """Run the real smoothing to steady state, from each plausible prior."""
    raw, s, state = PHASE[phase], None, start
    for _ in range(n):
        if s is None:
            s = dict(raw)
        else:
            s["jaw"] = s["jaw"] * SMOOTH + raw["jaw"] * (1 - SMOOTH)
            s["smile"] = s["smile"] * SMOOTH + raw["smile"] * (1 - SMOOTH)
            s["blink"] = s["blink"] * BLINK_SMOOTH + raw["blink"] * (1 - BLINK_SMOOTH)
        state = classify(state, s)
    return state

print("1. each calibration phase settles on the right state, from any prior")
for phase, want in WANT.items():
    for prior in ("neutral", "happy", "open", "blink"):
        check(f"{phase} from {prior}", settle(phase, prior), want)

print("\n2. the WEAK end of each pose still classifies correctly")
for phase, want in (("SMILE", "happy"), ("MOUTH", "open"), ("EYES", "blink")):
    check(f"{phase} at p10", classify("neutral", WEAK[phase]), want)

print("\n3. regression: a contaminated smile reading must not beat the jaw")
c = CONTAMINATED_OPEN
print(f"  smile reads {c['smile']:.3f} (higher than a real smile) with jaw {c['jaw']:.3f}")
check("still classified open", classify("neutral", c), "open")
check("...and would have been 'happy' without the jaw test",
      classify("neutral", {**c, "jaw": 0.0}), "happy")

print("\n4. hysteresis: a value between OFF and ON holds whatever it was")
mid_jaw = {"jaw": (OPEN_ON + OPEN_OFF) / 2, "smile": 0.0, "blink": 0.3}
check("was open -> stays open", classify("open", mid_jaw), "open")
check("was neutral -> stays neutral", classify("neutral", mid_jaw), "neutral")
mid_blink = {"jaw": 0.0, "smile": 0.0, "blink": (BLINK_ON + BLINK_OFF) / 2}
check("was blink -> stays blink", classify("blink", mid_blink), "blink")
check("was neutral -> stays neutral", classify("neutral", mid_blink), "neutral")

print("\n5. a natural blink is ignored; a held one latches")
def blink_run(n_samples):
    """n_samples of eyes-shut, then back to neutral. Returns whether it latched."""
    s = dict(PHASE["NEUTRAL"])
    state = "neutral"
    latched = False
    seq = [PHASE["EYES"]] * n_samples + [PHASE["NEUTRAL"]] * 10
    for raw in seq:
        s["jaw"] = s["jaw"] * SMOOTH + raw["jaw"] * (1 - SMOOTH)
        s["smile"] = s["smile"] * SMOOTH + raw["smile"] * (1 - SMOOTH)
        s["blink"] = s["blink"] * BLINK_SMOOTH + raw["blink"] * (1 - BLINK_SMOOTH)
        state = classify(state, s)
        if state == "blink":
            latched = True
    return latched

for n in range(1, 7):
    print(f"  {n} sample(s) shut -> latched: {blink_run(n)}")
check("1 sample (a real blink) does NOT latch", blink_run(1), False)
check("2 samples do NOT latch", blink_run(2), False)
check("4 samples (~0.6 s held) DO latch", blink_run(4), True)

print("\n6. happy is refused while the mouth has just been open")
laugh = {"jaw": 0.02, "smile": 0.80, "blink": 0.30}     # grinning, jaw shut
check("mouth open 0.1s ago -> still not happy",
      classify("open", laugh, since_open=0.1), "neutral")
check("mouth open 0.5s ago -> still not happy",
      classify("open", laugh, since_open=0.5), "neutral")
check("mouth open 1.2s ago -> happy",
      classify("neutral", laugh, since_open=1.2), "happy")
check("a plain smile with no recent open -> happy",
      classify("neutral", PHASE["SMILE"], since_open=99.0), "happy")
check("the refractory never blocks 'open' itself",
      classify("neutral", PHASE["MOUTH"], since_open=0.0), "open")
check("...nor 'blink'",
      classify("neutral", PHASE["EYES"], since_open=0.0), "blink")

print("\n7. head pose: measured on the tester, as deviations from THEIR resting pose")
# headcheck.py: rest yaw +2.6 pitch -6.6; left +46.0; right -49.1;
# down pitch +16.0; up pitch -30.5.
REST = {"jaw": 0.001, "smile": 0.001, "blink": 0.324}
for label, yaw, pitch, want in (
        ("straight ahead",   2.6 - 2.6,  -6.6 + 6.6,  "neutral"),
        ("turned left",     46.0 - 2.6,  -5.6 + 6.6,  "turn"),
        ("turned right",   -49.1 - 2.6,  -7.5 + 6.6,  "turn"),
        ("looking down",    -4.8 - 2.6,  16.0 + 6.6,  "down"),
        ("looking up",      -1.9 - 2.6, -30.5 + 6.6,  "neutral")):
    check(label, classify("neutral", REST, 99.0, yaw, pitch), want)

check("a real expression beats head pose",
      classify("neutral", PHASE["MOUTH"], 99.0, 43.4, 22.6), "open")
check("down beats turn when both apply",
      classify("neutral", REST, 99.0, 43.4, 22.6), "down")
print(f"  thresholds: turn {TURN_ON}/{TURN_OFF}deg, down {DOWN_ON}/{DOWN_OFF}deg")
# The useful property is not "under half" but "in the gap, and clear of a
# glance". The tester looks at the PANEL, so panel-to-lens glances (10-20 deg)
# must stay below it while a real turn (43-52 deg) stays above.
check("turn threshold above a panel-to-lens glance", TURN_ON > 20, True)
check("turn threshold below a real turn", TURN_ON < 43.4 * 0.7, True)
check("turn hysteresis leaves a real gap", TURN_ON - TURN_OFF >= 5, True)
check("down threshold sits under the measured tilt", DOWN_ON < 22.6, True)
check("...and above an upward tilt reading as down", DOWN_ON > 0, True)

print("\n8. the pitch sign hammyhamster's README flagged as unverified")
import numpy as np
down_m = [[1, 0, 0, 0], [0, 1, -0.28, 0], [0, 0.28, 1, 0], [0, 0, 0, 1]]
yaw_m = [[1, 0, 0.72, 0], [0, 1, 0, 0], [-0.72, 0, 1, 0], [0, 0, 0, 1]]
y, pi = head_angles(down_m)
check("a downward-tilt matrix gives positive pitch", pi > 0, True)
y2, _ = head_angles(yaw_m)
check("a turn matrix gives large yaw", abs(y2) > 40, True)

print("\n9. thresholds sit between the measured phases, not on top of them")
check("OPEN_ON above every closed-mouth phase",
      OPEN_ON > max(PHASE[p]["jaw"] for p in ("NEUTRAL", "SMILE", "EYES")), True)
check("OPEN_ON below the open-mouth phase", OPEN_ON < PHASE["MOUTH"]["jaw"], True)
check("SMILE_ON above neutral", SMILE_ON > PHASE["NEUTRAL"]["smile"], True)
check("SMILE_ON below the real smile", SMILE_ON < PHASE["SMILE"]["smile"], True)
check("BLINK_ON above eyes-open phases",
      BLINK_ON > max(PHASE[p]["blink"] for p in ("NEUTRAL", "SMILE", "MOUTH")), True)
check("BLINK_ON below eyes-shut", BLINK_ON < PHASE["EYES"]["blink"], True)

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURES: {fails}"))
sys.exit(1 if fails else 0)
