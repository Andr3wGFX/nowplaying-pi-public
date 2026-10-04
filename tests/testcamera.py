import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "stubs"))
import _sandbox  # noqa: F401  (throwaway HOME -- must precede nowplaying)
import nowplaying as np

print(f"SPI configured at {np.SPI_HZ/1e6:.0f} MHz, TICK={np.TICK}")

# clear out anything from a previous run
for f in np.CAPTURE_DIR.glob("*.jpg"):
    f.unlink()

# --- button logic: a long press must NOT also fire play/pause -------------
np.state["playing"] = True
np.lock_until = 0
np.on_hold()                       # held 3 s
assert np.camera_on, "hold should enter camera mode"
np.on_middle_release()             # the release that follows the hold
print("after hold+release : camera_on =", np.camera_on,
      "| playing still", np.state["playing"], "(must be True)")
assert np.state["playing"] is True, "long press leaked into play/pause!"

# --- run the viewfinder ---------------------------------------------------
shots = {}
t = threading.Thread(target=np.run_camera, daemon=True)
t.start()
time.sleep(1.0)
np.disp.fb.save("/tmp/claude-0/cam-1-viewfinder.png")
shots["viewfinder"] = np.disp.fb.getpixel((160, 120))

np.lock_until = 0
np.on_next()                       # start the countdown
time.sleep(0.6)
np.disp.fb.save("/tmp/claude-0/cam-2-countdown.png")

time.sleep(2.9)                    # countdown elapses, capture happens
np.disp.fb.save("/tmp/claude-0/cam-3-saved.png")

np.lock_until = 0
np.on_middle_release()             # short press exits
t.join(timeout=5)
print("camera thread exited:", not t.is_alive())

saved = sorted(np.CAPTURE_DIR.glob("*.jpg"))
print("saved files        :", [f.name for f in saved])
if saved:
    from PIL import Image
    im = Image.open(saved[0])
    print("saved image        :", im.size, im.mode, f"{saved[0].stat().st_size} bytes")
print("upload queue       :", [f.name for f in list(np.upload_q.queue)])

# --- prev button in camera mode toggles the hamster filter ----------------
# (It used to toggle the mirror; that moved when the filter arrived.)
np.lock_until = 0
before = np.cam_filter
np.camera_on = True; np.on_prev(); np.camera_on = False
print("filter toggled     :", before, "->", np.cam_filter,
      "(must differ)" if np.FILTER_ENABLED else "(filter disabled: no change expected)")

# --- no camera present ----------------------------------------------------
import cv2
cv2.FAIL_OPEN = True
np.camera_on = True
np.run_camera()
np.disp.fb.save("/tmp/claude-0/cam-4-nocamera.png")
print("no-camera handled  : camera_on =", np.camera_on, "(must be False)")
