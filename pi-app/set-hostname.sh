#!/bin/bash
# Give the Pi the network name "console", so it's reachable as console.local
set -e
sudo raspi-config nonint do_hostname console
echo "Done. After a reboot the Pi is console.local (SSH: ssh pi@console.local)."
