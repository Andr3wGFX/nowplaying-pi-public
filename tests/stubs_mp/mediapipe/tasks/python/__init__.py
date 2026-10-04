from . import vision


class BaseOptions:
    def __init__(self, model_asset_path=None):
        self.model_asset_path = model_asset_path
