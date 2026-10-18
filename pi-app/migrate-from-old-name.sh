#!/bin/bash
# One-time switch from the project's old name to "console".
# Run it once from the old folder after renaming the GitHub repo to "console":
#   cd ~/track8 && git pull && pi-app/migrate-from-old-name.sh
set -e
OLD="$HOME/track8"
NEW="$HOME/console"
echo "Stopping and removing the old start-up service..."
sudo systemctl disable --now track8.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/track8.service
sudo systemctl daemon-reload
if [ -d "$OLD" ] && [ ! -e "$NEW" ]; then
  echo "Moving $OLD to $NEW..."
  mv "$OLD" "$NEW"
fi
cd "$NEW"
git remote set-url origin https://github.com/briwil/console.git
git pull
echo "Installing the new start-up logo (this can take a minute)..."
pi-app/splash-setup.sh
sudo rm -rf /usr/share/plymouth/themes/track8
pi-app/boot-to-app.sh
pi-app/set-hostname.sh
pi-app/web-setup.sh
echo
echo "All done. The project now lives in ~/console. Reboot with: sudo reboot"
echo "After the reboot: ssh pi@console.local, and the file page is http://console.local"
