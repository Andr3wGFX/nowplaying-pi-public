class SpotifyException(Exception):
    def __init__(self, http_status=404, *a): self.http_status = http_status
class Spotify:
    def __init__(self, **kw): pass
    def current_playback(self): return None
    def previous_track(self, **kw): pass
    def next_track(self, **kw): pass
    def start_playback(self, **kw): pass
    def pause_playback(self, **kw): pass
