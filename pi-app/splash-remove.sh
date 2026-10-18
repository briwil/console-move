#!/bin/bash
# Go back to the Raspberry Pi's own start-up screen and boot messages.
set -e
cd "$(dirname "$0")"
sudo plymouth-set-default-theme -R pix || true
./loud-boot.sh
