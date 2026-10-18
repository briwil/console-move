#!/bin/bash
# Install what the Console app needs. Run once: ./setup.sh
set -e
sudo apt update
sudo apt install -y python3-pygame
echo "Done. Start the app with: ~/console/pi-app/run.sh"
