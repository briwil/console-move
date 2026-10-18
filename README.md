# Console

A DIY 8-track recorder and arranger with tape-style recording. It runs on a Raspberry Pi 5 with a 7.9" 1280×400
screen and a custom key-and-knob control board.

## What's in this repo

| Folder | What it holds | Status |
|---|---|---|
| `pi-app/` | The recorder app that runs on the Pi (audio engine and screen UI) | Screen and controls working, no audio yet |
| `firmware/` | Code for the PGA2350 on the control board (reads keys and knobs, sends them to the Pi over USB) | Not started |
| `hardware/` | KiCad project for the control board, plus the files sent to JLCPCB | Ordered, rev 0.1 |

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

The screen can use any font listed in `pi-app/fonts/fonts.json`: Inter Tight,
IBM Plex Mono, IBM Plex Sans, Space Grotesk, Archivo Narrow, Barlow Condensed,
JetBrains Mono, Space Mono, and the pixel fonts Silkscreen, VT323 and
DotGothic16. All are under the SIL Open Font License (see `pi-app/fonts/OFL-*.txt`).

To add a font, put its `.ttf` files in `pi-app/fonts/`, add an entry to
`fonts.json` (an id, its name and one file per weight), and add the same entry
to the `FONTS` list near the top of the designer's script.
