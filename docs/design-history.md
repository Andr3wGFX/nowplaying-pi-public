# Design history — how this project got to where it is

This page tells the story of the build: what was tried, what broke, and why
each decision went the way it did. It's meant for anyone building something
similar, and for anyone wondering *why* the code looks the way it does.

For the raw numbers and debugging detail behind each step, see
[`build-notes-pi4.md`](build-notes-pi4.md) and
[`build-notes-pi5.md`](build-notes-pi5.md).

| Stage | Board | What changed |
|---|---|---|
| 1 | Pi 4 | Spotify now-playing screen, three buttons |
| 2 | Pi 4 | Photo slideshow, clock and weather when the music stops |
| 3 | Pi 4 | Camera mode and Google Drive upload |
| 4 | Pi 4 | First hamster filter (OpenCV) — hit the limits of the Pi 4 |
| 5 | **Pi 5** | Board swap so MediaPipe could run |
| 6 | Pi 5 | Expression-aware hamster filter rebuilt on MediaPipe |
| 7 | Pi 5 | Timelapse mode |
| 8 | Pi 5 | Packaged for other people: `setup.sh`, tests, docs |

---

## 1. The starting point: a tiny screen on a Pi 4

**Goal:** a desk gadget that shows what's playing on Spotify, controlled with
physical buttons.

**Hardware choices**

- **Raspberry Pi 4 (2 GB)** — plenty for drawing a 320×240 screen.
- **Waveshare 2inch LCD (ST7789V, 320×240)** — small, and driven over
  **SPI**, a fast serial connection on the Pi's pins. No HDMI and no desktop
  needed.
- **Three buttons** wired straight from GPIO pins to ground. The Pi's built-in
  "pull-up" resistors mean no extra parts.
- **Raspberry Pi OS Lite** — no desktop. It's an appliance with no
  monitor or keyboard, so a desktop would just waste memory and boot time.

**The first big lesson: the screen that lit up but showed nothing.** The
`st7789` driver (version 1.0.1) holds the screen's reset pin in the "reset"
position and never lets go. The backlight comes on, but the screen stays
blank — with no error. The fix is two lines (`disp.reset()` then
`disp._init()`), but finding it meant reading the library's source. That
experience set the tone for the whole project: **read the library, and check
the actual output, not a proxy for it.**

**How fast can the screen go?** A speed test showed the SPI link is clean at
**64 MHz** (64 million bits per second). A full frame takes about 20 ms to send. An earlier note said 32 MHz
was "unreliable", but that test was run while the reset bug meant *nothing*
displayed at any speed — a false conclusion from a broken experiment.

**Only redraw what changed.** The progress bar and buttons are sent as small
strips instead of redrawing the whole screen each time. A test once reported
"2 strip updates sent" while the strip was completely blank, because the
drawing code used whole-screen coordinates on a cropped strip. Since then,
**screen tests compare actual pixels**, never counts of updates.

**Look and feel**

- The background image is blurred, slightly desaturated and dimmed, so text
  stays readable over it.
- Round shapes are drawn at 4× size and shrunk down, because Pillow (the
  drawing library) doesn't smooth the edges of circles and polygons.
- The progress bar is a moving sine wave that flattens out at both ends.
- **The font trap:** the display font's free demo version replaces all ten
  digits with watermark shapes. So every number on screen (clock, times,
  counters) uses Quicksand instead. The same font also has no accented
  letters, so names like "Björk" are simplified to "Bjork" instead of showing
  empty boxes.

**Spotify sign-in on a device with no browser.** Spotify sign-in normally
opens a browser on the same machine. Instead, the program prints a link: you
approve on your phone, then paste the resulting address back into the
terminal. No port-forwarding tricks needed.

---

## 2. Slideshow, clock and weather

When the music has been paused for 10 seconds, the screen switches to a
slideshow of your own photos with a big clock, the date and the weather.

- **Weather from Open-Meteo**, chosen because it needs no API key.
- The weather is fetched **in the background**, so a slow network can never
  freeze the screen.
- **Time zones:** the clock uses a proper zone name (like `Europe/London`).
  Some places don't use daylight saving, so a generic zone would be an hour
  out for half the year.
- Spotify stops reporting the track a few seconds after you pause. Instead of
  blanking the screen, the program keeps showing the last track.

---

## 3. Camera mode and Drive upload

A USB webcam (Logitech C270) turned the gadget into a photo booth.

**Buttons that act when released.** Holding the middle button for 3 seconds
opens the camera. A plain press means play/pause. If the button acted on
*press*, every long hold would also pause the music. So it acts on *release*
and checks whether it was a hold. Every dual-purpose button now works this
way, and there's a test for it.

**Why Google Drive and not Google Photos?** Two reasons:

- A Google Photos app has to pass Google's review.
- An app left in "testing" mode gets signed out every 7 days — on a device
  with no screen, that means re-doing the sign-in every week.

Drive's **`drive.file`** permission only lets the app see files it created
itself. Google treats it as low-risk, so the app can be published without a
review, and the sign-in lasts.

