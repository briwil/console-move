#!/bin/bash
# Hide the boot messages, rainbow square and blinking cursor, so the screen
# stays black until Track8 appears. Undo with: ./loud-boot.sh
set -e
BOOT=/boot/firmware
[ -f $BOOT/cmdline.txt ] || BOOT=/boot
# keep the original files the first time, so loud-boot.sh can put them back
[ -f $BOOT/cmdline.txt.track8-backup ] || sudo cp $BOOT/cmdline.txt $BOOT/cmdline.txt.track8-backup
[ -f $BOOT/config.txt.track8-backup ] || sudo cp $BOOT/config.txt $BOOT/config.txt.track8-backup

# cmdline.txt must stay one single line
sudo python3 - "$BOOT/cmdline.txt" <<'PY'
import sys
path = sys.argv[1]
words = open(path).read().split()
words = ["console=tty3" if w == "console=tty1" else w for w in words if w != "splash"]
for w in ["quiet", "loglevel=3", "logo.nologo", "vt.global_cursor_default=0",
          "systemd.show_status=false", "rd.udev.log_level=3"]:
    if w not in words:
        words.append(w)
open(path, "w").write(" ".join(words) + "\n")
PY

grep -q "^disable_splash=1" $BOOT/config.txt || echo "disable_splash=1" | sudo tee -a $BOOT/config.txt > /dev/null
echo "Done. Reboot (sudo reboot) to see the quiet start."
