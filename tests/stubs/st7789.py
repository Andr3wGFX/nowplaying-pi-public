"""Fake panel: keeps a framebuffer so partial-window pushes can be verified."""
import numpy
from PIL import Image

class ST7789:
    def __init__(self, **kw):
        self._width = kw.get("width", 240); self._height = kw.get("height", 240)
        self._rotation = kw.get("rotation", 0)
        self.fb = Image.new("RGB", (self._width, self._height), (0, 0, 0))
        self.full_pushes = 0; self.partial_pushes = 0; self.bytes_sent = 0
        self.set_window()
    def reset(self): pass
    def _init(self): pass
    def set_window(self, x0=0, y0=0, x1=None, y1=None):
        self._win = (x0, y0,
                     self._width - 1 if x1 is None else x1,
                     self._height - 1 if y1 is None else y1)
        self._buf = bytearray()
    def image_to_data(self, image, rotation=0):
        if not isinstance(image, numpy.ndarray):
            image = numpy.array(image.convert("RGB"))
        pb = numpy.rot90(image, rotation // 90).astype("uint16")
        red = (pb[..., [0]] & 0xF8) << 8
        green = (pb[..., [1]] & 0xFC) << 3
        blue = (pb[..., [2]] & 0xF8) >> 3
        return (red | green | blue).byteswap().tobytes()
    def data(self, d):
        self._buf.extend(d); self.bytes_sent += len(d)
        x0, y0, x1, y1 = self._win
        w, h = x1 - x0 + 1, y1 - y0 + 1
        if len(self._buf) == w * h * 2:
            arr = numpy.frombuffer(bytes(self._buf), dtype=">u2").reshape(h, w)
            r = (((arr >> 11) & 0x1F) * 255 // 31).astype("uint8")
            g = (((arr >> 5) & 0x3F) * 255 // 63).astype("uint8")
            b = ((arr & 0x1F) * 255 // 31).astype("uint8")
            self.fb.paste(Image.fromarray(numpy.dstack([r, g, b])), (x0, y0))
            if (w, h) == (self._width, self._height): self.full_pushes += 1
            else: self.partial_pushes += 1
            self._buf = bytearray()
        elif len(self._buf) > w * h * 2:
            raise AssertionError(f"overflow: window {w}x{h} got {len(self._buf)} bytes")
    def display(self, image):
        self.set_window()
        raw = self.image_to_data(image, self._rotation)
        for i in range(0, len(raw), 4096): self.data(raw[i:i+4096])
