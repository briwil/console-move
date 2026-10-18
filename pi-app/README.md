# Pi app

The recorder that runs on the Raspberry Pi. **Version 0.2** shows the screen
layout full screen with an OP-1 style tape: the playhead stays in the middle
and the tape moves past it, with bar, beat and grid lines and bar numbers.
There's no audio yet: the waveforms are made up, and recording writes new
made-up audio onto the armed track.

## First-time setup

On the Pi (over SSH is fine):

```
cd ~/track8 && git pull
pi-app/setup.sh
```

## Running it

```
~/track8/pi-app/run.sh
```

When you run it over SSH while the desktop is up, the app opens full screen on
the Pi's display. Keys you type in the SSH window control it, and so does a
keyboard plugged into the Pi:

| Key | Does |
|---|---|
| 1–8 | Arm that track for recording |
| Space | Play / stop |
| R | Record on / off (also starts playing) |
| ← / → | Move back / forward one grid step |
| [ / ] or Shift+← / → | Move back / forward one bar |
| G | Change the grid: 1/4, 1/8, 1/16, 1/32 |
| + / − | Zoom in / out (16, 8, 4, 2 or 1 bars across the screen) |
| Q | Quit (ignored when it starts at boot) |

## Starting straight into the app at boot

```
~/track8/pi-app/boot-to-app.sh
sudo reboot
```

The Pi then skips the desktop and opens Track8. SSH still works. To go back to
the desktop:

```
~/track8/pi-app/boot-to-desktop.sh
sudo reboot
```

When it starts at boot, Q does nothing, so the screen never drops to a bare
text console, and if the app ever crashes it restarts by itself. Over SSH:

- `sudo systemctl stop track8` stops it (then you can run it by hand with `run.sh`)
- `sudo systemctl start track8` starts it again
- `journalctl -u track8 -f` shows its messages

## Start-up screen

```
~/track8/pi-app/splash-setup.sh
~/track8/pi-app/boot-to-app.sh
sudo reboot
```

The Pi shows the Track8 logo while it starts, with no text, and the logo stays
up until the app takes over. `splash-remove.sh` brings back the normal
Raspberry Pi start-up screen and messages, which helps if the Pi ever has
trouble starting.

To hide the messages without the logo (a black screen instead), use
`quiet-boot.sh`, and `loud-boot.sh` to undo it.

## If the picture is upside down

Without the desktop, the app turns the picture itself, by 270° by default.
If it's upside down, change the line `ExecStart=...track8.py` in
`track8.service` to end in `track8.py --rotate 90`, then run
`./boot-to-app.sh` again.

## Files

- `track8.py` is the app: the screen, the keys and the transport (play,
  record, position).
- `tape.py` is the tape: the tracks over time, the grid and zoom, and drawing the lanes, waveforms and ruler.
- `ui.py` reads and draws layouts made with the Screen Designer
  (`tools/screen-designer.html`).
- `layouts/main.ui` is the main screen layout. Paste new designer code here.
- `fonts/` holds Inter Tight and IBM Plex Mono (SIL Open Font License).
- `track8.service` is the boot-to-app service used by `boot-to-app.sh`.
- `splash/` and `splash-setup.sh` are the start-up logo; `quiet-boot.sh` and `loud-boot.sh` hide or show the boot messages.

The layout names the app relies on: `track1_lane`…`track8_lane`, `track1_wave`…`track8_wave` (the app draws the grid and the audio into these), `trackN_meter`, `ruler`, `playhead`, `clock`, `grid`, `status`, `rec_dot` and `rec_outline`.
