#!/bin/bash
# Start Console on the Pi's screen.
# - With the desktop running (for example when you run this over SSH), it opens full screen on the desktop.
# - Without a desktop (boot-to-app), it draws straight to the screen.
cd "$(dirname "$0")"
RUNDIR=/run/user/$(id -u)
if [ -S "$RUNDIR/wayland-0" ]; then
  export XDG_RUNTIME_DIR="$RUNDIR" WAYLAND_DISPLAY=wayland-0 DISPLAY=:0
  export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-wayland,x11}"
else
  export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-kmsdrm}"
fi
exec python3 console.py "$@"
