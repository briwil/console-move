# Track8

A DIY 8-track recorder and arranger, inspired by the Thingstone Track8, with
OP-1-style tape features. It runs on a Raspberry Pi 5 with a 7.9" 1280×400
screen and a custom key-and-knob control board.

## What's in this repo

| Folder | What it holds | Status |
|---|---|---|
| `pi-app/` | The recorder app that runs on the Pi (audio engine and screen UI) | Not started |
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

The first time, on the Pi:

```
git clone https://github.com/briwil/track8.git ~/track8
```

After that, to get the latest changes:

```
cd ~/track8 && git pull
```

The repo is private, so `git clone` asks for your GitHub username and a
personal access token in place of your password.

## Pi setup notes

- **Screen rotation:** `~/.config/labwc/autostart` contains
  `(sleep 3; wlr-randr --output HDMI-A-1 --transform 270) &`
