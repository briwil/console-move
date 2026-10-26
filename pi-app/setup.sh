#!/bin/bash
# Install what the Console app needs. Run once (and again after updates that say so): ./setup.sh
set -e
cd "$(dirname "$0")"
sudo apt update
sudo apt install -y python3-pygame python3-numpy python3-alsaaudio ffmpeg gcc g++ libc6-dev python3-pip
echo "Installing Ableton Link (aalink)..."
sudo pip3 install --break-system-packages --upgrade aalink
echo "Building the effects (reverb and delay)..."
gcc -O2 -shared -fPIC -o fx/libconsolefx.so fx/fx.c -lm
echo "Building the drum synth..."
bash drums/build.sh
# the TR-606 and TR-808 (Schwung), one library each
for m in 606 808; do g++ -O2 -shared -fPIC -w -o drums/schwung/lib$m.so drums/schwung/glue$m.cpp; done
echo "Done. Start the app with: ~/console/pi-app/run.sh"
