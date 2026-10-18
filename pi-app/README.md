# Pi app

The recorder that runs on the Raspberry Pi. **Version 0.3** records real audio.

- An OP-1 style tape: the playhead stays in the middle and the tape moves past
  it, with bar, beat and grid lines and bar numbers.
- Records from a USB audio device. An OP-XY in its 8-channel USB mode records
  all 8 tracks at once (input 1 to track 1, and so on). A stereo device, like a
  UCA202, records its inputs mixed together onto the armed track. Press I to
  switch between the two.
- Plays the tape back out of the same device (on the OP-XY, through its
  headphone jack).
- Saves the song when you stop, to `~/console-data/projects/Song 1/`
  (`track1.wav`…`track8.wav`, 24-bit), and loads it again at start-up.
- E exports stems (every track with audio, all the same length so they line
  up in a DAW) plus a stereo mix to `~/console-data/exports/`. Grab them from the
  file page at console.local.

Tracks are mono, the tape is 64 bars at 120 BPM (about 2 minutes), and the
OP-XY runs at 44.1 kHz. Without an audio device the app still runs and says
NO AUDIO DEVICE; plug one in and it connects within a couple of seconds.
`run.sh --demo` shows made-up waveforms instead.

## Recording timing

Recordings are shifted earlier by the audio delay (about 100 ms by default) so
overdubs line up with what you heard. If they land early or late, put a
different value in `~/console-data/settings.json`, for example
`{"latency_frames": 4000}` (44100 frames is one second), and restart the app.
The same file can pick a device by name: `{"device": "UCA202"}`.

## First-time setup

On the Pi (over SSH is fine):

```
cd ~/console && git pull
pi-app/setup.sh
```

## Running it

```
~/console/pi-app/run.sh
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
| I | Input: all inputs to tracks 1–8, or inputs mixed onto the armed track |
| E | Export stems and a stereo mix |
| Q | Quit (ignored when it starts at boot) |

## Starting straight into the app at boot

```
~/console/pi-app/boot-to-app.sh
sudo reboot
```

The Pi then skips the desktop and opens Console. SSH still works. To go back to
the desktop:

```
~/console/pi-app/boot-to-desktop.sh
sudo reboot
```

When it starts at boot, Q does nothing, so the screen never drops to a bare
text console, and if the app ever crashes it restarts by itself. Over SSH:

- `sudo systemctl stop console` stops it (then you can run it by hand with `run.sh`)
- `sudo systemctl start console` starts it again
- `journalctl -u console -f` shows its messages

## Start-up screen

```
~/console/pi-app/splash-setup.sh
~/console/pi-app/boot-to-app.sh
sudo reboot
```

The Pi shows the Console logo while it starts, with no text, and the logo stays
up until the app takes over. `splash-remove.sh` brings back the normal
Raspberry Pi start-up screen and messages, which helps if the Pi ever has
trouble starting.

To hide the messages without the logo (a black screen instead), use
`quiet-boot.sh`, and `loud-boot.sh` to undo it.

## File page (console.local)

```
~/console/pi-app/set-hostname.sh
~/console/pi-app/web-setup.sh
sudo reboot
```

Then open **http://console.local** in a browser on the same Wi-Fi. It shows the
console's storage (`~/console-data`, with Projects, Samples and Exports): you can
download files or whole folders as a zip, play audio, upload by dragging files
onto the page, make folders and delete things. Anyone on your Wi-Fi can open
it, so it has no password.

`sudo systemctl stop console-web` turns the page off and
`sudo systemctl disable console-web` keeps it off after a reboot.

If `console.local` doesn't open (some Windows PCs and Android phones don't
support `.local` names), use the Pi's address instead, such as
`http://192.168.86.54`.

## If the picture is upside down

Without the desktop, the app turns the picture itself, by 270° by default.
If it's upside down, change the line `ExecStart=...console.py` in
`console.service` to end in `console.py --rotate 90`, then run
`./boot-to-app.sh` again.

## Files

- `console.py` is the app: the screen, the keys and the transport (play,
  record, position).
- `audio.py` is the audio engine: finding the device, recording, playback, saving and export.
- `tape.py` is the tape: the tracks over time, the grid and zoom, and drawing the lanes, waveforms and ruler.
- `ui.py` reads and draws layouts made with the Screen Designer
  (`tools/screen-designer.html`).
- `layouts/main.ui` is the main screen layout. Paste new designer code here.
- `fonts/` holds the screen fonts, listed in `fonts/fonts.json` (SIL Open Font License).
- `console.service` is the boot-to-app service used by `boot-to-app.sh`.
- `web/` is the file page (`server.py` and `index.html`), installed by `web-setup.sh` as `console-web.service`.
- `set-hostname.sh` names the Pi `console`.
- `splash/` and `splash-setup.sh` are the start-up logo; `quiet-boot.sh` and `loud-boot.sh` hide or show the boot messages.

The layout names the app relies on: `track1_lane`…`track8_lane`, `track1_wave`…`track8_wave` (the app draws the grid and the audio into these), `trackN_meter`, `ruler`, `playhead`, `clock`, `grid`, `status`, `rec_dot` and `rec_outline`.
