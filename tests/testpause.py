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
    def previous_track(self,**k): pass
    def next_track(self,**k): pass
    def start_playback(self,**k): pass
    def pause_playback(self,**k): pass
np.sp = FakeSp()
np.PAUSE_AFTER, np.PHOTO_SECS, np.POLL, np.FADE_STEPS = 6.0, 2.0, 0.4, 1
threading.Thread(target=np.main, daemon=True).start()

def show(tag):
    print(f"  {tag:34} message={np.state['message']!r:18} title={np.state['title']!r:10} "
          f"playing={np.state['playing']}  photo_mode={np.in_photo_mode()}")
    np.disp.fb.save(f"/tmp/claude-0/pause-{tag.replace(' ','_')}.png")

time.sleep(1.0); show("1 playing")
print("user pauses (Spotify still reports the track):")
BOX["cur"]["is_playing"] = False
time.sleep(1.0); show("2 just paused")
print("Spotify drops the playback context, as it does a few seconds later:")
BOX["cur"] = None
time.sleep(1.2); show("3 context dropped")
print("...still inside the 6 s window, screen should be unchanged:")
time.sleep(2.0); show("4 still waiting")
print("past the timeout:")
time.sleep(3.5); show("5 slideshow")
