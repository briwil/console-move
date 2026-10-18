# Pi app

The recorder that runs on the Raspberry Pi. **Version 0.1** shows the screen
layout full screen and responds to keys. There's no audio yet: play, record
and the track keys only change what's on screen.

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
| ← / → | Move back / forward one bar |
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

## If the picture is upside down

Without the desktop, the app turns the picture itself, by 270° by default.
If it's upside down, change the line `ExecStart=...track8.py` in
`track8.service` to end in `track8.py --rotate 90`, then run
`./boot-to-app.sh` again.

## Files

- `track8.py` is the app: the screen, the keys and the transport (play,
  record, position).
- `ui.py` reads and draws layouts made with the Screen Designer
  (`tools/screen-designer.html`).
- `layouts/main.ui` is the main screen layout. Paste new designer code here.
- `fonts/` holds Inter Tight and IBM Plex Mono (SIL Open Font License).
- `track8.service` is the boot-to-app service used by `boot-to-app.sh`.
