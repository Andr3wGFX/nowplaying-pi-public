import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "stubs"))
import _sandbox  # noqa: F401  (throwaway HOME -- must precede nowplaying)
import nowplaying as np

ITEM = {"id":"t1","name":"Nights","duration_ms":307000,
        "artists":[{"name":"Frank Ocean"}],"album":{"images":[]}}
BOX = {"cur": {"item":ITEM,"is_playing":True,"progress_ms":187000,"device":{"id":"dev"}}}
class FakeSp:
    def current_playback(self): return BOX["cur"]
np.sp = FakeSp()
np.PAUSE_AFTER, np.POLL = 30.0, 0.4

# trace every push
real_push = np.push
def traced(img, box=None):
    kind = "FULL" if box is None else ("ctrl" if box == np.CTRL_BAND else "wave")
    print(f"      push {kind}")
    return real_push(img, box)
np.push = traced
# trace compose to see whether the transport is included
real_compose = np.compose
def tcompose(s, lit):
    print(f"      compose(message={np.state['message']!r})")
    return real_compose(s, lit)
np.compose = tcompose

threading.Thread(target=np.main, daemon=True).start()
time.sleep(1.2)
print("--- pausing ---"); BOX["cur"]["is_playing"] = False
time.sleep(1.2)
print("--- dropping context ---"); BOX["cur"] = None
time.sleep(1.5)
print("transport pixel (161,158):", np.disp.fb.getpixel((161,158)))
