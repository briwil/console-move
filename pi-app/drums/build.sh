#!/bin/bash
# Builds libdrums.so (the drum synth) from the LXR sound engine in lxr/ and the console's glue.
# setup.sh runs this; drums.py also runs it when the library is missing or older than the code.
cd "$(dirname "$0")" || exit 1
S=lxr/Src/Soundengine
FILES="$(ls $S/DSPAudio/*.c $S/DSPAudio/FX/*.c $S/DSPAudio/FX/VerbTools/*.c) $S/FxBus.c
       $S/MIDI/MidiParser.c $S/MIDI/ParameterArray.c $S/MIDI/MidiVoiceControl.c lxr/Src/Preset/initKit.c
       console_drums.c mod_targets.c"
exec gcc -shared -O2 -fPIC -w -I shim -I lxr/Inc -I lxr/Inc/Soundengine -I lxr/Inc/Soundengine/DSPAudio \
    $FILES -o libdrums.so -lm -Wl,--no-undefined
