#!/bin/bash
# Build Console's sound engines (drum synth, effects, drum machines, Schwung synths) for the Ableton Move.
# Run on the Raspberry Pi 5 (same kind of processor as the Move):
#
#     bash ~/console-move/move/build-for-move.sh
#
# The Move's system libraries are older (glibc 2.35) than the Pi's, so a library built normally on the Pi
# won't load there. This builds inside an Ubuntu 22.04 container instead, which has exactly glibc 2.35,
# and leaves everything in ~/move-libs.tgz, ready to copy to the Move.
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$HOME/move-libs.tgz"

if ! command -v docker >/dev/null; then
  echo "Installing Docker (one time)..."
  sudo apt update && sudo apt install -y docker.io
fi

echo "Building in Ubuntu 22.04 (first run downloads it and the compilers: a few minutes)..."
sudo docker run --rm -v "$REPO":/src:ro -v "$HOME":/out ubuntu:22.04 bash -c '
  set -e
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq gcc g++ make cmake git python3 ca-certificates binutils >/dev/null
  cp -r /src/pi-app /build && cd /build
  find . -name "*.so" -delete
  rm -rf schwung/modules schwung/src
  echo "- effects";        gcc -O2 -shared -fPIC -o fx/libconsolefx.so fx/fx.c -lm
  echo "- LXR drum synth"; bash drums/build.sh
  cp drums/libdrums.so drums/libdrums_live.so 2>/dev/null || true
  echo "- 606 / 808";      for m in 606 808; do g++ -O2 -shared -fPIC -w -o drums/schwung/lib$m.so drums/schwung/glue$m.cpp; done
  echo "- Machinedrum";    g++ -O2 -std=c++11 -shared -fPIC -w -Idrums/md/vendor -Idrums/md -o drums/md/libmd.so drums/md/glue_md.cpp
  echo "- Schwung synths and drum machines (the longest part)"
  python3 schwung/build.py || echo "(some modules failed: see above)"
  echo
  echo "Newest system library versions needed (the Move has GLIBC 2.35):"
  for f in $(find . -name "*.so"); do objdump -T "$f" | grep -o "GLIBC_2\.[0-9]*\|GLIBCXX_3\.4\.[0-9]*"; done | sort -V | uniq | grep GLIBC_ | tail -n 1
  for f in $(find . -name "*.so"); do objdump -T "$f" | grep -o "GLIBCXX_3\.4\.[0-9]*"; done | sort -V | uniq | tail -n 1
  tar czf /out/move-libs.tgz $(find . -name "*.so") schwung/modules
  chown '"$(id -u):$(id -g)"' /out/move-libs.tgz
'
echo
echo "Done: $OUT"
