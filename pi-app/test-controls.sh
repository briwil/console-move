#!/bin/bash
# Control board test: shows every key, knob turn and knob push on the Pi's screen.
# Run it from anywhere: ~/console/pi-app/test-controls.sh   (Q quits)
cd "$(dirname "$0")"
RUNDIR=/run/user/$(id -u)
if [ -S "$RUNDIR/wayland-0" ]; then
  export XDG_RUNTIME_DIR="$RUNDIR" WAYLAND_DISPLAY=wayland-0 DISPLAY=:0
  export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-wayland,x11}"
else
  export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-kmsdrm}"
fi

# The boot copy of Console has the screen and the board: pause it while the test runs.
RESTART=0
if systemctl is-active --quiet console 2>/dev/null; then
  echo "Pausing the copy of Console that started at boot (it may ask for your password)..."
  sudo systemctl stop console && RESTART=1
fi
python3 controltest.py "$@"
if [ "$RESTART" = 1 ]; then
  echo "Starting Console again..."
  sudo systemctl start console
fi
