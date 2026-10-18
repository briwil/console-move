#!/bin/bash
# Go back to starting the normal desktop at boot.
set -e
sudo systemctl disable --now track8.service || true
sudo systemctl set-default graphical.target
echo "Done. Reboot (sudo reboot) to get the desktop back."
