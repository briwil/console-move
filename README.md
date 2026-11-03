# Console on the Ableton Move

An 8-track tape recorder with OP-1/OP-XY-style editing, up to 8 instruments (drum machines and synths, including
ones from Schwung's catalog) and step sequencers, running as an app on an Ableton Move.

- **How to use it:** [move/manual/Console-on-Move-Manual.pdf](move/manual/Console-on-Move-Manual.pdf)
- **How it works / notes:** [move/MOVE-NOTES.md](move/MOVE-NOTES.md)
- **Updating the Move:** Menu, SETTINGS, SOFTWARE UPDATE (see [move/UPDATE.md](move/UPDATE.md))

| Folder | What it holds |
|---|---|
| `move/` | The Move's screen and buttons, the updater, the build script, notes and manual |
| `pi-app/` | The app itself: audio engine, sound core (C), drum machines, sequencers, Schwung support, Ableton Link |
| `tools/` | The screen designer and the stand-in modules the Move app uses |

The libraries (synths, sound core, Link...) are compiled in the cloud by GitHub Actions
(`.github/workflows/move-libs.yml`) and downloaded by the updater.

*Originally this was a Raspberry Pi recorder; its history (including the KiCad control board) is in the git log.*
