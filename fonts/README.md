# fonts/

Optional. The program looks for `fonts/MochiBoom.ttf` for the song title and
artist words, and falls back to **Quicksand** (apt `fonts-quicksand`, installed
by `setup.sh`) if it isn't there. Everything still works without it.

Mochi Boom isn't included because its licence doesn't allow redistribution.
If you have your own copy, drop it here as `MochiBoom.ttf`.

⚠ The free DEMO version's ten digits are watermark glyphs, which is why the
program never draws numbers in Mochi — clock, times and counters always use
Quicksand. Check any demo font for that before designing around it.

`.gitignore` ignores everything in this folder except this README, so a font
you add can't be pushed by accident.
