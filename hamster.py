#!/usr/bin/env python3
"""
Hamster face filter -- MediaPipe edition.

Finds faces, reads where the eyes actually are, and lays a hamster over each
one scaled so the hamster's eye separation matches the person's. No rotation:
the stickers stay horizontal.

The sticker keeps its own background: a rectangle around the hamster's head is
cropped from the source image and pasted whole, rather than cutting the
hamster out of it.

WHAT CHANGED FROM THE EARLIER OPENCV (HAAR + LBF) VERSION
--------------------------------------------------------
One model now does both jobs. MediaPipe's FaceLandmarker returns face
landmarks AND named expression scores ("blendshapes") in a single pass, so the
Haar cascade and the 68-point LBF model are both gone.

Two things get better as a result:

1. Eye separation is MEASURED, not estimated. The old code derived it from the
   detection box (EYE_SEP_OF_W = 0.350, itself a hard-won calibration -- the
   obvious guess of 0.45 made every sticker 29% too big). Now the eye points
   come from the model, so a turned or tilted head scales correctly instead of
   inheriting the error in its bounding box.

1a. And the old constant was measurably wrong. Measured live on the Pi 5,
   eye separation is 0.337 of the box width (sd 0.003, n=40), not 0.350 --
   so every sticker had been about 4% too big. Small, but it was guesswork
   standing in for a measurement, and now it is a measurement.

2. Blink is detectable. The LBF model could not see one: measured on the tester's
   own face, eyes CLOSED scored 0.230 against 0.210 neutral, because LBF
   places eye points from a learned prior rather than tracking eyelids.
   MediaPipe's eyeBlink scores 0.69 closed against 0.32 open on the same face.

Needs ~/np/face_landmarker.task, which setup.sh downloads.
"""
import json
import math
import os
import random
import time
from pathlib import Path

# MediaPipe's C++ layer logs a screenful of xnnpack/madvise warnings on every
# construction. They are harmless, and in a systemd journal they bury the
# messages that matter. Must be set before mediapipe is imported.
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Expression thresholds, measured on the tester's own face with recal.py, through
# the exact code path this file uses -- VIDEO mode, detection at 480 px. That
# matters: an earlier calibration at full resolution in IMAGE mode produced
# materially different numbers, so thresholds taken from the wrong
# configuration are just a different flavour of guess.
#
#   480 px, mean per pose      NEUTRAL   SMILE    OPEN   BLINK
#   jawOpen                      0.001   0.000   0.513   0.025
#   mean mouthSmileL/R           0.001   0.394   0.015   0.000
#   mean eyeBlinkL/R             0.324   0.304   0.242   0.689
#
# Every signal has a real gap to put a threshold in: +0.49 for jaw, +0.38 for
# smile, +0.37 for blink. Compare the two signals that were rejected on this
# project -- OpenCV's smile cascade (2 correct out of 7) and LBF's blink
# (eyes CLOSED scored 0.230 against 0.210 open, i.e. backwards). A threshold
# is only worth having when there is a gap to put it in.
#
# The ON values sit deliberately LOW in each gap rather than at the midpoint.
# Calibration poses are exaggerated; real ones are not. SMILE_ON of 0.18 is
# about half the measured grin (p10 0.32), so a gentle smile still registers,
# while still sitting 12x above the highest non-smiling reading (0.015).
#
# Hysteresis: a clear signal to switch on, a clear one to drop back, so a face
# sitting near a boundary doesn't flap between hamsters.
OPEN_ON,  OPEN_OFF  = 0.15, 0.08
SMILE_ON, SMILE_OFF = 0.18, 0.09
BLINK_ON, BLINK_OFF = 0.60, 0.50

