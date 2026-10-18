#!/bin/bash
# Put the normal boot messages back (undoes quiet-boot.sh).
set -e
BOOT=/boot/firmware
[ -f $BOOT/cmdline.txt ] || BOOT=/boot
for f in cmdline.txt config.txt; do
  if [ -f $BOOT/$f.track8-backup ]; then
    sudo cp $BOOT/$f.track8-backup $BOOT/$f
    sudo rm $BOOT/$f.track8-backup
  fi
done
echo "Done. Reboot (sudo reboot) to see the normal boot messages again."
