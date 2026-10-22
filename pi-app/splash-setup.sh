#!/bin/bash
# Show the start-up animation (splash/frames/) while the Pi starts, instead of text.
# Also hides the boot messages (runs quiet-boot.sh). Undo with: ./splash-remove.sh
set -e
cd "$(dirname "$0")"
./quiet-boot.sh > /dev/null
sudo apt install -y plymouth > /dev/null
sudo mkdir -p /usr/share/plymouth/themes/console
sudo rm -f /usr/share/plymouth/themes/console/*.png
sudo cp splash/console.plymouth splash/console.script splash/frames/*.png /usr/share/plymouth/themes/console/
echo "Installing the start-up screen (this can take a minute)..."
sudo plymouth-set-default-theme -R console
BOOT=/boot/firmware
[ -f $BOOT/cmdline.txt ] || BOOT=/boot
grep -qw splash $BOOT/cmdline.txt || sudo sed -i '1 s/$/ splash/' $BOOT/cmdline.txt
echo "Done. Run ./boot-to-app.sh again if you haven't since updating, then: sudo reboot"
