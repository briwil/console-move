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

## Licence and third-party work

Console is free software under the GNU General Public License v3.0 ([LICENSE](LICENSE)). It bundles drum engines, effects and Schwung modules made by other people, each under its own licence; they are listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). Those modules belong to their authors. If you made one and want it credited differently, relicensed or removed, please open an issue on this repository and it will be dealt with promptly.

"Erica Synths", "LXR" and "LXR-02" are trademarks of Erica Synths; "Ableton" and "Move" are trademarks of Ableton AG. Console is not affiliated with or endorsed by either company.
