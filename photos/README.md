# photos/

Slideshow photos, shown after the music has been paused for 10 seconds.

Put your originals anywhere, then convert them to the panel's 320×240:

    ~/np/bin/python ~/np/convert_photos.py ~/originals ~/np/photos

The second argument matters: without it the results go to
`~/originals/converted/`, not here. It honours phone rotation tags and
centre-crops to 4:3 (portrait shots get cropped hard; it flags them).
iPhone `.heic` files are skipped unless you `pip install pillow-heif` —
easiest is to export as JPEG first.

Personal photos are **not** in the repo — `.gitignore` ignores everything in
this folder except this README.
