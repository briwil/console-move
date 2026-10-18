#!/bin/bash
# Make the Pi start straight into Console instead of the desktop.
# Undo with: ./boot-to-desktop.sh
set -e
cd "$(dirname "$0")"
sudo cp console.service /etc/systemd/system/console.service
sudo systemctl daemon-reload
sudo systemctl enable console.service
sudo systemctl set-default multi-user.target
echo "Done. Reboot (sudo reboot) and the Pi will start into Console."
echo "SSH still works. To see the app's messages: journalctl -u console -f"
