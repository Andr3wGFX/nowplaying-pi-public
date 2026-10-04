# Pi 5 migration — notes and packaging findings

Follows on from `build-notes-pi4.md`. Covers everything after the Pi 4 build:
the hamster face filter, expression detection, the CPU wall that forced the Pi 5,
and the swap itself.

- Wiring diagram: [`wiring.png`](wiring.png) (identical on Pi 4 and Pi 5)
- The story and reasoning, in plain language: [`design-history.md`](design-history.md)

## Why the Pi 5 at all
MediaPipe **installs** fine on the Pi 4 and dies at native-library load:
`FATAL ERROR: This binary was compiled with aes enabled`. Cortex-A72 (BCM2711)
has no ARMv8 Crypto Extensions; Cortex-A76 (BCM2712) does. **Not fixable in
software** — no flag, no older wheel, no rebuild. That is the whole reason for
the board swap.

Fallback in use on the Pi 4: OpenCV facemark LBF, 68 landmarks, 9.1 fps, three
expression states. **Blink detection is impossible with it** — measured on
the tester's own face, eyes CLOSED scored EAR 0.230 vs neutral 0.210, i.e. the eye
landmarks are hallucinated, not detected. Three states shipped, not four.

## Face filter constants (measured, not guessed)
- `EYE_SEP_OF_W = 0.350`, `EYE_Y_OF_H = 0.399` — derived from the Haar box.
  Guessing 0.45 made every sticker **29% too big**.
- **No `equalizeHist`** before detection: measured across real photos it *lost*
  faces (5 found vs 7 raw).
- Haar smile cascade **rejected**: 2/7 on nearly-all-smiling faces, one of those
  a false positive. Coin flip, not a detector.
- Tracking: greedy one-to-one match, `max_miss=2`, `confirm=2`, `match_radius=1.1`,
  `merge_dist=0.7`. Settles at 3 hamsters on a 3-face photo, clears in ~0.4 s,
  0 false positives on cactus/sunset frames.

## Packaging facts, verified against PyPI 2026-09-14
- **OpenCV on the Pi comes from apt (`python3-opencv`), never pip.** Debian's
  build drops `cv2.data`, which is why `opencv-data` is a separate install and
  why `hamster.find_cascade()` has `/usr/share/opencv4/haarcascades` fallbacks.
  Debian's build *does* carry `cv2.face`, which facemark needs.
- **`mediapipe` 1.0.1 hard-depends on `opencv-contrib-python`.** Installing it
  therefore drops a pip OpenCV into the venv, which **shadows the apt one**.
  Current release of that package is **5.0** — a major version the filter code has
  never run against. Install as `pip install mediapipe "opencv-contrib-python<5"`.
- MediaPipe's aarch64 wheel is tagged `py3-none`, so the Python version is not an
  obstacle (Trixie/3.13 is fine). No source build, no long compile.
- `st7789` 1.0.1 is still the newest release; pin it, since the code hand-works
  around its RST bug.
- `pillow-heif` is **not** needed on the Pi — `convert_photos.py` never registers
  the HEIF opener, so it does nothing there.
- Venv must be created `--system-site-packages`, **over** the restored `~/np`
  (tested: creating a venv on a folder full of files destroys none of them).
- `.spotify-cache` restores from tar as **644**; chmod all three credential files,
  not two.

## Raspberry Pi OS Lite gaps
Lite is the right image (headless appliance, 64-bit mandatory for MediaPipe), but
it ships less than the desktop image. Things that must be installed by hand:
`opencv-data`, `libgles2`, `libegl1`, and possibly `python3-gpiozero` — which is
what provides the `pinout` command used to verify the header before wiring.

## Pi 5 hardware notes
- 40-pin header is pin-compatible with the Pi 4: same positions, same BCM numbers.
  **Wiring does not change.**
- **Ethernet and USB swapped sides on the Pi 5** — orient by the microSD end, not
  the ports. Pin 1 is nearest the microSD slot.
- GPIO is 3.3 V and **not** 5 V tolerant; some Pi 5 guides claim otherwise.
- `st7789` 1.0.1 → `gpiodevice`, whose chip-label match is the regex `pinctrl-*`,
  which matches the Pi 5's `pinctrl-rp1`. No code change needed.
- **Unverified:** the SPI clock ceiling on Pi 5. Pi 4 measured clean at 64 MHz.
  Run `tools/cameracheck.py` on your own board to measure it.

## MediaPipe on the Pi 5 — it works, and here are the numbers

