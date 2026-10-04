"""Give a test a throwaway HOME so it can never touch real files.

nowplaying.py finds everything through Path.home() / "np" -- .env, tokens,
photos, captures, the upload ledger. Several tests delete the ledger and the
Drive token as setup. Pointed at a real HOME, that would sign the device out
of Google Drive. So every test that imports nowplaying imports this FIRST:

    import _sandbox   # noqa: F401  -- must come before `import nowplaying`

It builds  <tmp>/np/  with symlinks to the repo's read-only assets (stickers,
background, the helper modules), a few synthetic photos, and nothing secret.
Writable state (captures/, timelapse/, .uploaded.json) lands in <tmp> and is
removed at exit.
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

ROOT = Path(tempfile.mkdtemp(prefix="np-test-home-"))
NP = ROOT / "np"
NP.mkdir()
for name in ("background.png", "stickers", "fonts",
             "hamster.py", "timelapse.py"):
    src = REPO / name
    if src.exists():
        (NP / name).symlink_to(src)

photos = NP / "photos"
photos.mkdir()
try:
    from PIL import Image
    for i, rgb in enumerate([(200, 90, 60), (40, 120, 200), (90, 170, 80)]):
        Image.new("RGB", (320, 240), rgb).save(photos / f"{i:02d}-test.png")
except ImportError:
    pass

os.environ["HOME"] = str(ROOT)
# Belt and braces: never pick up real credentials from the environment.
for k in ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET",
          "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
    os.environ.pop(k, None)

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

atexit.register(shutil.rmtree, ROOT, ignore_errors=True)
