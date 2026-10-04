#!/usr/bin/env bash
# Run every test. Needs no Pi, camera, panel or network: the display, GPIO,
# Spotify, webcam and MediaPipe are all faked (tests/stubs, tests/stubs_mp),
# and each test that imports nowplaying gets a throwaway HOME (_sandbox.py).
#
#   bash tests/run_all.sh
#
# Needs: python3 with pillow, numpy, opencv (cv2), requests. ffmpeg optional
# (testtimelapse falls back to OpenCV's encoder without it).
#
# Two styles of test live here:
#   assert-style  exit non-zero on failure         -> PASS/FAIL is reliable
#   print-style   print what they saw; read it     -> exit code only catches crashes
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"

ASSERT="testmp testgeom testhead testtimelapse testtlflow"
PRINT="testpause testpixels testoverlay testcamera testupload testtrace"

fail=0
for t in $ASSERT; do
  if "$PY" "$t.py" >"/tmp/np-$t.log" 2>&1; then
    echo "PASS  $t"
  else
    echo "FAIL  $t   (log: /tmp/np-$t.log)"; fail=1
  fi
done
echo
for t in $PRINT; do
  if timeout 300 "$PY" "$t.py" >"/tmp/np-$t.log" 2>&1; then
    echo "ran   $t   (print-style: read /tmp/np-$t.log)"
  else
    echo "CRASH $t   (log: /tmp/np-$t.log)"; fail=1
  fi
done
exit $fail