The first calibration script (four held poses: neutral, smile, mouth open,
eyes shut) completed all four phases at **13.4 fps** (detection every frame,
640×480). The `aes` fatal error is gone: BCM2712 has the crypto extensions.

The tester's measured blendshape averages:

| blendshape | NEUTRAL | SMILE | MOUTH | EYES |
|---|---|---|---|---|
| mouthSmileLeft | 0.000 | 0.486 | **0.739** | 0.028 |
| mouthSmileRight | 0.000 | 0.428 | 0.668 | 0.023 |
| jawOpen | 0.001 | 0.000 | **0.326** | 0.008 |
| eyeBlinkLeft | 0.318 | 0.354 | 0.368 | **0.749** |
| eyeBlinkRight | 0.305 | 0.291 | 0.254 | **0.711** |
| mouthPucker | **0.798** | 0.075 | 0.018 | 0.343 |
| browInnerUp | 0.037 | 0.029 | 0.036 | 0.034 |
| eyeSquintLeft | 0.281 | 0.477 | 0.529 | 0.510 |

**THE TRAP — read this before touching the thresholds.** `mouthSmile` is
*higher* with the mouth open (0.70) than during an actual smile (0.46):
opening wide drags the mouth corners back. So `jawOpen` must be tested FIRST
and must also gate the smile test. Testing smile first makes every open-mouth
face come out "happy".

**Blink is real now.** 0.31 open → 0.73 shut, a 0.42 gap. The LBF model scored
eyes-closed 0.230 vs 0.210 neutral, i.e. backwards. Note the 0.31 baseline is
this face's natural aperture, so thresholds are relative to them, not to zero.

**Rejected signals:** `mouthPucker` reads **0.798 at rest** — their relaxed mouth
looks puckered, so a naive pucker state would fire whenever they sat still.
`browInnerUp` is flat (0.029–0.037) across all four phases: no calibration
phase raised their brows, so it carries no information. `eyeSquintLeft` rises for
all three non-neutral phases and separates nothing.

### Recalibrated — the first calibration was measured in the wrong configuration

That first calibration ran at full resolution in IMAGE mode. The filter runs VIDEO mode
on a downscaled frame, and that changes the numbers materially. `recal.py`
re-measured through the shipping code path:

| 480 px, mean | NEUTRAL | SMILE | OPEN | BLINK |
|---|---|---|---|---|
| jawOpen | 0.001 | 0.000 | **0.513** | 0.025 |
| mean mouthSmile | 0.001 | **0.394** | 0.015 | 0.000 |
| mean eyeBlink | 0.324 | 0.304 | 0.242 | **0.689** |

Separation: jaw +0.49, smile +0.38, blink +0.37. All three are real gaps.

