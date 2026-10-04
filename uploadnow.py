#!/usr/bin/env python3
"""
Upload files to the same Drive folder the photo booth uses.

    source ~/np/bin/activate
    python ~/np/uploadnow.py ~/np/timelapse/*.mp4

For anything recorded or captured while offline. The running program re-queues
stranded JPEGs on startup but never looked at the timelapse folder, so videos
made off-wifi sat there forever -- that's now fixed in nowplaying.py, and this
is the manual version for files already stranded.

Writes to the same ledger the program uses, so nothing gets uploaded twice.
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

HOME = Path.home() / "np"
ENV_FILE = HOME / ".env"
GDRIVE_TOKEN = HOME / ".gdrive-token.json"
LEDGER = HOME / ".uploaded.json"
UPLOAD_URL = ("https://www.googleapis.com/upload/drive/v3/files"
              "?uploadType=multipart")
TOKEN_URL = "https://oauth2.googleapis.com/token"
LIMIT = 5_000_000            # Drive's multipart cap

if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

cfg = json.loads(GDRIVE_TOKEN.read_text())
r = requests.post(TOKEN_URL, timeout=20, data={
    "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
    "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    "refresh_token": cfg["refresh_token"], "grant_type": "refresh_token"})
r.raise_for_status()
token = r.json()["access_token"]

try:
    done = set(json.loads(LEDGER.read_text()))
except Exception:
    done = set()

MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".mp4": "video/mp4"}

paths = [Path(a) for a in sys.argv[1:]]
if not paths:
    sys.exit("usage: python uploadnow.py <file> [file ...]")

for path in paths:
    if not path.is_file():
        print(f"  skip   {path}  (not a file)")
        continue
    size = path.stat().st_size
    if path.name in done:
        print(f"  skip   {path.name}  (already in the ledger)")
        continue
    if size >= LIMIT:
        print(f"  SKIP   {path.name}  {size/1e6:.2f} MB -- over Drive's "
              f"5 MB multipart limit")
        continue
    mime = MIME.get(path.suffix.lower(), "application/octet-stream")
    meta = {"name": path.name, "parents": [cfg["folder_id"]]}
    b = "----npbooth" + str(int(time.time() * 1000))
    body = (
        f"--{b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(meta)}\r\n--{b}\r\nContent-Type: {mime}\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{b}--\r\n".encode()
    print(f"  ...    {path.name}  {size/1e6:.2f} MB as {mime}", flush=True)
    resp = requests.post(UPLOAD_URL, timeout=180, data=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/related; boundary={b}"})
    if resp.status_code >= 300:
        print(f"  FAIL   {path.name}: {resp.status_code} {resp.text[:120]}")
        continue
    done.add(path.name)
    LEDGER.write_text(json.dumps(sorted(done)))
    print(f"  ok     {path.name} -> {resp.json().get('id')}")

print("done")