---

## 4. The first hamster filter — and the wall

The idea: put a cartoon hamster over each face, and change the hamster to
match your expression.

The first version used OpenCV on the Pi 4: one tool (a "Haar cascade") to find
faces, another (the "LBF" landmark model) to place 68 points on each face. It
ran at about **9 frames per second** with three moods. Getting the stickers to
line up meant measuring, not guessing: a guessed eye-spacing constant made
every sticker 29% too big.

**Blink detection was impossible.** With eyes *closed*, the model's
eye-openness score was **0.230**; with eyes *open*, it was **0.210** — the
wrong way round. The model wasn't detecting eyes at all; it was guessing where
they ought to be.

**The fix was Google's MediaPipe**, which finds 478 points per face *and* gives
direct expression scores (smile, jaw open, blink…). It installed fine on the
Pi 4 and then crashed instantly:

```
FATAL ERROR: This binary was compiled with aes enabled
```

MediaPipe needs a set of CPU instructions (the ARMv8 crypto extensions, which speed up
encryption maths such as AES) that
the Pi 4's processor doesn't have. The Pi 5's processor does. **No setting,
older version or rebuild gets around a missing CPU feature**, so that single
error is the whole reason this project moved to a Pi 5.

---

## 5. Switching from the Pi 4 to the Pi 5

The swap was planned around one rule: **always keep a working device to go
back to.**

**Choices and why**

| Decision | Why |
|---|---|
| Flash a **new** microSD card and leave the Pi 4's card untouched | If anything about the Pi 5 disappoints, putting the old card back takes two minutes. Reusing the card is possible, but rollback then becomes a 40-minute reflash-and-restore. |
| Back up `~/np` **without** the Python environment | The environment gets rebuilt on the new board anyway. Leaving it out shrank the backup from 7.6 MB to 197 KB (before photos). |
| Check the backup actually contains `.env`, `.gdrive-token.json` and `.spotify-cache` | These are the sign-ins. Without them you start Spotify and Google setup from scratch. Listing the archive also proves it isn't truncated. |
| Keep a **second copy** of the backup if the old card will be reused | Once that card is wiped, the backup is the only copy. |
| **Shut the Pi 4 down** before starting the Pi 5 | Both use the hostname `nowplaying`. Two machines with the same name on one network fight, and you SSH into whichever answers first. |
| **64-bit** Raspberry Pi OS **Lite** | MediaPipe has no 32-bit ARM version at all. Lite, because there's no monitor. The cost: a few libraries (`libgles2`, `libegl1`, `opencv-data`) have to be installed by hand. |
| Fit the **active cooler** first | The Pi 5 slows itself down hard without a fan, and face tracking keeps the CPU busy. |
| Boot with **nothing wired**, then check the pins with `pinout` before wiring | Software and network first; the one step that can damage hardware comes last, with the power off. |
| Measure the SPI speed again | The Pi 4 managed 64 MHz; the Pi 5 was an unknown, and the camera view depends on that speed. |
| Run the program **by hand** before installing it as a service | A service hides errors in a log and keeps restarting. By hand, you see the error immediately. |

**Things learned on the way**

- **The pins didn't change.** The Pi 5's 40-pin header matches the Pi 4's, so
  the wiring carried over unchanged.
- **But the landmarks did.** The Ethernet and USB ports swapped sides. Go by
  the microSD end instead: pin 1 is at that end.
- **The GPIO pins are 3.3 V only.** Some Pi 5 guides claim they handle 5 V;
  they don't.
- **Restored secrets lose their protection.** After restoring the backup,
  `.spotify-cache` came back readable by everyone (permissions `644`). All
  three sign-in files need `chmod 600` again, which makes them readable by
  your user only.
- **Two copies of OpenCV.** OpenCV (the camera and image library) comes from
  the system's package manager. MediaPipe insists on installing its own copy
  through pip, which silently takes priority — and pip would fetch OpenCV
  5.0, which this code has never been tested with. Pinning
  `opencv-contrib-python<5` keeps it on 4.x. If the camera or hamsters break
  after a `pip install`, this is the first suspect.
- **Wifi settings that vanish.** On this OS version, the wifi network set up
  during flashing is regenerated at every boot, so edits to it quietly
  disappear. New networks have to be added as separate connections.
- **Never switch wifi over SSH.** The connection drops the moment the Pi
  leaves the old network, and the session freezes mid-prompt.

**After the swap:** MediaPipe ran at **13.4 fps**, and the crash was gone.

Every manual step from the swap was later folded into
[`setup.sh`](../setup.sh). A fresh install is now one command, and the manual
checklist was retired.

---

## 6. Rebuilding the expression filter on MediaPipe

This is where most of the design effort went. The approach throughout:
**measure, change one thing, measure again.**

**Calibrate on a real face.** The tester held four poses (neutral, smile,
mouth open, eyes shut) and the scores were recorded. Two surprises:

- **The first calibration was done in the wrong setup.** It used full-size
  still images; the real filter uses smaller video frames. Re-measured through
  the actual filter code (`tools/recal.py`), the numbers changed a lot.
- **"Open mouth looks like a smile" was mostly the tester grinning**, not a
  quirk of the model. But at very low resolution the smile score really does
  inflate, so the filter checks "mouth open" *before* "smile" as a safety
  net.

**Set thresholds low in the gap.** Calibration poses are exaggerated; real
expressions are subtler. So each "on" threshold sits well below the measured
pose, and the tests check the *weaker* 10% of samples still classify
correctly, not just the average.

**Signals that looked useful but weren't**

- "Pucker" scored 0.8 with a relaxed mouth, so it would fire constantly.
- "Brow raise" barely moved in any pose.
- "Squint" rose for every non-neutral pose, so it couldn't tell them apart.

**Head turning and looking down**, an idea from the
catherpiee/hammyhamster project. MediaPipe
already gives the head's rotation, so this needed no extra model. Two
details:

- hammyhamster's notes said the "looking down" direction had never been
  verified. `tools/headcheck.py` confirmed it on a real camera.
- Nobody faces the camera dead-on — you look at the *screen*, not the lens. So
  angles are measured relative to your own resting position, which slowly
  adapts. The threshold is high enough that glancing between screen and lens
  doesn't count.

**The flickering problem.** When someone laughs, their mouth opens and closes
rapidly, and the hamster switched 38 times in 30 seconds. Three fixes were
tried and scored against a recording of real use:

| Approach | Result |
|---|---|
| Minimum time in each mood (1 s) | Stopped flicker, but the "open mouth" hamster was often showing while the mouth was shut (24% of the time) |
| Majority vote over recent frames (hammyhamster's method) | Got stuck on "open" — wrong 84% of the time |
| **Block "happy" briefly after the mouth was open** | No back-and-forth at all, 90%+ correct |

The chosen fix has a real cost: some genuine smiles straight after a laugh are
missed (38%). There's no setting that gets zero flicker *and* zero missed
smiles — it's a trade-off, and the trade-off is documented.

**Fast in, slow out.** The "mouth open" score is the cleanest signal in the
system, so entering that mood is instant. Leaving it is the slowest
transition, which hides brief mouth-closes mid-laugh.

**What actually found the bug:** three plausible guesses about the mouth
detection were each disproved by one measurement. What solved it was
`tools/livestate.py`: running the real code in the real situation and
printing the numbers.

---

## 7. Stickers

- **Eye positions are placed by hand.** Three attempts to find the hamster's
  eyes automatically got 4–5 out of 9 right; they picked nostrils, mouths and
  steam clouds. By hand: 9 out of 9. `tools/sticker_sheet.py` draws a ring on
  every eye position so mistakes are easy to spot.
- **The variety bug.** Each face picked its sticker from a random number
  chosen once and never changed, so a session only ever showed about 4 of the
  stickers. The fix: pick fresh each time the mood changes, skipping the last
  three used.

---

## 8. Timelapse

- **Save frames first, make the video at the end.** A video file left open
  for 30 minutes is unplayable if anything interrupts it. Individual photos on
  disk survive a crash.
- **Video quality is worked out from the length.** The simple Drive upload
  accepts at most 5 MB, and file size = quality × length. So longer clips get
  a lower bitrate (bits per second of video — roughly, quality), and very low bitrates also drop to a smaller 480-line picture so they still look
  acceptable. A fixed minimum quality was a real bug the tests caught: a
  two-minute clip would have come out at 10.5 MB — over the limit, so the
  upload would fail only after all that recording.
- **Videos uploaded as photos.** The uploader labelled everything as a JPEG,
  so videos wouldn't play in Drive. The label now comes from the file
  extension.
- **Another font gap.** An arrow character showed as an empty box. There's now
  a test that checks the font actually contains every character the program
  draws.

---

## 9. Making it usable by other people

- **`setup.sh`** replaced the manual install checklist: it installs
  everything, checks its own work, and is safe to re-run.
- **Pinned versions** where it matters: `st7789==1.0.1` (the code works
  around that exact version's bug) and OpenCV below 5.
- **Tests that run without the hardware.** The screen, buttons, Spotify and
  MediaPipe are replaced with fakes. The fake screen keeps real pixels, so the
  tests check what was actually drawn. Every test runs in a throwaway home
  folder, so it can never touch real sign-ins.

---

## Lessons that kept coming back

1. **Read the library's source.** The blank screen, the font watermarks and
   the reset pin were all answered in minutes by reading code, after hours of
   guessing.
2. **Check the real output.** Compare pixels, not update counts; render the
   screen and look at it.
3. **Measure in the real setup.** The first face calibration was carefully
   done — in the wrong configuration.
4. **One measurement beats a plausible theory.** Three good-sounding
   explanations for the mouth problem were each wrong.
5. **Some problems are trade-offs, not bugs.** Write down what you gave up, so
   nobody "fixes" it back later.
