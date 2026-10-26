# Console

A DIY 8-track recorder and arranger with tape-style recording. It runs on a Raspberry Pi 5 with a 7.9" 1280×400
screen and a custom key-and-knob control board.

**New here? Read [PROJECT-NOTES.md](PROJECT-NOTES.md) first.** It explains how everything fits together, what's
been decided, how the Pi is set up and what's still open. The controls are in [pi-app/CONTROLS.md](pi-app/CONTROLS.md).

## What's in this repo

| Folder | What it holds | Status |
|---|---|---|
| `pi-app/` | The recorder app that runs on the Pi (audio engine, drum synth, sequencer, screen UI) | Working: recording, editing, drums, sequencer, Link |
| `firmware/` | Code for the PGA2350 on the control board (reads keys and knobs, sends them to the Pi over USB) | Working (CircuitPython) |
| `hardware/` | KiCad project for the control board, plus the files sent to JLCPCB | Built, rev 0.1 |

## Hardware

- Raspberry Pi 5 (8 GB), with the official 27 W USB-C power supply
- Waveshare 7.9" HDMI screen (400×1280 panel, rotated 270° for landscape)
- Control board: 24 Kailh Choc V1 keys (hotswap), 11 EC11 encoders and a
  Pimoroni PGA2350 (RP2350B), connected to the Pi over USB-C
- Audio in: any USB audio device, such as an OP-XY (multichannel) or a
  stereo line-in interface like the Behringer UCA202

## Getting the code onto the Pi

The repo is private, so the Pi signs in to GitHub once with GitHub's own tool:

```
sudo apt install gh
gh auth login
gh repo clone briwil/console ~/console
```

After that, to get the latest changes:

```
cd ~/console && git pull
```

## Pi setup notes

- **Screen rotation:** `~/.config/labwc/autostart` contains
  `(sleep 3; wlr-randr --output HDMI-A-1 --transform 270) &`

## Tools

- `tools/screen-designer.html` is a visual designer for the 1280×400 screen.
  Open it in a browser, lay out the screen and copy the generated `ui.*` code.

## Fonts

The screen can use any font listed in `pi-app/fonts/fonts.json`, and the theme page
(console.local/theme) offers all of them. There are about 35, all free from Google Fonts under
the SIL Open Font License (see `pi-app/fonts/OFL-*.txt`). They include:
- Outfit, Roboto Condensed, Inter, Geist, DM Sans, Manrope and Archivo;
- Space Grotesk and Sora;
- mono fonts: Geist Mono, JetBrains Mono, DM Mono, Azeret, Space Mono, Red Hat Mono and IBM Plex Mono;
- techy fonts: Michroma, Orbitron, Chakra Petch, Oxanium and Rajdhani;
- display fonts: Unbounded, Syne, Bebas Neue and Big Shoulders;
- dot and pixel fonts: Doto, Tiny5, Jersey 10, Sixtyfour, Silkscreen, VT323 and DotGothic16.

To add a font, put its `.ttf` files in `pi-app/fonts/` (one per weight) and add an entry to
`fonts.json` (an id, its name and one file per weight). The new fonts are trimmed to Western
characters to keep them small.
