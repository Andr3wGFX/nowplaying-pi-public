#!/usr/bin/env python3
"""Tests for the timelapse encoder -- real frames, real ffmpeg, real files.

The thing that actually matters is that the finished video plays and fits under
Google Drive's 5 MB multipart limit, so both are measured rather than assumed.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
import cv2
import numpy as np
from timelapse import Timelapse

fails = []
def check(name, got, want=True):
    ok = (got == want)
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}: {got}"
          + ("" if ok else f"  (want {want})"))
    if not ok:
        fails.append(name)

def synth(i, w=1024, h=768):
    """A frame that changes every time, so a stuck encoder is visible."""
    im = np.zeros((h, w, 3), np.uint8)
    im[:] = (30 + (i * 3) % 200, 60, 200 - (i * 3) % 180)
    cv2.circle(im, (int(w / 2 + 300 * np.cos(i / 12)),
                    int(h / 2 + 200 * np.sin(i / 12))), 60, (255, 255, 255), -1)
    cv2.putText(im, f"{i:04d}", (40, 120), cv2.FONT_HERSHEY_SIMPLEX, 3,
                (255, 255, 255), 6)
    return im

root = Path(tempfile.mkdtemp())
print("1. a full-length session: 30 minutes at one frame every 4 s")
FPS, INTERVAL = 30, 4.0
tl = Timelapse(root, "2026-09-15_0200", INTERVAL, FPS)
N = int(1800 / INTERVAL)                      # 450
for i in range(N):
    tl.add(synth(i), cv2)
check("frames captured", tl.count, N)
check("video length is about 15 s", round(tl.out_seconds), 15)
bps, scale, pred = tl.plan()
print(f"  plan: {bps/1000:.0f} kbps, scale {scale or 'full'}, predicted {pred/1e6:.2f} MB")

out = tl.encode()
size = out.stat().st_size
print(f"  encoded {out.name}: {size / 1e6:.2f} MB")
check("under Drive's 5 MB multipart limit", size < 5_000_000)
check("not suspiciously tiny", size > 100_000)

probe = subprocess.run(
    ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
     "stream=nb_frames,width,height,codec_name", "-show_entries",
     "format=duration", "-of", "default=nw=1", str(out)],
    capture_output=True, text=True)
info = dict(l.split("=") for l in probe.stdout.strip().splitlines() if "=" in l)
print("  ffprobe:", info)
check("codec is h264", info.get("codec_name"), "h264")
check("all frames made it", int(info.get("nb_frames", 0)), N)
check("duration is ~15 s", abs(float(info.get("duration", 0)) - 15.0) < 0.5)
check("full resolution kept", (info.get("width"), info.get("height")),
      ("1024", "768"))

print("\n2. a session stopped early still produces a valid clip")
tl2 = Timelapse(root, "short", INTERVAL, FPS)
for i in range(40):
    tl2.add(synth(i), cv2)
out2 = tl2.encode()
check("short clip exists", out2.exists())
check("short clip is smaller", out2.stat().st_size < size)
print(f"  {tl2.count} frames -> {tl2.out_seconds:.2f} s, "
      f"{out2.stat().st_size / 1e6:.2f} MB at "
      f"{tl2.plan()[0] / 1000:.0f} kbps")
check("short clip also under the cap", out2.stat().st_size < 5_000_000)

print("\n3. bitrate scales so even a LONG capture stays uploadable")
tl3 = Timelapse(root, "long", INTERVAL, FPS)
for label, frames in (("15 s (the shipped setting)", 450),
                      ("60 s", 1800), ("120 s", 3600), ("160 s", 4800)):
    tl3.count = frames
    bps, scale, pred = tl3.plan()
    print(f"  {label:<26} {bps/1000:>5.0f} kbps  scale "
          f"{str(scale or 'full'):<5}  {pred/1e6:>5.2f} MB  "
          f"{'fits' if tl3.fits_upload() else 'TOO BIG'}")
tl3.count = 3600
check("two minutes of video still fits", tl3.fits_upload())

print("\n4. refuses to make a video out of nothing")
tl4 = Timelapse(root, "empty", INTERVAL, FPS)
try:
    tl4.encode()
    check("empty session raises", False)
except RuntimeError as e:
    check("empty session raises", "frame" in str(e).lower())

print("\n5. cleanup keeps the manifest and drops the frames")
tl2.cleanup()
check("frame folder removed", not tl2.dir.exists())
check("manifest written", (root / "short.json").exists())

shutil.rmtree(root)
print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURES: {fails}"))
sys.exit(1 if fails else 0)
