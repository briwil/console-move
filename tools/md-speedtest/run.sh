#!/bin/bash
# Machinedrum speed test: can the Pi run the Machinedrum emulator live?
#
# Builds the emulator (joelanders/gearmulator-md-mm) with a small test program, then plays a beat through it
# with your ROM and times it. The first run downloads and builds for a while; later runs start straight away.
#
#   tools/md-speedtest/run.sh [path-to-rom.bin]
#
# The ROM defaults to ~/console-data/roms/elektron_sps1-1uw_os1.63.bin. It never goes into the repo.
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
ROM="${1:-$HOME/console-data/roms/elektron_sps1-1uw_os1.63.bin}"
SRC="$HOME/gearmulator-md-mm"
BUILD="$SRC/temp/speedtest"
COMMIT=4050ce447a176ab1d900b1c578a7c0d18cdaf43a        # the version this test was made with

if [ ! -f "$ROM" ]; then
    echo "Can't find the ROM at $ROM"
    echo "Copy it there, or give its path:  tools/md-speedtest/run.sh /path/to/rom.bin"
    exit 1
fi

missing=""
for tool in git cmake g++; do
    command -v $tool >/dev/null || missing="$missing $tool"
done
if [ -n "$missing" ]; then
    echo "Installing:$missing (it may ask for your password)"
    sudo apt-get install -y git cmake g++
fi

if [ ! -d "$SRC/.git" ]; then
    echo "Downloading the emulator..."
    git init -q "$SRC"
    git -C "$SRC" remote add origin https://github.com/joelanders/gearmulator-md-mm.git
fi
if [ "$(git -C "$SRC" rev-parse HEAD 2>/dev/null)" != "$COMMIT" ]; then
    git -C "$SRC" fetch -q --depth 1 origin $COMMIT
    git -C "$SRC" checkout -q -f $COMMIT
fi
git -C "$SRC" submodule update -q --init --depth 1 source/dsp56300 source/mc68k source/cpp-terminal \
    source/3rdparty/RmlUi source/3rdparty/freetype source/3rdparty/lunasvg
git -C "$SRC/source/dsp56300" submodule update -q --init --depth 1

# add the test program to the emulator's build
cp "$HERE/mdSpeedTest.cpp" "$SRC/source/elektron/md/"
grep -q mdSpeedTest "$SRC/source/elektron/md/CMakeLists.txt" || \
    printf '\nadd_executable(mdSpeedTest mdSpeedTest.cpp)\ntarget_link_libraries(mdSpeedTest PRIVATE mdLib)\n' \
    >> "$SRC/source/elektron/md/CMakeLists.txt"

echo "Building (the first time takes a while)..."
off=""
for synth in OSIRUS OSTIRUS VAVRA XENIA NODALRED2X JE8086; do off="$off -Dgearmulator_SYNTH_$synth=OFF"; done
cmake -S "$SRC" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release -Dgearmulator_BUILD_JUCEPLUGIN=OFF -DBUILD_TESTING=OFF \
    $off > "$BUILD.log" 2>&1 || { tail -20 "$BUILD.log"; exit 1; }
cmake --build "$BUILD" --target mdSpeedTest -j "$(nproc)" >> "$BUILD.log" 2>&1 || { tail -30 "$BUILD.log"; exit 1; }

echo "Running: about 15 s of start-up, then 30 s of beat..."
mkdir -p "$HOME/console-data"
"$BUILD/source/elektron/md/mdSpeedTest" "$ROM" 30 "$HOME/console-data/md-speedtest.wav" 2>&1 \
    | grep -E "^(Start-up|Played|Worst|Sound|RESULT|Wrote|Warning|Couldn|That file|The emulator)"
