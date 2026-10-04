"""Fake camera: synthetic moving frames so the camera path can be exercised."""
import numpy as np

CAP_V4L2 = 200
CAP_PROP_FOURCC = 6
CAP_PROP_FRAME_WIDTH = 3
CAP_PROP_FRAME_HEIGHT = 4
CAP_PROP_BUFFERSIZE = 38
COLOR_BGR2RGB = 4
__version__ = "fake-1.0"

FAIL_OPEN = False          # flip in a test to simulate no camera


def VideoWriter_fourcc(*a):
    return 1196444237


def cvtColor(frame, code):
    return frame[:, :, ::-1].copy()


def flip(frame, axis):
    return frame[:, ::-1].copy() if axis == 1 else frame[::-1].copy()


class VideoCapture:
    def __init__(self, index=0, api=None):
        self.w, self.h, self.n = 640, 480, 0
        self._open = not FAIL_OPEN
    def isOpened(self):
        return self._open
    def set(self, prop, val):
        if prop == CAP_PROP_FRAME_WIDTH: self.w = int(val)
        if prop == CAP_PROP_FRAME_HEIGHT: self.h = int(val)
        return True
    def get(self, prop):
        return {CAP_PROP_FRAME_WIDTH: self.w, CAP_PROP_FRAME_HEIGHT: self.h}.get(prop, 0)
    def read(self):
        if not self._open:
            return False, None
        self.n += 1
        f = np.zeros((self.h, self.w, 3), dtype=np.uint8)
        f[:, :, 0] = 40                                   # B
        f[:, :, 1] = 90
        f[:, :, 2] = 150
        x = (self.n * 13) % max(self.w - 80, 1)           # a moving block
        f[self.h//3:self.h//3+120, x:x+80] = (60, 220, 255)
        f[:, ::64] = 255                                  # vertical rulers
        return True, f
    def release(self):
        self._open = False
