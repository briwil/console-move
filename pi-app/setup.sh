#!/bin/bash
# Install what the Console app needs. Run once: ./setup.sh
set -e
sudo apt update
sudo apt install -y python3-pygame python3-numpy python3-alsaaudio ffmpeg
echo "Done. Start the app with: ~/console/pi-app/run.sh"
