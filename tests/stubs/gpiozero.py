class Button:
    def __init__(self, pin, hold_time=1.0, **kw):
        self.pin = pin
        self.hold_time = hold_time
        self.when_pressed = None
        self.when_held = None
        self.when_released = None


class LED:
    def __init__(self, pin):
        self.pin = pin
