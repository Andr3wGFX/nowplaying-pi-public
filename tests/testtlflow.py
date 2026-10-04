#!/usr/bin/env python3
"""End-to-end test of the timelapse MODE: buttons, capture loop, encode,
upload queue, and the state you are left in afterwards.

Runs the real nowplaying.py against the fake display and GPIO, with the
intervals shrunk so half an hour takes a second.
"""
import sys
import shutil
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
# Import the REAL cv2 before stubs/ goes on the path -- stubs/ contains a fake
# cv2 for the display tests, and it would shadow the real one. (Easy to get
# wrong when editing this file; hence the comment rather than just the fix.)
import cv2 as real_cv2
import numpy as np

sys.path.insert(0, str(HERE / "stubs"))
sys.path.insert(0, str(HERE))
import _sandbox  # noqa: F401,E402  (throwaway HOME -- must precede nowplaying)
import nowplaying as np_app

fails = []
def check(name, got, want=True):
    ok = (got == want)
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}: {got}"
          + ("" if ok else f"  (want {want})"))
    if not ok:
        fails.append(name)


class FakeCap:
    """Hands back a different frame each time, so a stuck grab is visible."""
    def __init__(self):
        self.i = 0
        self.grabs = 0
    def grab(self):
        self.grabs += 1
        return True
    def retrieve(self):
        self.i += 1
        im = np.zeros((768, 1024, 3), np.uint8)
        im[:] = (20 + self.i * 4 % 200, 70, 160)
        real_cv2.putText(im, str(self.i), (60, 200),
                         real_cv2.FONT_HERSHEY_SIMPLEX, 4, (255, 255, 255), 8)
        return True, im
    def read(self):
        return self.retrieve()
    def release(self):
        pass


tmp = Path(tempfile.mkdtemp())
np_app.TL_DIR = tmp
np_app.TL_INTERVAL = 0.05
np_app.TL_MAX_SECS = 4.0
np_app.TL_TICK = 0.02
np_app.TL_FPS = 10
np_app.CAPTURE_DIR = tmp / "captures"

uploaded = []
np_app.queue_upload = lambda p: uploaded.append(Path(p))

print("1. the shutter's two jobs stay separate")
np_app.camera_on = True
np_app.timelapse_on = False
np_app.next_held = False
np_app.cam_shoot_at = None
np_app.on_next()                             # a plain press
check("plain press arms the photo countdown", np_app.cam_shoot_at is not None)
np_app.cam_shoot_at = None

np_app.on_next_hold()                        # a hold
check("hold starts a timelapse", np_app.timelapse_on)
np_app.on_next()                             # the release that follows a hold
check("the release after a hold does NOT also take a photo",
      np_app.cam_shoot_at, None)
check("the held flag was cleared", np_app.next_held, False)

print("\n2. capture, then stop with the middle button")
cap = FakeCap()
import threading
def stopper():
    time.sleep(1.5)
    np_app.on_middle_release()               # stop mid-capture
threading.Thread(target=stopper, daemon=True).start()
t0 = time.monotonic()
np_app.run_timelapse(cap, real_cv2)
took = time.monotonic() - t0
print(f"  ran {took:.1f}s, captured {np_app._tl.count if np_app._tl else '?'} frames")
check("stopped early rather than running to the end", took < 3.5)
check("timelapse flag cleared", np_app.timelapse_on, False)
check("STILL in camera mode afterwards", np_app.camera_on, True)
check("stale frames were flushed before each capture", cap.grabs >= cap.i)

print("\n3. what it produced")
vids = sorted(tmp.glob("*.mp4"))
check("one video written", len(vids), 1)
if vids:
    sz = vids[0].stat().st_size
    print(f"  {vids[0].name}  {sz / 1000:.0f} kB")
    check("video is not empty", sz > 1000)
    probe = __import__("subprocess").run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,nb_frames", "-of", "default=nw=1",
         str(vids[0])], capture_output=True, text=True)
    print("  ffprobe:", probe.stdout.strip().replace("\n", "  "))
    check("h264", "h264" in probe.stdout)
check("queued for upload", [p.suffix for p in uploaded], [".mp4"])
check("frame folder cleaned up", list(tmp.glob("*/f00001.jpg")), [])
check("manifest kept", len(list(tmp.glob("*.json"))), 1)

print("\n4. the middle button's three levels")
np_app.camera_on = True
np_app.timelapse_on = True
np_app.held_fired = False
np_app.on_middle_release()
check("1st press stops the capture", (np_app.timelapse_on, np_app.camera_on),
      (False, True))
np_app.on_middle_release()
check("2nd press leaves camera mode", np_app.camera_on, False)

shutil.rmtree(tmp)
print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURES: {fails}"))
sys.exit(1 if fails else 0)