# jawOpen is tested FIRST and also gates the smile test. This is cheap
# insurance, not a fix for a measured problem: at 480 px with a blank open
# mouth, smile reads 0.015. But at 320 px the same pose read 0.72 (measured
# with the size held constant otherwise), so if the frame is ever small, blurred or badly cropped,
# a wide-open mouth can still masquerade as a grin. Ordering it this way costs
# one comparison and removes the failure mode entirely.
#
# Smoothing is an exponential moving average: new = old*k + measured*(1-k).
# Blink gets its own, heavier constant on purpose. A natural blink lasts
# 100-150 ms, which at this sampling rate is a single reading; at k=0.60 one
# reading cannot cross BLINK_ON, and it takes roughly half a second of eyes
# genuinely shut to latch. Without that, the hamster would change every time
# the tester blinked.
SMOOTH = 0.45
BLINK_SMOOTH = 0.60

# Two separate protections against the filter thrashing, because there were
# two separate problems and one knob could not fix both.
#
# HAPPY_REFRACTORY: smiling with your mouth open is one thing people do, and it
# makes two states take turns winning -- jaw dips under OPEN_OFF, `happy` grabs
# the state, jaw rises, `open` takes it back. Hysteresis cannot help: it guards
# a single signal crossing a single threshold. So `happy` is simply refused for
# a second after the mouth was last open, on the grounds that you were laughing
# rather than smiling.
#
# MIN_DWELL: a floor on how fast any face may change hamster at all, for the
# ordinary flicker that survives everything else.
#
# Both measured against a real 30-second session of the tester opening and closing
# their mouth, scored on four things: visible flicker (state visits under 0.4 s),
# open-to-happy churn, hit rate (does `open` show when jaw > 0.25) and false
# rate (does it claim `open` when jaw < 0.05):
#
#                              flicker  churn   hit   false  smiles missed
#   nothing                          7      4  100%      0%        12%
#   MIN_DWELL 1.0s alone             0      2   68%     24%         -
#   refractory 1.0s + dwell 0.4s     1      0   93%      2%        50%
#   refractory 0.7s + dwell 0.4s     1      0   90%      2%        38%  <- shipped
#
# Two lessons are baked into that table. First, the dwell-only version looked
# fine on "state changes per minute" and was quietly wrong: it bought stability
# by holding `open` through a quarter of the frames where the mouth was shut.
# Counting changes was the wrong metric.
#
# Second, the refractory has a real cost that only showed up once it was
# measured on a live run -- it suppresses genuine smiles that happen to follow
# an open mouth, which is most of them, because people laugh. 0.7 s is the
# shortest value that still kills the churn entirely. There is no setting with
# zero churn AND zero missed smiles; this is a trade, not a bug to be fixed.
HAPPY_REFRACTORY = 0.7
MIN_DWELL = 0.4

# A flat dwell turned out to punish the one signal that deserves it least.
# jawOpen has by far the cleanest separation of anything measured here (0.001
# resting against 0.513 open), so a strong jaw reading is the most trustworthy
# number the filter has -- and making it queue behind a timer is what the tester
# saw as "the mouth switch is having difficulties". Measured across both live
# sessions, samples with jaw > 0.30 that were NOT showing the open hamster:
#
#   flat 0.4 s dwell                    5 and 4 late,  hit 88% / 90%
#   confident opens waived entirely     0 and 0 late,  hit 96% / 100%, but the
#                                       brief neutral between two opens flashes
#   + slower EXIT from open (0.6 s)     0 and 0 late,  hit 96% / 100%, 1 fewer
#                                       flash, false 0% / 2%
#
# So: entering `open` on a confident reading is nearly immediate, and LEAVING
# open is slower than anything else, which stops a momentary mouth-close
# mid-laugh flashing the neutral hamster.
OPEN_CONFIDENT = 0.30       # a jaw reading this high needs no corroboration
CONFIDENT_DWELL = 0.15      # ...so it waits barely at all
OPEN_EXIT_DWELL = 0.6       # ...but leaving open is deliberate

