import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "stubs"))
import _sandbox  # noqa: F401  (throwaway HOME -- must precede nowplaying)
from PIL import Image
import nowplaying as np
from st7789 import ST7789 as Fake

np.weather.update(temp=71, code=2, ok=True)          # pretend the fetch worked
print("overlay lines:", np.overlay_lines())

photos = sorted(np.PHOTO_DIR.glob("*.png"))
sheet = Image.new("RGB", (320*2+30, 240*2+30), (238,240,244))
for i, p in enumerate(photos[:4]):
    sheet.paste(np.with_overlay(np.load_photo(p)), (10+(i%2)*330, 10+(i//2)*250))
sheet.save("/tmp/claude-0/overlay-sheet.png")

# --- the band-origin test that caught the last bug -----------------------
photo = np.load_photo(photos[0])
ref = Fake(width=320, height=240, rotation=0); ref.display(np.with_overlay(photo))

panel = np.disp
panel.display(photo)                                  # clean photo on the panel
band = np.crop_band(photo, np.OVL_BAND)
np.draw_overlay(band, origin=(np.OVL_BAND[0], np.OVL_BAND[1]))
np.push(band, np.OVL_BAND)                            # then just the strip

diff = sum(1 for a, b in zip(list(ref.fb.getdata()), list(panel.fb.getdata())) if a != b)
w = np.OVL_BAND[2]-np.OVL_BAND[0]+1; h = np.OVL_BAND[3]-np.OVL_BAND[1]+1
print(f"band {w}x{h} = {w*h*2} bytes = {w*h*2*8/4e6*1000:.0f} ms at 4 MHz")
print(f"pixels differing from a full-frame render: {diff} / {320*240}")
panel.fb.save("/tmp/claude-0/overlay-banded.png")

# --- weather failure must not break the clock ---------------------------
np.weather.update(temp=None, code=None, ok=False)
print("with weather unavailable:", np.overlay_lines())
np.with_overlay(photo).save("/tmp/claude-0/overlay-noweather.png")
