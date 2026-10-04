#!/usr/bin/env python3
"""
Timelapse capture and encoding for the photo booth.

Frames go to disk as numbered JPEGs first, and are encoded only at the end.
That is deliberate: a half-hour capture is a lot of the user's time to lose,
and a VideoWriter held open for thirty minutes leaves an unplayable file if
anything interrupts it. Frames on disk survive a crash, a power cut, or a
Ctrl-C, and can be re-encoded by hand afterwards.

Size matters more than it looks: Google Drive's multipart upload is capped at
5 MB (checked against Google's own docs, not assumed), and the uploader in
nowplaying.py is a multipart one. So the bitrate is computed from the clip's
length to land under a target, rather than set to a fixed number and hoped for.
"""
import json
import shutil
import subprocess
import time
from pathlib import Path


class Timelapse:
    """One capture session: a folder of frames that becomes one video."""

    def __init__(self, root, stamp, interval, fps, target_bytes=4_000_000):
        self.root = Path(root)
        self.stamp = stamp
        self.dir = self.root / stamp
        self.dir.mkdir(parents=True, exist_ok=True)
        self.interval = interval
        self.fps = fps
        self.target_bytes = target_bytes
        self.count = 0
        self.started = time.monotonic()
        self.last_frame_at = None

    # ------------------------------------------------------------- capture
    def due(self, now=None):
        now = now if now is not None else time.monotonic()
        return self.last_frame_at is None or now - self.last_frame_at >= self.interval

    def add(self, frame_bgr, cv2, quality=88):
        self.count += 1
        path = self.dir / f"f{self.count:05d}.jpg"
        cv2.imwrite(str(path), frame_bgr,
                    [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        self.last_frame_at = time.monotonic()
        return path

    @property
    def elapsed(self):
        return time.monotonic() - self.started

    @property
    def out_seconds(self):
        """How long the finished video will be, at the chosen frame rate."""
        return self.count / float(self.fps)

    # -------------------------------------------------------------- encode
    def plan(self):
        """-> (bitrate, scale_height or None, predicted_bytes).

        size = bitrate x duration, so fitting a cap is arithmetic, not taste:
        a longer clip MUST get a lower bitrate. The only real choice is what to
        spend the shortfall on, and below roughly 1.2 Mbps a 1024x768 frame
        starts to smear -- so at that point the frame is scaled down instead,
        which is what makes a low bitrate look acceptable.

        A quality floor here was a bug the tests caught: with a floor of
        700 kbps, two minutes of video would have come out at 10.5 MB and the
        upload would have failed after the user waited an hour for it.
        """
        secs = max(self.out_seconds, 1.0)
        bps = int(min(self.target_bytes * 8 / secs, 4_000_000))
        bps = max(bps, 200_000)
        scale = 480 if bps < 1_200_000 else None
        return bps, scale, int(bps * secs / 8)

    def fits_upload(self, limit=5_000_000):
        """Drive's multipart upload is capped at 5 MB -- checked against
        Google's documentation, not assumed."""
        return self.plan()[2] < limit

    def encode(self, out_path=None):
        """-> Path of the finished mp4. Raises if nothing usable was produced."""
        if self.count < 2:
            raise RuntimeError(f"only {self.count} frame(s) captured")
        out = Path(out_path or (self.root / f"{self.stamp}.mp4"))
        if shutil.which("ffmpeg"):
            self._encode_ffmpeg(out)
        else:
            self._encode_cv2(out)
        if not out.exists() or out.stat().st_size < 1024:
            raise RuntimeError("encoder produced no usable file")
        return out

    def _encode_ffmpeg(self, out):
        bps, scale, _ = self.plan()
        # -pix_fmt yuv420p because without it many players (and Drive's own
        # preview) refuse the file. The Pi 5 has NO hardware H.264 encoder --
        # that block was removed after the Pi 4 -- so this is libx264 on the
        # CPU, which is why the preset is veryfast.
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-framerate", str(self.fps),
               "-i", str(self.dir / "f%05d.jpg"),
               "-c:v", "libx264", "-preset", "veryfast",
               "-pix_fmt", "yuv420p",
               "-b:v", str(bps),
               "-movflags", "+faststart"]
        if scale:
            cmd[-1:-1] = ["-vf", f"scale=-2:{scale}"]
        cmd.append(str(out))
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {r.stderr.strip()[:200]}")

    def _encode_cv2(self, out):
        """Fallback when ffmpeg isn't installed. Quality is not controllable
        this way, so the file may be larger than the target."""
        import cv2
        frames = sorted(self.dir.glob("f*.jpg"))
        first = cv2.imread(str(frames[0]))
        h, w = first.shape[:2]
        writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"),
                                 self.fps, (w, h))
        if not writer.isOpened():
            raise RuntimeError("no ffmpeg, and OpenCV can't write mp4 either")
        try:
            for f in frames:
                im = cv2.imread(str(f))
                if im is not None:
                    writer.write(im)
        finally:
            writer.release()

    # ------------------------------------------------------------- tidying
    def manifest(self):
        return {"frames": self.count, "interval_s": self.interval,
                "fps": self.fps, "captured_s": round(self.elapsed, 1),
                "video_s": round(self.out_seconds, 2)}

    def cleanup(self, keep_frames=False):
        (self.root / f"{self.stamp}.json").write_text(
            json.dumps(self.manifest(), indent=1))
        if not keep_frames:
            shutil.rmtree(self.dir, ignore_errors=True)