# ---------------------------------------------------------------------------
# Head turn and head tilt, from catherpiee/hammyhamster. MediaPipe returns a
# 4x4 facial transformation matrix from the SAME pass that gives blendshapes,
# so two more expressions cost one option flag and no extra model.
#
# Measured on the tester (headcheck.py), degrees:
#
#   pose              yaw    pitch
#   straight ahead    2.6     -6.6     <- note: NEITHER rests at zero
#   turn left        46.0     -5.6
#   turn right      -49.1     -7.5
#   look down        -4.8     16.0
#   look up          -1.9    -30.5
#
# hammyhamster's README warns the pitch sign was never checked against a live camera.
# Checked here: down is positive. Correct as written.
#
# THRESHOLDS ARE RELATIVE TO A MOVING BASELINE, not to zero. Those resting
# offsets are the angle between the camera and wherever the face is looking,
# and in the photo booth the tester looks at the PANEL, not the lens -- a different
# offset again, unknown in advance. A fixed threshold calibrated at the lens
# could sit permanently triggered at the panel. So the baseline tracks the
# resting pose slowly and FREEZES while a pose is held, which stops it drifting
# to follow a turn that is meant to be detected.
HEAD_POSE = True
TURN_ON, TURN_OFF = 25.0, 16.0     # degrees of yaw away from baseline.
                                   # Deliberately over half the measured
                                   # turn (43-52 deg): glancing between the
                                   # panel and the lens is a 10-20 deg
                                   # movement and must not count as a turn.
DOWN_ON, DOWN_OFF = 12.0, 7.0      # degrees of downward pitch away from baseline
BASE_SMOOTH = 0.98                 # ~8 s to follow a new resting pose


def head_angles(matrix):
    """Yaw and pitch in degrees. R[0][2] is rotation about the vertical axis
    (turning), R[1][2] about the horizontal (nodding); down is positive."""
    yaw = math.degrees(math.asin(max(-1.0, min(1.0, matrix[0][2]))))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, -matrix[1][2]))))
    return yaw, pitch

# Landmark indices into MediaPipe's face mesh. The refined model returns 478
# points, the last ten being the irises -- the best eye centres available.
# Without refinement we fall back to averaging each eye's inner and outer
# corner. Which one is "left" does not matter here: the code sorts by x and
# only ever uses the separation and the midpoint.
# How many of its own recent hamsters a face won't immediately wear again.
# 3 against an 8-sticker neutral pool leaves plenty of choice; against the
# 3-sticker open pool the memory is relaxed rather than leaving nothing.
RECENT = 3

IRIS_A, IRIS_B = 468, 473
EYE_A_CORNERS = (33, 133)
EYE_B_CORNERS = (362, 263)

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/1/face_landmarker.task")


def classify(prev, s, since_open=99.0, yaw_dev=0.0, pitch_dev=0.0):
    """Pure function: previous state + smoothed scores -> new state.

    Split out so it can be tested without a camera, a model, or a face.
    `s` holds smoothed 'jaw', 'smile' and 'blink'; `since_open` is how many
    seconds ago the jaw was last above its threshold.
    """
    if s["jaw"] > (OPEN_OFF if prev == "open" else OPEN_ON):
        return "open"
    if s["blink"] > (BLINK_OFF if prev == "blink" else BLINK_ON):
        return "blink"
    # Smile needs a closed mouth (see THE TRAP) and a mouth that has been
    # closed for a moment (see HAPPY_REFRACTORY).
    if (s["jaw"] < OPEN_ON and since_open >= HAPPY_REFRACTORY
            and s["smile"] > (SMILE_OFF if prev == "happy" else SMILE_ON)):
        return "happy"
    # Head pose last, as in hammyhamster's code: a specific face beats a general posture.
    # Tilt is checked before turn so a head that is both down and slightly
    # turned reads as down.
    if HEAD_POSE:
        if pitch_dev > (DOWN_OFF if prev == "down" else DOWN_ON):
            return "down"
        if abs(yaw_dev) > (TURN_OFF if prev == "turn" else TURN_ON):
            return "turn"
    return "neutral"


