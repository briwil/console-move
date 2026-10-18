#!/bin/bash
# Make the Pi start straight into Track8 instead of the desktop.
# Undo with: ./boot-to-desktop.sh
set -e
cd "$(dirname "$0")"
sudo cp track8.service /etc/systemd/system/track8.service
sudo systemctl daemon-reload
sudo systemctl enable track8.service
sudo systemctl set-default multi-user.target
echo "Done. Reboot (sudo reboot) and the Pi will start into Track8."
echo "SSH still works. To see the app's messages: journalctl -u track8 -f"
