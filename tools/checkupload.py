#!/usr/bin/env python3
"""
Why didn't the photo upload?     python3 ~/np/tools/checkupload.py

Checks every link in the chain and then actually tries an upload, so you get
the real error from Google instead of a guess. Safe to run while the display
is going -- it touches no GPIO.
"""
import json
import os
import sys
from pathlib import Path

import requests

HOME = Path.home() / "np"
ENV_FILE = HOME / ".env"
TOKEN_FILE = HOME / ".gdrive-token.json"
LEDGER = HOME / ".uploaded.json"
CAPTURES = HOME / "captures"
PROGRAM = HOME / "nowplaying.py"

ok = True


def good(msg):
    print(f"  [ ok ] {msg}")


def bad(msg, fix=""):
    global ok
    ok = False
    print(f"  [FAIL] {msg}")
    if fix:
        print(f"         -> {fix}")


print("\n1. Is the running program the one with the uploader in it?")
if not PROGRAM.exists():
    bad(f"{PROGRAM} not found")
else:
    src = PROGRAM.read_text()
    if "def upload_worker" in src and "uploadType=multipart" in src:
        good(f"nowplaying.py has the uploader ({len(src.splitlines())} lines)")
    else:
        bad("nowplaying.py is an OLDER version with no uploader",
            "update it:  cd ~/np && git pull")

print("\n2. Credentials")
if not ENV_FILE.exists():
    bad(f"{ENV_FILE} missing")
else:
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        val = os.environ.get(key, "")
        if val:
            good(f"{key} present ({len(val)} chars)")     # never printed
        else:
            bad(f"{key} missing from ~/np/.env")

print("\n3. Authorisation")
cfg = None
if not TOKEN_FILE.exists():
    bad("no ~/np/.gdrive-token.json",
        "run:  python ~/np/gdrive_auth.py")
else:
    try:
        cfg = json.loads(TOKEN_FILE.read_text())
        good(f"token file present, folder id {cfg.get('folder_id','?')[:12]}...")
    except Exception as e:
        bad(f"token file unreadable: {e}", "re-run gdrive_auth.py")

print("\n4. Photos on disk")
shots = sorted(CAPTURES.glob("*.jpg")) if CAPTURES.is_dir() else []
if not shots:
    bad("no photos in ~/np/captures",
        "take one: hold the middle button, then press next")
else:
    good(f"{len(shots)} photo(s); newest is {shots[-1].name}")

done = set()
if LEDGER.exists():
    try:
        done = set(json.loads(LEDGER.read_text()))
    except Exception:
        pass
pending = [s for s in shots if s.name not in done]
print(f"         {len(done)} recorded as uploaded, {len(pending)} pending")

if not ok or not cfg or not shots:
    print("\nStopping here -- fix the failures above first.\n")
    sys.exit(1)

print("\n5. Trading the refresh token for an access token")
try:
    r = requests.post("https://oauth2.googleapis.com/token", timeout=20, data={
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": cfg["refresh_token"],
        "grant_type": "refresh_token"})
    if r.status_code != 200:
        bad(f"refresh failed: {r.status_code} {r.text[:300]}")
        if "invalid_grant" in r.text:
            print("         -> invalid_grant usually means the app is still in")
            print("            TESTING. Publish it (Audience -> Publish app),")
            print("            then re-run gdrive_auth.py.")
        sys.exit(1)
    token = r.json()["access_token"]
    good("got an access token")
except Exception as e:
    bad(f"couldn't reach Google: {e}")
    sys.exit(1)

print("\n6. Does the target folder still exist?")
r = requests.get(f"https://www.googleapis.com/drive/v3/files/{cfg['folder_id']}",
                 headers={"Authorization": f"Bearer {token}"},
                 params={"fields": "id,name,trashed"}, timeout=20)
if r.status_code == 200:
    info = r.json()
    good(f"folder '{info['name']}' ok" + ("  (IN TRASH!)" if info.get("trashed") else ""))
else:
    bad(f"folder lookup failed: {r.status_code} {r.text[:200]}",
        "the folder was deleted -- re-run gdrive_auth.py to make a new one")
    sys.exit(1)

print("\n7. Uploading the newest photo for real")
path = shots[-1]
boundary = "----checkupload"
meta = {"name": path.name, "parents": [cfg["folder_id"]]}
body = (
    f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
    f"{json.dumps(meta)}\r\n--{boundary}\r\nContent-Type: image/jpeg\r\n\r\n"
).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
r = requests.post(
    "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
    timeout=90, data=body,
    headers={"Authorization": f"Bearer {token}",
             "Content-Type": f"multipart/related; boundary={boundary}"})
if r.status_code in (200, 201):
    fid = r.json().get("id")
    good(f"uploaded {path.name} ({path.stat().st_size // 1024} KB)")
    print(f"\n  It is in Drive now: https://drive.google.com/file/d/{fid}/view")
    print("\n  So the credentials and the folder are all fine. If the program")
    print("  itself still isn't uploading, it was started BEFORE you ran")
    print("  gdrive_auth.py -- the worker only looks for the token once, at")
    print("  startup. Restart it:")
    print("      sudo systemctl restart nowplaying     (if installed as a service)")
    print("      or Ctrl+C and run it again")
else:
    bad(f"upload failed: {r.status_code}")
    print(r.text[:600])
