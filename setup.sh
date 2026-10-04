#!/usr/bin/env bash
# One-shot setup for a fresh Raspberry Pi OS (64-bit, Debian 13 "trixie").
#
#   git clone <this repo> ~/np
#   bash ~/np/setup.sh              # everything, including the hamster filter
#   bash ~/np/setup.sh --no-hamster # skip MediaPipe (display + camera still work)
#
# Safe to re-run: every step checks before it acts, and it never overwrites
# your .env, tokens, photos or captures.
set -euo pipefail

HAMSTER=1
[ "${1:-}" = "--no-hamster" ] && HAMSTER=0

NP="$HOME/np"
HERE="$(cd "$(dirname "$0")" && pwd)"
MODEL_URL="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die()  { printf '\n\033[31mSTOP:\033[0m %s\n' "$*"; exit 1; }

[ "$(id -u)" -ne 0 ] || die "run this as your normal user, not with sudo -- it asks for sudo itself where needed."
# Every path in the program is ~/np/... (Path.home() / "np"), so the repo
# has to BE ~/np. Refusing here beats a program that silently can't find
# its stickers later.
[ "$HERE" = "$NP" ] || die "this repo is at $HERE but must be at $NP.
      Move it:  mv \"$HERE\" \"$NP\"   then run  bash ~/np/setup.sh"

say "1/7  System packages (apt)"
# python3-opencv comes from apt, NOT pip: pip's OpenCV tries to build from
# source on ARM. ffmpeg encodes timelapses (the Pi 5 has no hardware H.264
# encoder). libgles2/libegl1 are what MediaPipe needs and Lite doesn't ship.
sudo apt update
sudo apt install -y python3-opencv v4l-utils ffmpeg fonts-quicksand \
                    python3-venv python3-lgpio libgles2 libegl1

say "2/7  SPI (the display's bus)"
if [ -e /dev/spidev0.0 ]; then
  echo "SPI already on."
elif command -v raspi-config >/dev/null; then
  sudo raspi-config nonint do_spi 0      # 0 = enable (yes, really)
  NEED_REBOOT=1
  echo "SPI enabled -- takes effect after a reboot."
else
  echo "raspi-config not found; enable SPI by hand (dtparam=spi=on in /boot/firmware/config.txt)."
fi

say "3/7  Python virtual environment in ~/np"
# --system-site-packages so the venv sees apt's OpenCV and lgpio.
# Creating a venv over a folder that already has files leaves them untouched.
if [ -x "$NP/bin/python" ]; then
  echo "venv already exists."
else
  python3 -m venv "$NP" --system-site-packages
fi
"$NP/bin/pip" install --upgrade pip >/dev/null
"$NP/bin/pip" install -r "$NP/requirements.txt"

if [ "$HAMSTER" = 1 ]; then
  say "4/7  MediaPipe for the hamster filter"
  # MediaPipe hard-depends on opencv-contrib-python and would pull OpenCV 5.x
  # into the venv, shadowing apt's 4.x. The pin in this file keeps it on 4.x.
  "$NP/bin/pip" install -r "$NP/requirements-mediapipe.txt"
  if [ ! -s "$NP/face_landmarker.task" ]; then
    echo "Downloading the face model (a few MB)..."
    curl -fL --retry 3 -o "$NP/face_landmarker.task" "$MODEL_URL"
  else
    echo "face_landmarker.task already present."
  fi
else
  say "4/7  MediaPipe skipped (--no-hamster)"
fi

say "5/7  Folders"
mkdir -p "$NP/photos" "$NP/captures" "$NP/timelapse" "$NP/fonts"

say "6/7  Credentials file"
if [ -f "$NP/.env" ]; then
  echo ".env already exists -- left alone."
else
  cp "$NP/.env.example" "$NP/.env"
  echo "Created ~/np/.env from the template. FILL IT IN before running."
fi
chmod 600 "$NP/.env"   # it holds two client secrets: owner-only

say "7/7  Quick self-check"
HAMSTER="$HAMSTER" "$NP/bin/python" - <<'PY'
import importlib, os
mods = ["cv2", "PIL", "spotipy", "requests", "gpiozero", "st7789"]
if os.environ.get("HAMSTER") == "1":
    mods.append("mediapipe")          # skipped with --no-hamster on purpose
for m in mods:
    try:
        mod = importlib.import_module(m)
        print(f"  ok       {m:<10} {getattr(mod, '__version__', '')}")
    except Exception as e:
        print(f"  MISSING  {m:<10} {type(e).__name__}: {e}")
import cv2
if cv2.__version__.startswith("5"):
    print("  WARNING  OpenCV 5.x is active -- the <5 pin didn't hold")
PY

echo
echo "Done. Next:"
[ "${NEED_REBOOT:-0}" = 1 ] && echo "  0. sudo reboot                      (SPI needs it)"
echo "  1. nano ~/np/.env                   (Spotify + Google keys, location)"
echo "  2. ~/np/bin/python ~/np/gdrive_auth.py   (once, for Drive upload; optional)"
echo "  3. ~/np/bin/python ~/np/nowplaying.py    (first run: Spotify sign-in)"
echo "  4. bash ~/np/install_service.sh     (start at boot)"
