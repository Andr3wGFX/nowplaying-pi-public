"""Fake MediaPipe: enough of the FaceLandmarker surface to test the filter's
geometry without a model, a camera or a face. Landmarks are injected."""


class ImageFormat:
    SRGB = "srgb"


class Image:
    def __init__(self, image_format=None, data=None):
        self.image_format, self.data = image_format, data


# the test sets these
FAKE_LANDMARKS = []          # list of faces; each a list of (x, y) normalised
FAKE_BLENDSHAPES = []        # list of dicts {category_name: score}
FAKE_MATRICES = []           # list of 4x4 rotation matrices