**Correction to the earlier note.** "Opening your mouth reads as a smile" was
NOT a property of the tester's face. Measured with a blank open mouth at 480 px,
smile reads **0.015**, not 0.70. The 0.739 in the first calibration was mostly
them grinning through the OPEN phase (that phase followed SMILE immediately and
the instruction didn't say not to). A *separate* real effect does exist:
a follow-up check held behaviour constant across sizes and found smile inflating to
0.72 at 320 px versus 0.01 at 640 px — a low-resolution artifact. jaw-first
ordering is kept as cheap insurance against that, not as a fix for anatomy.

**max_side = 480, not 320.** Measured on the Pi 5, VIDEO mode runs 20.7 / 20.0
/ 19.9 fps at 240 / 320 / 480 — flat, because it is pegged at the C270's frame
rate, not the model's. 480 also found more faces (85 vs 80). The downscale was
buying nothing. 640 is equally affordable but 480 separates jaw better and
leaves more CPU for the display.

**Eye separation measured: 0.337 of box width (sd 0.003, n=40).** The Haar-era
constant of 0.350 was ~4% too big. Now moot — irises are measured directly.

### Shipped thresholds (hamster.py)
```
OPEN_ON,  OPEN_OFF  = 0.15, 0.08     # jawOpen, tested first
SMILE_ON, SMILE_OFF = 0.18, 0.09     # mean mouthSmile, only if jaw is low
BLINK_ON, BLINK_OFF = 0.60, 0.50     # mean eyeBlink
SMOOTH = 0.45        BLINK_SMOOTH = 0.60
```
ON values sit deliberately LOW in each gap, not at the midpoint: calibration
poses are exaggerated and real ones are not. SMILE_ON is about half the
measured grin (p10 0.32) yet still 12x the highest non-smiling reading.
Tests assert the **p10** of each pose classifies correctly, not just the mean.

Blink keeps heavier smoothing: simulated against the real numbers, one or two
samples cannot cross the threshold and three (~0.5 s held) latches, so natural
blinks are ignored.

### Reusing catherpiee/hammyhamster

That app picks a hamster by **gesture** (hands + pose + face), not expression,
which is why the sticker filenames are what they are: bicep, nerd, think,
thumbs down, cross arms, one finger mouth. Three things worth taking:

**1. Head yaw and pitch, free.** It reads them off
`facial_transformation_matrixes` -- a 4x4 rotation matrix from the SAME
FaceLandmarker already running. Needs only
`output_facial_transformation_matrixes=True` (confirmed present in mediapipe
1.0.1). Two more expressions, no second model, no second pass. hammyhamster's README warns
the pitch sign was never verified live, so `headcheck.py` verifies it on
the tester's own camera before it goes in the filter.

**1a. Verified on the tester's face** (`headcheck.py`), degrees:

| pose | yaw | pitch |
|---|---|---|
| straight ahead | 2.6 | **-6.6** |
| turn left / right | +46.0 / -49.1 | -5.6 / -7.5 |
| look down | -4.8 | **+16.0** |
| look up | -1.9 | -30.5 |

Pitch sign is correct as hammyhamster's code has it (down positive) — the thing hammyhamster's README
said was unverified.

**Neither angle rests at zero.** Those offsets are the angle between camera and
face, and in the photo booth the tester looks at the PANEL, not the lens — a
different offset again, unknown in advance. So thresholds are deviations from a
**moving baseline** that freezes while a pose is held (otherwise it drifts to
follow the turn it is meant to detect). `testhead.py` drives a face resting 30°
off-axis and checks all three properties. `TURN_ON = 25°` is deliberately over
half the measured turn: a panel-to-lens glance is 10-20° and must not count.

**Eye-separation compensation for yaw: considered and rejected.** Dividing
measured separation by cos(yaw) would "correct" the foreshortening — but a
turned face genuinely is narrower on screen, and the sticker should shrink with
it. The measured separation is already right.

`sideyee.jpg` is drawn in PROFILE, one visible eye, so it has no real eye pair.
Its coordinates are synthetic: a 132 px span (the median sep/width ratio of the
other fifteen, 0.180 × 735) centred on the visible eye and nose.

**2. Its vote scheme -- measured and rejected.** It stabilises with a majority
vote (7 of the last 12 frames). Replayed against the tester's real trace it is
worse than a refractory: at a 1.5 s window it scores 95% hit but **84% false**,
i.e. it latches `open` and stays there. Rejected on the numbers, not on taste.

**3. Its collision-handling framing -- taken.** Its code documents gesture
collisions explicitly (bicep swallowing thumbs-up; whole-hand centroid vs
fingertip for mouth distance) and fixes them by ordering, not by tuning
thresholds. Re-reading the open-vs-happy fight that way is what produced
HAPPY_REFRACTORY instead of another threshold tweak.

catherpiee's gesture map vs this repo's tags, for reference when the hand model goes in:
two_hands/bicep/shy/cross_arms/glasses/fist_by_head/sad/nerd/finger_mouth/hug/
default/thinking/thumbs_up/thumbs_down, plus `side_eye` -> `sideyee.jpg`, which
was missing from this repo's stickers folder and has now been copied across.
Gesture detection itself needs hand + pose landmarkers -- two more models on a
loop already running at 15.2 fps, so it needs measuring before it is promised.

### Two bugs found in live use

**1. Sticker variety.** `_free_sticker` derived the choice from one random seed
drawn per face and never redrawn: `free[int(seed * 9973) % len(free)]`. Intended
to be *stable*; actually *deterministic*. With pools of open 3 / happy 4 /
neutral 8, one seed means one fixed open hamster and one fixed happy hamster for
the whole session, plus two neutrals — about **4 distinct of 15 per session**,
and the set only changes when the filter is toggled off and on (which clears
tracks). Simulated: 5.3 distinct after one toggle, 8.6 after two. The tester
reported seeing "around 7". Fixed by drawing fresh per mood change minus a
3-deep memory: 12.5 distinct after one toggle, 15.0 after five.

**2. State thrashing, misread as "mouth open doesn't trigger".** It triggered
fine — live trace shows jawOpen peaking at **0.765** and clearing its threshold
in 58% of samples. The real fault: **38 state changes in 30 seconds (76 hamster
swaps/min)**. Hysteresis protects a single signal crossing one threshold; it
does nothing when two states take turns winning. Smiling with the mouth open
does exactly that — jaw dips under OPEN_OFF, `happy` grabs the state, jaw rises,
`open` takes it back.

First fix was `MIN_DWELL = 1.0` s and it was **wrong**, because
"state changes per minute" was the wrong metric — the tester was opening and
closing their mouth about once a second, so a correct filter *should* change
state 40-50 times a minute. Scored properly (flicker = visits under 0.4 s,
churn = open→happy→open, hit = `open` shown when jaw > 0.25, false = `open`
shown when jaw < 0.05):

| | flicker | churn | hit | false | smiles missed |
|---|---|---|---|---|---|
| nothing | 7 | 4 | 100% | 0% | 12% |
| MIN_DWELL 1.0s | 0 | 2 | 68% | **24%** | — |
| hammyhamster vote, 1.5 s window | 0 | — | 95% | **84%** | — |
| refractory 1.0s + dwell 0.4s | 1 | **0** | 93% | 2% | **50%** |
| **refractory 0.7s + dwell 0.4s** | 1 | **0** | 90% | 2% | 38% |

Confirmed live, not just replayed: the second session scored 0 churn, 1
flicker, 95% hit, and state changes fell from 39 to 20. The replay agrees with
the live states in 110/111 samples, so the simulator being tuned against is
faithful.

**The refractory has a real cost, found only by running it live.** It suppresses
genuine smiles that follow an open mouth — which is most smiles, because people
laugh. 1.0 s missed 50% of broad smiles; 0.7 s is the shortest value that still
kills the churn completely, at 38%. There is no setting with zero churn AND zero
missed smiles. It is a trade, not a bug.

Dwell alone bought stability by holding `open` through a quarter of the frames
where the mouth was shut. `HAPPY_REFRACTORY` targets the actual conflict —
`happy` is refused for a second after the mouth was last open, on the grounds
that you were laughing — and costs nothing elsewhere. Raising thresholds did
not help at all (0.25/0.12 was slightly worse).

**Method note.** Three consecutive hypotheses about the mouth were wrong
(threshold too high; resolution starving the signal; chin cropped out of frame).
Each was plausible and each was refuted by one measurement. The thing that
actually found it was instrumenting the real code path in the real situation and
printing the numbers — `livestate.py`.

### Sticker set: all six moods covered

Nine more images added. Eye coordinates were found by hand off a coordinate
grid after three automatic attempts failed in instructive ways: pass 1 scored
symmetry about the IMAGE centre (broken by letterbox bars and props like the
magnifying glass), pass 2 took the largest connected blob as the face (on an
open-mouthed hamster that is the black mouth), pass 3 fixed both and still put
the dots on nostrils and steam clouds. 4/9, 5/9, then 5/9 again. Hand-placed,
verified visually: 9/9.

Pools at the time: neutral 8, open 6, happy 6, blink 2, down 2, turn 1
(three images were later removed for copyright reasons; the public set is
neutral 7, open 5, happy 5, blink 2, down 2, turn 1). `blink` finally
has stickers of its own -- `smug squint.png`, plus `cross arms .jpg` retagged
from neutral because its X eyes read as eyes-shut.

### Entering `open` is fast, leaving it is slow

A flat `MIN_DWELL` punished the cleanest signal in the system. jawOpen separates
0.001 resting from 0.513 open -- by far the best-separated measurement here --
and making it queue behind a timer is what the tester reported as "the mouth switch
is having difficulties". Counting samples where jaw > 0.30 but the open hamster
was NOT showing, across both live sessions:

| | late (A/B) | hit (A/B) | flicker |
|---|---|---|---|
| flat 0.4 s dwell | 5 / 4 | 88% / 90% | 1 / 1 |
| confident opens waived | 0 / 0 | 96% / 100% | 6 / 5 |
| **+ slower exit from open (0.6 s)** | **0 / 0** | **96% / 100%** | 5 / 4 |

The flicker the waiver introduces is a brief `neutral` between two opens — a
momentary mouth-close mid-laugh. Making the EXIT from open the slowest
transition in the system removes those without delaying onset.

### Filter rewrite
`hamster.py` is now MediaPipe-only; the older Haar + LBF version was retired. One model does detection AND expression.
Eye separation is measured from the iris landmarks (478-point model) instead of
inferred as `0.350 × box width`. `classify()` is a pure function so the state
machine is testable without a camera — see `testmp.py` (their real numbers) and
`testgeom.py` (fake-MediaPipe geometry, verified by pixel).

Verified against real mediapipe **1.0.1** on a development machine:
`FaceLandmarkerOptions` kwargs, `RunningMode.VIDEO`, `detect_for_video`,
`close`. The automated tests use a fake MediaPipe and no model file, so live
inference is only ever tested on the Pi — that is what `checkmp.py` is for.

The `TypeError` at exit is MediaPipe's destructor running after interpreter
teardown. Cosmetic; fixed by calling `close()` explicitly.

## Timelapse mode

Hold the shutter in camera mode to start; middle press stops it and leaves you
in camera mode; middle again returns to Spotify. One frame every 4 s for up to
30 minutes = 450 frames = 15 s at 30 fps. Hamsters are baked in if the filter
is on. `ffmpeg` required (`sudo apt install -y ffmpeg`) — the desktop image
ships it, Lite does not.

**Frames go to disk first, encoded only at the end.** A VideoWriter held open
for thirty minutes leaves an unplayable file if anything interrupts it; JPEGs
on disk survive a crash and can be re-encoded by hand.

**Bitrate is derived from duration, not fixed.** Drive's multipart upload is
capped at **5 MB** (checked against Google's docs). size = bitrate × duration,
so fitting a cap is arithmetic: a longer clip must get a lower bitrate. Below
~1.2 Mbps the frame is scaled to 480p instead, which is what makes a low
bitrate look acceptable. A quality floor of 700 kbps was a real bug the tests
caught — two minutes of video would have encoded to 10.5 MB and failed to
upload *after the user waited an hour for it*.

**The uploader called everything `image/jpeg`.** An mp4 sent with that type
lands in Drive as a file that will not preview or play. Now derived from the
suffix.

Both buttons that do two jobs now act on RELEASE with a `*_held` flag — the
same pattern the middle button has used since the Pi 4, and for the same
reason: otherwise a long hold also fires the short-press action on the way in.

A red recording dot sits top right while capturing, and is deliberately NOT
drawn during the render — by then the capture has stopped, and a dot still
burning would say otherwise.

**Third font-glyph bug on this project.** The progress line used `\u2192` and
Quicksand drew a tofu box; only rendering the screen and looking at it caught
it. Mochi Boom's watermarked digits, Mochi's missing accents, now this. There
is now a test that asks the font whether each character it is asked to draw
actually exists, instead of assuming.

Measured: 23 frames captured and encoded to valid h264 in 1.5 s of wall clock
in the harness, so a 4-second interval is not remotely tight on the Pi 5.

## Networking gotcha: Raspberry Pi OS Trixie provisions wifi via netplan

Confirmed Debian 13 (trixie), i.e. Raspberry Pi OS Lite 64-bit as the README
specifies. But the Imager-provisioned network settings now come through
**netplan**, not plain NetworkManager, and that changes how wifi is edited:

```
netplan-wlan0-<ssid>  ->  /run/NetworkManager/system-connections/...   <- tmpfs!
netplan-eth0       ->  /run/NetworkManager/system-connections/...   <- tmpfs!
<hand-made>        ->  /etc/NetworkManager/system-connections/...   <- persists
```

`/run` is wiped on every boot and regenerated from `/etc/netplan/90-NM-*.yaml`.
So `nmcli connection modify netplan-wlan0-<ssid> ...` appears to work, survives all
day, and **silently reverts on reboot**. Anything durable must either edit the
netplan YAML or live in a separate `/etc/NetworkManager` profile.

Adding a phone hotspot as a fallback avoids the problem entirely: leave the
netplan-managed home profile at its default priority of 0 and give the hotspot
`connection.autoconnect-priority -10`. Higher wins, negatives are allowed, so
home is preferred whenever in range and nothing netplan owns has to be touched.

**Never switch wifi interactively over SSH.** The session dies the instant the
Pi leaves the old network, so nmtui's password prompt ends up on a terminal
that no longer exists — the screen looks frozen and keystrokes land in the
local shell instead. Configure without activating (`autoconnect no`, set the
secret, then set priority) so the session survives and the Pi roams on its own.

Hotspot PSKs land in plaintext in `/etc/NetworkManager/system-connections/*` and
`/etc/netplan/*.yaml`; both were verified as mode 600, root-owned.

## Status at the time of the swap
The Pi 4 was running music screen, slideshow, clock/weather, camera mode, Drive
upload, and the hamster filter with three expression states. In this build the Pi 5
reused the Pi 4's microSD card (a fresh card is the safer choice), so the backup tarball was the only copy of the
credentials during the swap — make a second off-machine copy before you wipe
anything.

Done since the swap: the expression backend now runs on MediaPipe blendshapes
(see "Face filter constants" and the sections after it).
