#!/usr/bin/env python3
"""
Does the new MediaPipe filter actually work on the Pi 5, and how fast?

    source ~/np/bin/activate
    python ~/np/tools/checkmp.py

Five checks. Each prints a number rather than a verdict, so if something is
wrong you can see how wrong. Stay in frame for the last two.
"""
import sys
import time
from pathlib import Path

HOME = Path.home() / "np"
if str(HOME) not in sys.path:
    sys.path.insert(0, str(HOME))
MODEL = HOME / "face_landmarker.task"

import cv2                                            # noqa: E402
import numpy as np                                    # noqa: E402

print("=" * 66)
print("  1.  what is installed")
print("=" * 66)
print("  opencv     :", cv2.__version__)
try:
    import mediapipe as mp
    from mediapipe.tasks import python as mpp
    from mediapipe.tasks.python import vision
except ImportError as e:
    sys.exit(f"  mediapipe missing: {e}")
print("  mediapipe  :", mp.__version__)
if not MODEL.exists():
    sys.exit(f"  model missing: {MODEL}  -- run  bash ~/np/setup.sh  (it downloads it)")
print("  model      :", MODEL.stat().st_size // 1024, "KB")
print("  cv2.face   :", hasattr(cv2, "face"),
      "  <- no longer needed, but tells us if the apt OpenCV got replaced")

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
if not cap.isOpened():
    sys.exit("  camera didn't open")
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
for _ in range(5):
    cap.read()
ok, frame = cap.read()
if not ok:
    sys.exit("  camera opened but returned nothing")
print("  frame      :", frame.shape[1], "x", frame.shape[0])


def make(mode, faces=4):
    return vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(
            base_options=mpp.BaseOptions(model_asset_path=str(MODEL)),
            running_mode=mode, num_faces=faces, output_face_blendshapes=True))


print()
print("=" * 66)
print("  2.  landmarks: does this model give us irises?")
print("=" * 66)
lm = make(vision.RunningMode.IMAGE)
rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
if not res.face_landmarks:
    print("  no face in this frame -- sit in front of the camera and rerun")
else:
    n = len(res.face_landmarks[0])
    print(f"  landmarks  : {n}", "(478 = irises included, the good case)"
          if n > 473 else "(468 = no irises; falling back to eye corners)")
    print(f"  blendshapes: {len(res.face_blendshapes[0])} scores returned")
lm.close()

print()
print("=" * 66)
print("  3.  speed ladder -- this decides max_side and the running mode")
print("=" * 66)
print("  the filter needs about 10 detections a second to keep up with the")
print("  camera at detect_every=2. anything at or above that is fine.")
print()
print(f"  {'mode':<7}{'max_side':>10}{'fps':>9}{'faces seen':>13}")
best = {}
for mode_name, mode in (("IMAGE", vision.RunningMode.IMAGE),
                        ("VIDEO", vision.RunningMode.VIDEO)):
    lm = make(mode)
    t0_mono = time.monotonic()
    for side in (240, 320, 480):
        n, found, t0 = 0, 0, time.monotonic()
        while time.monotonic() - t0 < 4.0:
            ok, f = cap.read()
            if not ok:
                continue
            h, w = f.shape[:2]
            sc = min(1.0, side / max(h, w))
            small = cv2.resize(f, (int(w * sc), int(h * sc))) if sc < 1 else f
            img = mp.Image(image_format=mp.ImageFormat.SRGB,
                           data=cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
            if mode_name == "VIDEO":
                r = lm.detect_for_video(img, int((time.monotonic() - t0_mono) * 1000))
            else:
                r = lm.detect(img)
            n += 1
            found += len(r.face_landmarks or [])
        fps = n / (time.monotonic() - t0)
        best[(mode_name, side)] = fps
        print(f"  {mode_name:<7}{side:>10}{fps:>9.1f}{found:>13}")
    lm.close()

print()
print("=" * 66)
print("  4.  eye separation: measured vs the old estimate")
print("=" * 66)
print("  the Haar version inferred eye separation as 0.350 x box width.")
print("  now we can measure it. these should be close on a square-on face,")
print("  and diverge when you turn your head -- which is the whole point.")
print()
lm = make(vision.RunningMode.VIDEO)
t0_mono = time.monotonic()
ratios = []
print(f"  {'measured sep':>14}{'0.350 x box':>14}{'error':>10}")
for i in range(40):
    ok, f = cap.read()
    if not ok:
        continue
    fh, fw = f.shape[:2]
    sc = min(1.0, 320 / max(fh, fw))
    small = cv2.resize(f, (int(fw * sc), int(fh * sc)))
    img = mp.Image(image_format=mp.ImageFormat.SRGB,
                   data=cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
    r = lm.detect_for_video(img, int((time.monotonic() - t0_mono) * 1000))
    if not r.face_landmarks:
        continue
    marks = r.face_landmarks[0]
    xs = np.array([m.x for m in marks]) * fw
    ys = np.array([m.y for m in marks]) * fh
    box_w = xs.max() - xs.min()
    if len(marks) > 473:
        sep = abs(xs[473] - xs[468])
    else:
        sep = abs(xs[[362, 263]].mean() - xs[[33, 133]].mean())
    ratios.append(sep / box_w)
    if i % 8 == 0:
        est = box_w * 0.350
        print(f"  {sep:>14.1f}{est:>14.1f}{(est - sep) / sep * 100:>9.1f}%")
lm.close()
if ratios:
    r = np.array(ratios)
    print(f"\n  measured eye-sep / box-width: mean {r.mean():.3f}  sd {r.std():.3f}"
          f"  (n={len(r)})")
    print(f"  the Haar constant was 0.350 -> off by {(0.350 - r.mean()) / r.mean() * 100:+.1f}%")

print()
print("=" * 66)
print("  5.  the real filter, live -- four expressions, five seconds each")
print("=" * 66)
from hamster import HamsterFilter                      # noqa: E402
ham = HamsterFilter(HOME / "stickers", MODEL, detect_every=2, max_side=320)
print(f"  {len(ham.stickers)} stickers, moods {sorted(ham.by_expr)}, "
      f"{'VIDEO' if ham.video_mode else 'IMAGE'} mode")
counts = {}
for label in ("neutral face", "SMILE", "OPEN WIDE", "EYES SHUT (hold them)"):
    for n in (3, 2, 1):
        print(f"\r  next: {label}   in {n}...", end="", flush=True)
        time.sleep(1)
    print(f"\r  >>> {label}" + " " * 28)
    seen, t0 = {}, time.monotonic()
    while time.monotonic() - t0 < 5.0:
        ok, f = cap.read()
        if not ok:
            continue
        ham.apply(f)
        for t in ham.tracks:
            seen[t["expr"]] = seen.get(t["expr"], 0) + 1
    counts[label] = seen
    total = sum(seen.values()) or 1
    print("      " + "  ".join(f"{k}={v * 100 // total}%"
                               for k, v in sorted(seen.items(),
                                                  key=lambda kv: -kv[1])))
ham.close()
cap.release()

print()
print("=" * 66)
print("  copy everything above back to Claude")
print("=" * 66)
