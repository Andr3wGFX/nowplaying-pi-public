# Notices and credits

The code and documentation are released under the **MIT License** — see
[`LICENSE`](LICENSE). The licence does **not** cover the images in `stickers/`
or `background.png`; see "Image rights" below.

## Ideas and code reused

- **catherpiee/hammyhamster** (a hamster face-filter app). Taken from it: reading
  head yaw/pitch off MediaPipe's `facial_transformation_matrixes` (the pitch sign
  hammyhamster's README flagged as unverified was verified here with `tools/headcheck.py`),
  the practice of resolving expression collisions by ordering rather than
  threshold-tuning, and `stickers/sideyee.jpg`. Its majority-vote smoothing was
  measured and *not* used — see `docs/build-notes-pi5.md`.

## Third-party software (installed by `setup.sh`, not vendored)

| Package | Used for | Licence |
|---|---|---|
| MediaPipe + `face_landmarker.task` model | face landmarks, blendshapes, head pose | Apache 2.0 |
| OpenCV | camera capture, image ops | Apache 2.0 (4.5+) |
| Pillow | all drawing | MIT-CMU (HPND) |
| spotipy | Spotify Web API | MIT |
| st7789 (Pimoroni) | SPI panel driver | MIT |
| gpiozero / lgpio | buttons | BSD-3 / Unlicense |
| requests | HTTP | Apache 2.0 |
| FFmpeg / libx264 | timelapse encoding | LGPL / GPL (called as a program, not linked) |
| Quicksand font | digits and fallback text | SIL OFL 1.1 |

## Data services

- **Open-Meteo** — weather. Free for non-commercial use, no key; their terms ask
  for attribution (CC BY 4.0) if the data is shown publicly.
- **Spotify Web API** and **Google Drive API** — used under each developer's own
  app credentials, which live only in `~/np/.env` and are never committed.

## Not included, on purpose

- **Mochi Boom font** — its licence forbids redistribution. See `fonts/README.md`.
- **Personal photos, captures, timelapses** — `.gitignore` blocks them.
- **Credentials and tokens** — `.env`, `.gdrive-token.json`, `.spotify-cache`.

## Image rights

- **Stickers:** the hamster drawings are meme art collected from around the
  internet; the author of this repo doesn't own them and can't license them.
  They're included so the filter works out of the box. If you reuse this
  project — especially for anything you share or sell — swap in images you have
  the rights to. `tools/sticker_sheet.py` redraws `docs/stickers.png` after you
  change the set. If you own one of these images and want it removed, open an
  issue.
- **`background.png`:** origin not recorded. Same caveat.
