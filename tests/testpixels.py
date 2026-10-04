import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "stubs"))
import _sandbox  # noqa: F401  (throwaway HOME -- must precede nowplaying)
import nowplaying as np
ITEM={"id":"t1","name":"Nights","duration_ms":307000,"artists":[{"name":"Frank Ocean"}],"album":{"images":[]}}
BOX={"cur":{"item":ITEM,"is_playing":True,"progress_ms":187000,"device":{"id":"dev"}}}
class F:
    def current_playback(self): return BOX["cur"]
np.sp=F(); np.PAUSE_AFTER, np.POLL = 30.0, 0.4
threading.Thread(target=np.main, daemon=True).start()

DISC=(161,158)                 # inside the play/pause disc
def check(tag):
    px=np.disp.fb.getpixel(DISC)
    accent=np.state["accent"]
    near=all(abs(a-b)<30 for a,b in zip(px,accent))
    print(f"  {tag:22} disc pixel={px} accent={accent}  transport drawn: {near}")
    np.disp.fb.save(f"/tmp/claude-0/fix-{tag.replace(' ','_')}.png")
time.sleep(1.2); check("playing")
BOX["cur"]["is_playing"]=False; time.sleep(1.2); check("just paused")
BOX["cur"]=None;               time.sleep(1.5); check("context dropped")
time.sleep(1.5); check("still waiting")
