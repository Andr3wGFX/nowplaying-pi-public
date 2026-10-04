#!/usr/bin/env python3
"""
One-time Google Drive authorisation for the photo booth.

    python3 ~/np/gdrive_auth.py

Uses Google's device flow -- the one made for TVs -- so the Pi never needs a
browser. It shows you a short code; you type that into google.com/device on
your phone or laptop. drive.file is one of only six scopes this flow supports,
which is lucky, because it's also the scope that avoids Google's verification
review entirely.

Nothing here ever sees your Google password. The Pi only ever receives a token
scoped to files this app itself creates.
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

HOME = Path.home() / "np"
ENV_FILE = HOME / ".env"
TOKEN_FILE = HOME / ".gdrive-token.json"
FOLDER_NAME = "Pi Photo Booth"

SCOPE = "https://www.googleapis.com/auth/drive.file"
DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
FILES_URL = "https://www.googleapis.com/drive/v3/files"


def load_env():
    if not ENV_FILE.exists():
        sys.exit(f"{ENV_FILE} not found.")
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


load_env()
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
if not CLIENT_ID or not CLIENT_SECRET:
    sys.exit("Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to ~/np/.env first.\n"
             "See the setup steps Claude gave you.")

# ------------------------------------------------------------ step 1 ------
print("Asking Google for a device code...")
r = requests.post(DEVICE_URL, timeout=15,
                  data={"client_id": CLIENT_ID, "scope": SCOPE})
if r.status_code != 200:
    sys.exit(f"device/code failed: {r.status_code} {r.text}\n\n"
             "If this says invalid_client, the OAuth client is the wrong TYPE.\n"
             "It must be 'TVs and Limited Input devices'.")
d = r.json()

print()
print("=" * 56)
print(f"  1. On your phone or laptop, go to:  {d['verification_url']}")
print(f"  2. Enter this code:                 {d['user_code']}")
print("=" * 56)
print(f"\n  (the code is good for {d['expires_in'] // 60} minutes)")
print("\nWaiting for you to approve", end="", flush=True)

# ------------------------------------------------------------ step 2 ------
interval = max(int(d.get("interval", 5)), 5)
deadline = time.monotonic() + int(d["expires_in"])
tokens = None
while time.monotonic() < deadline:
    time.sleep(interval)
    print(".", end="", flush=True)
    r = requests.post(TOKEN_URL, timeout=15, data={
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "device_code": d["device_code"],
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
    if r.status_code == 200:
        tokens = r.json()
        break
    err = r.json().get("error", "")
    if err == "authorization_pending":
        continue
    if err == "slow_down":
        interval += 5
        continue
    if err == "access_denied":
        sys.exit("\nYou declined the request.")
    sys.exit(f"\ntoken poll failed: {r.status_code} {r.text}")

if not tokens:
    sys.exit("\nTimed out. Run it again.")

print("\n\nAuthorised.")
if "refresh_token" not in tokens:
    sys.exit("No refresh_token came back -- can't stay logged in. Remove the "
             "app's access at myaccount.google.com/permissions and retry.")

# ------------------------------------------------- a folder to upload to ---
access = tokens["access_token"]
hdr = {"Authorization": f"Bearer {access}"}
r = requests.post(FILES_URL, headers=hdr, timeout=15, json={
    "name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"})
if r.status_code not in (200, 201):
    sys.exit(f"couldn't create the Drive folder: {r.status_code} {r.text}")
folder_id = r.json()["id"]
print(f"Created Drive folder '{FOLDER_NAME}'.")

TOKEN_FILE.write_text(json.dumps({
    "refresh_token": tokens["refresh_token"],
    "folder_id": folder_id,
    "folder_name": FOLDER_NAME,
}, indent=2))
TOKEN_FILE.chmod(0o600)
print(f"Saved {TOKEN_FILE} (mode 600).")
print("\nDone. Photos you take will now upload to that folder.")
