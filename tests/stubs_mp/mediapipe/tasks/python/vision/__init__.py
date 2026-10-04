import mediapipe as _mp


class RunningMode:
    IMAGE = "image"
    VIDEO = "video"


class FaceLandmarkerOptions:
    def __init__(self, base_options=None, running_mode=None, num_faces=1,
                 output_face_blendshapes=False,
                 output_facial_transformation_matrixes=False):
        self.base_options = base_options
        self.running_mode = running_mode
        self.num_faces = num_faces
        self.output_face_blendshapes = output_face_blendshapes
        self.output_facial_transformation_matrixes = (
            output_facial_transformation_matrixes)


class _Mark:
    def __init__(self, x, y):
        self.x, self.y = x, y


class _Cat:
    def __init__(self, name, score):
        self.category_name, self.score = name, score


class _Result:
    def __init__(self):
        self.face_landmarks = [[_Mark(x, y) for (x, y) in f]
                               for f in _mp.FAKE_LANDMARKS]
        self.face_blendshapes = [[_Cat(k, v) for k, v in b.items()]
                                 for b in _mp.FAKE_BLENDSHAPES]
        self.facial_transformation_matrixes = list(_mp.FAKE_MATRICES)


class FaceLandmarker:
    calls = {"video": 0, "image": 0}

    def __init__(self, options):
        self.options = options

    @classmethod
    def create_from_options(cls, options):
        return cls(options)

    def detect(self, image):
        FaceLandmarker.calls["image"] += 1
        return _Result()

    def detect_for_video(self, image, ts):
        FaceLandmarker.calls["video"] += 1
        return _Result()

    def close(self):
        pass