class HamsterFilter:
    def __init__(self, sticker_dir, model_path, cover_w=3.0, cover_h=3.3,
                 detect_every=2, ease=0.5, max_side=480, max_faces=4,
                 max_miss=2, confirm=2, match_radius=1.1, merge_dist=0.7,
                 video_mode=True):
        """cover_w/h: how much of the sticker to take, in multiples of its own
        eye separation.

        detect_every : run the detector every Nth frame
        ease         : how fast the overlay glides to the detected position,
                       applied EVERY frame so motion stays smooth between
                       detections rather than jumping on detection frames
        max_miss     : drop a face after this many missed DETECTIONS (not
                       frames). Too high and departed faces hang around.
        confirm      : a face must be seen this many times before it gets a
                       hamster, which throws away single-frame false positives
        match_radius : how far a face may move between detections and still be
                       recognised as the same one. Too small and a fast head
                       turn spawns a second hamster beside the first.
        video_mode   : MediaPipe's VIDEO running mode reuses the previous
                       frame's region of interest and should be faster than
                       IMAGE mode, which re-searches the whole frame. Falls
                       back to IMAGE automatically if it refuses.
        """
        self.dir = Path(sticker_dir)
        self.cover_w, self.cover_h = cover_w, cover_h
        self.detect_every, self.ease = detect_every, ease
        # max_side: detect on a downscaled copy. 480, not 320 -- measured on
        # the Pi 5, VIDEO mode runs at 20.7 / 20.0 / 19.9 fps at 240 / 320 /
        # 480, i.e. flat, because it is pegged at the camera's frame rate and
        # not the model's. The downscale was buying nothing and costing face
        # pixels: 480 also found MORE faces (85 vs 80 over the same window).
        self.max_side = max_side
        self.max_miss, self.confirm = max_miss, confirm
        self.match_radius, self.merge_dist = match_radius, merge_dist
        self.frame_no = 0
        self.tracks = []
        self.n_landmarks = None           # 478 with irises, 468 without

        self._load_stickers()
        self._load_model(model_path, max_faces, video_mode)

    # --------------------------------------------------------------- setup
    def _load_stickers(self):
        man = json.loads((self.dir / "stickers.json").read_text())
        self.stickers = []
        for s in man["stickers"]:
            img = cv2.imread(str(self.dir / s["file"]), cv2.IMREAD_COLOR)
            if img is None:
                continue
            lx, ly = s["eye_left"]
            rx, ry = s["eye_right"]
            self.stickers.append({
                "img": img, "name": s["file"],
                "expr": s.get("expr", "neutral"),
                "mid": ((lx + rx) / 2.0, (ly + ry) / 2.0),
                "sep": max(abs(rx - lx), 1.0),
            })
        if not self.stickers:
            raise RuntimeError(f"no sticker images found in {self.dir}")
        self.by_expr = {}
        for i, st in enumerate(self.stickers):
            self.by_expr.setdefault(st["expr"], []).append(i)

    def _load_model(self, model_path, max_faces, video_mode):
        model = Path(model_path)
        if not model.is_file():
            raise RuntimeError(
                f"{model} is missing. With the venv active:\n"
                f"    wget -O {model} {MODEL_URL}")
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mpp
            from mediapipe.tasks.python import vision
        except ImportError as e:
            raise RuntimeError(f"mediapipe not importable: {e}")
        self.mp, self.vision, self.mpp = mp, vision, mpp
        self._model_path, self._max_faces = str(model), max_faces
        self.video_mode = video_mode
        self.landmarker = None
        self._build(video_mode)
        self._t0 = time.monotonic()

    def _build(self, video_mode):
        """A running mode is baked in at construction, so switching from VIDEO
        to IMAGE means building a new landmarker, not flipping a flag."""
        if self.landmarker is not None:
            try:
                self.landmarker.close()
            except Exception:
                pass
        mode = (self.vision.RunningMode.VIDEO if video_mode
                else self.vision.RunningMode.IMAGE)
        self.landmarker = self.vision.FaceLandmarker.create_from_options(
            self.vision.FaceLandmarkerOptions(
                base_options=self.mpp.BaseOptions(
                    model_asset_path=self._model_path),
                running_mode=mode, num_faces=self._max_faces,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=HEAD_POSE))
        self.video_mode = video_mode

    def close(self):
        """MediaPipe's own destructor raises TypeError if it runs during
        interpreter shutdown, because the module globals it needs are already
        None. Harmless but alarming in the log, so close it explicitly."""
        lm = getattr(self, "landmarker", None)
        if lm is not None:
            try:
                lm.close()
            except Exception:
                pass
            self.landmarker = None

    # ---------------------------------------------------------------- faces
    def _detect(self, bgr):
        """-> list of (box, eye_mid, eye_sep, scores) in FULL-frame pixels.

        MediaPipe returns landmarks normalised to 0..1, so the downscale used
        for speed never has to be undone -- the coordinates are already
        resolution-independent.
        """
        fh, fw = bgr.shape[:2]
        scale = min(1.0, self.max_side / max(fh, fw))
        small = (cv2.resize(bgr, (int(fw * scale), int(fh * scale)))
                 if scale < 1 else bgr)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)

        if self.video_mode:
            ts = int((time.monotonic() - self._t0) * 1000)
            try:
                res = self.landmarker.detect_for_video(image, ts)
            except Exception as e:
                print(f"hamster: VIDEO mode refused ({e}); using IMAGE mode")
                self._build(False)
                res = self.landmarker.detect(image)
        else:
            res = self.landmarker.detect(image)

        out = []
        blends = res.face_blendshapes or []
        mats = (res.facial_transformation_matrixes or []) if HEAD_POSE else []
        for i, marks in enumerate(res.face_landmarks or []):
            self.n_landmarks = len(marks)
            xs = np.fromiter((m.x for m in marks), float, len(marks)) * fw
            ys = np.fromiter((m.y for m in marks), float, len(marks)) * fh
            box = (xs.min(), ys.min(), xs.max() - xs.min(), ys.max() - ys.min())

            if len(marks) > IRIS_B:
                ax, ay = xs[IRIS_A], ys[IRIS_A]
                bx, by = xs[IRIS_B], ys[IRIS_B]
            else:
                ax = xs[list(EYE_A_CORNERS)].mean()
                ay = ys[list(EYE_A_CORNERS)].mean()
                bx = xs[list(EYE_B_CORNERS)].mean()
                by = ys[list(EYE_B_CORNERS)].mean()
            sep = max(abs(bx - ax), 1.0)
            mid = ((ax + bx) / 2.0, (ay + by) / 2.0)

            angles = None
            if HEAD_POSE and i < len(mats):
                angles = head_angles(mats[i])

            scores = {}
            if i < len(blends):
                c = {b.category_name: b.score for b in blends[i]}
                scores = {
                    "jaw": c.get("jawOpen", 0.0),
                    "smile": (c.get("mouthSmileLeft", 0.0)
                              + c.get("mouthSmileRight", 0.0)) / 2.0,
                    "blink": (c.get("eyeBlinkLeft", 0.0)
                              + c.get("eyeBlinkRight", 0.0)) / 2.0,
                }
            out.append((box, mid, sep, scores, angles))
        return out

    def _track(self, found):
        """Match detections to existing faces one-to-one, so a face that moved
        updates its own track instead of spawning a second one."""
        unmatched = list(self.tracks)
        for (box, mid, sep, scores, angles) in found:
            x, y, bw, bh = box
            cx, cy = x + bw / 2, y + bh / 2
            best, best_d = None, 1e9
            for t in unmatched:
                d = ((t["tcx"] - cx) ** 2 + (t["tcy"] - cy) ** 2) ** 0.5
                if d < best_d and d < max(bw, t["tw"]) * self.match_radius:
                    best, best_d = t, d
            if best is None:
                t = {"cx": cx, "cy": cy, "w": bw, "h": bh,       # drawn
                     "ex": mid[0], "ey": mid[1], "sep": sep,
                     "tcx": cx, "tcy": cy, "tw": bw, "th": bh,   # detected
                     "tex": mid[0], "tey": mid[1], "tsep": sep,
                     "sticker": 0, "recent": [],
                     "expr": "neutral", "s": None, "changed_at": 0.0,
                     "open_at": -99.0, "yaw0": None, "pitch0": None,
                     "yaw_dev": 0.0, "pitch_dev": 0.0,
                     "miss": 0, "seen": 1}
                self.tracks.append(t)
                self._assign(t, "neutral")
            else:
                unmatched.remove(best)      # one detection claims one track
                t = best
                t["tcx"], t["tcy"] = cx, cy
                t["tw"], t["th"] = bw, bh
                t["tex"], t["tey"], t["tsep"] = mid[0], mid[1], sep
                t["miss"] = 0
                t["seen"] += 1
            if scores:
                self._update_expression(t, scores, angles)

        for t in unmatched:
            t["miss"] += 1
        self.tracks = [t for t in self.tracks if t["miss"] <= self.max_miss]
        self._merge()

    def _merge(self):
        """Two tracks on one face can still happen when the detector wobbles.
        Keep the better-established one."""
        keep = []
        for t in sorted(self.tracks, key=lambda t: (-t["seen"], t["miss"])):
            dup = False
            for k in keep:
                d = ((k["tcx"] - t["tcx"]) ** 2 + (k["tcy"] - t["tcy"]) ** 2) ** 0.5
                if d < max(k["tw"], t["tw"]) * self.merge_dist:
                    dup = True
                    break
            if not dup:
                keep.append(t)
        self.tracks = keep

    def _assign(self, track, expr):
        """Give this face a hamster for this mood.

        Prefers one from the right mood that nobody else is wearing and that
        this face has not worn in its last RECENT moods. An unlabelled mood
        falls back to the neutral pool rather than the whole pile, so an
        un-tagged 'blink' doesn't pull a grinning hamster.

        This used to derive the choice from one random seed per face, fixed
        for the life of the track: free[int(seed * 9973) % len(free)]. That
        made the pick stable, which was the intent -- but it also made it
        DETERMINISTIC. With one seed, "open" always resolved to the same index
        in a 3-sticker pool and "happy" to the same index in a 4-sticker pool,
        so a whole session only ever showed about four distinct hamsters, and
        the set only changed when the filter was toggled off and on. The tester saw
        roughly seven of fifteen in normal use. Drawing fresh each time, minus
        a short memory, covers the whole set instead.
        """
        pool = (self.by_expr.get(expr) or self.by_expr.get("neutral")
                or list(range(len(self.stickers))))
        taken = {t["sticker"] for t in self.tracks if t is not track}
        recent = track.get("recent", ())
        free = [i for i in pool if i not in taken and i not in recent]
        if not free:                         # small pool: relax the memory
            free = [i for i in pool if i not in taken] or pool
        pick = random.choice(free)
        track["sticker"] = pick
        track.setdefault("recent", [])
        track["recent"] = ([pick] + track["recent"])[:RECENT]
        return pick

    # ----------------------------------------------------------- expression
    @staticmethod
    def _dwell_for(track, want):
        """How long this particular change has to wait. Not one number: see
        OPEN_CONFIDENT above."""
        if want == "open" and track["s"]["jaw"] > OPEN_CONFIDENT:
            return CONFIDENT_DWELL
        if track["expr"] == "open":
            return max(MIN_DWELL, OPEN_EXIT_DWELL)
        return MIN_DWELL

    def _update_expression(self, t, raw, angles=None):
        if angles is not None:
            yaw, pitch = angles
            if t["yaw0"] is None:
                t["yaw0"], t["pitch0"] = yaw, pitch
            t["yaw_dev"] = yaw - t["yaw0"]
            t["pitch_dev"] = pitch - t["pitch0"]
            # Freeze the baseline while a pose is held, or it drifts to follow
            # the very turn it is supposed to be measuring.
            if t["expr"] not in ("turn", "down"):
                k = BASE_SMOOTH
                t["yaw0"] = t["yaw0"] * k + yaw * (1 - k)
                t["pitch0"] = t["pitch0"] * k + pitch * (1 - k)
        if t["s"] is None:
            t["s"] = dict(raw)
        else:
            s = t["s"]
            s["jaw"] = s["jaw"] * SMOOTH + raw["jaw"] * (1 - SMOOTH)
            s["smile"] = s["smile"] * SMOOTH + raw["smile"] * (1 - SMOOTH)
            s["blink"] = (s["blink"] * BLINK_SMOOTH
                          + raw["blink"] * (1 - BLINK_SMOOTH))
        when = time.monotonic()
        if t["s"]["jaw"] > OPEN_ON:
            t["open_at"] = when
        now = classify(t["expr"], t["s"], when - t["open_at"],
                       t["yaw_dev"], t["pitch_dev"])
        if now == t["expr"]:
            return
        if when - t["changed_at"] < self._dwell_for(t, now):
            return                    # too soon -- let the current one stand
        t["expr"] = now
        t["changed_at"] = when
        self._assign(t, now)

    # --------------------------------------------------------------- paste
    def _paste(self, frame, track):
        st = self.stickers[track["sticker"] % len(self.stickers)]
        fh, fw = frame.shape[:2]

        # where the person's eyes are -- measured, not inferred from the box
        want_sep = track["sep"]
        eye_x, eye_y = track["ex"], track["ey"]

        # crop a window around the hamster's eyes, in its own eye-sep units
        k = want_sep / st["sep"]                     # source px -> frame px
        mx, my = st["mid"]
        half_w = st["sep"] * self.cover_w / 2
        half_h = st["sep"] * self.cover_h / 2
        sx0, sx1 = mx - half_w, mx + half_w
        sy0, sy1 = my - half_h, my + half_h

        # target rectangle in the frame
        tx0 = eye_x - (mx - sx0) * k
        ty0 = eye_y - (my - sy0) * k
        tw = int(round((sx1 - sx0) * k))
        th = int(round((sy1 - sy0) * k))
        if tw < 8 or th < 8:
            return

        # take the crop, padding with edge pixels if it runs off the sticker
        sh, sw = st["img"].shape[:2]
        ix0, iy0 = int(np.floor(sx0)), int(np.floor(sy0))
        ix1, iy1 = int(np.ceil(sx1)), int(np.ceil(sy1))
        pad_l, pad_t = max(0, -ix0), max(0, -iy0)
        pad_r, pad_b = max(0, ix1 - sw), max(0, iy1 - sh)
        crop = st["img"][max(0, iy0):min(sh, iy1), max(0, ix0):min(sw, ix1)]
        if crop.size == 0:
            return
        if pad_l or pad_t or pad_r or pad_b:
            crop = cv2.copyMakeBorder(crop, pad_t, pad_b, pad_l, pad_r,
                                      cv2.BORDER_REPLICATE)
        patch = cv2.resize(crop, (tw, th), interpolation=cv2.INTER_AREA
                           if k < 1 else cv2.INTER_LINEAR)

        # clip to the frame and copy
        px0, py0 = int(round(tx0)), int(round(ty0))
        cx0, cy0 = max(0, px0), max(0, py0)
        cx1, cy1 = min(fw, px0 + tw), min(fh, py0 + th)
        if cx1 <= cx0 or cy1 <= cy0:
            return
        frame[cy0:cy1, cx0:cx1] = patch[cy0 - py0:cy1 - py0, cx0 - px0:cx1 - px0]

    # ----------------------------------------------------------------- main
    def apply(self, frame):
        """BGR in, BGR out (modified in place). Detection runs every Nth
        frame; the tracks carry the overlay in between."""
        if self.frame_no % self.detect_every == 0:
            self._track(self._detect(frame))
        self.frame_no += 1

        # glide toward the detected position every frame, not just on the
        # frames the detector ran -- this is what makes it feel responsive
        e = self.ease
        for t in self.tracks:
            for now, want in (("cx", "tcx"), ("cy", "tcy"),
                              ("w", "tw"), ("h", "th"),
                              ("ex", "tex"), ("ey", "tey"), ("sep", "tsep")):
                t[now] += (t[want] - t[now]) * e

        # nearer faces (bigger boxes) paste last, so they sit in front
        for t in sorted(self.tracks, key=lambda t: t["w"]):
            if t["seen"] >= self.confirm:      # ignore one-frame phantoms
                self._paste(frame, t)
        return frame

    def reshuffle(self):
        """New hamsters for everyone, forgetting what they just wore."""
        for t in self.tracks:
            t["recent"] = []
            self._assign(t, t["expr"])
