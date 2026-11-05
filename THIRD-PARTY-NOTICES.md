# Third-party notices

Console is released under the GNU General Public License v3.0 (see [LICENSE](LICENSE)). It bundles the third-party work below, each under its own licence. Full licence texts sit next to the code (`LICENSE*` files) where the authors supplied them.

## Trademarks and hardware

- "Erica Synths", "LXR" and "LXR-02" are trademarks of Erica Synths. Console is not affiliated with or approved by Erica Synths. Truthful compatibility statements are fine; official branding is not allowed. The LXR hardware design is not licensed to anyone and is not part of this repository.
- Ableton and Move are trademarks of Ableton AG. Console is not affiliated with Ableton.

## Drum engines

| Component | Location | Licence |
|---|---|---|
| LXR-02 firmware (Erica Synths), used as a drum engine and modified | `pi-app/drums/lxr/` | GPL-3.0 with extra terms; see `pi-app/drums/lxr/NOTICE.md` (trademarks; modified versions must be marked as modified) |
| Open-XY drums | `pi-app/drums/md/` | MIT (`LICENSE-OPEN-XY`) |
| OP-XY MNMD drums | `pi-app/drums/md/` | MIT (`LICENSE-OP-XY-MNMD`) |
| 606 drum engine | `pi-app/drums/schwung/606/` | GPL-3.0 and MIT (`LICENSE-GPL3`, `LICENSE.MIT`) |
| 808 drum engine | `pi-app/drums/schwung/808/` | GPL-3.0 (`LICENSE-GPL3`) |
| Reverb ported from Mutable Instruments Elements/Rings (Emilie Gillet) | `pi-app/fx/` | MIT (`LICENSE-mutable.txt`) |

## Schwung modules (`pi-app/schwung/modules/`)

Licence is taken from each module's `module.json`.

| Module | Author | Licence |
|---|---|---|
| 303 | Robin Schmidt / midilab / davemollen / Charles Vestal | GPL-3.0 |
| 4k-eq | 4K EQ 2 by Dusk Audio (GPL-3.0); port: athousanddetails | NOT STATED |
| ambiotica | Charles Vestal | MIT |
| amino | AI & Klaine | NOT STATED |
| aphex | Filliformes | MIT |
| bizar | AI & Klaine | NOT STATED |
| braids | Emilie Gillet (port: charlesvestal) | MIT |
| busdriver | legsmechanical | MIT |
| capicola | Heavylight Industries (port: charlesvestal) | AGPL-3.0 |
| chiptune | charlesvestal | MIT/LGPL-2.1 |
| chonk | legsmechanical (DSP: Punk Labs LLC) | GPL-3.0-or-later |
| chordism | charlesvestal | MIT |
| chowtape | charlesvestal | GPL-3.0 |
| clap | charlesvestal, Chris Johnson (Airwindows) | MIT |
| cloudseed | Ghost Note Audio (port: charlesvestal) | MIT |
| crest | AI & Klaine | NOT STATED |
| cw78 | A Thousand Details; every voice modelled from the Roland CR-78 service notes (June 1979), VG-11A voicing board | NOT STATED |
| denis | Vincent Fillion | NOT STATED |
| dexed | Dexed/MSFA by google/asb2m10 (port: charlesvestal) | GPL-3.0 |
| dissolver | fillioning | NOT STATED |
| dragonfly-hall | bradcoomber | GPL-3.0 |
| ducker | charlesvestal | MIT |
| essaim | fillioning | NOT STATED |
| filter | charlesvestal | MIT |
| fizzik | Filliformes | NOT STATED |
| forge | Vincent Fillion | MIT |
| gate | charlesvestal | MIT |
| granular | Boris (port: charlesvestal) | GPL-3.0 |
| gresil | Emilie Gillet (DSP) / filliformes (port) | MIT |
| hank | charlesvestal | MIT |
| hera | jpcima (port: charlesvestal) | GPL-3.0 |
| hush1 | Move Everything Community | NOT STATED |
| je8086 | dsp56300/gearmulator (port: charlesvestal) | NOT STATED |
| junologue-chorus | Peter Allwin (port: charlesvestal) | MIT |
| libpo32 | mestela | NOT STATED |
| maze | sd88me | NOT STATED |
| midiverb | Charles Vestal (DSP: thement/midiverb_emulator) | GPL-3.0 |
| model-72 | sd88me | NOT STATED |
| mono-voice | timncox | NOT STATED |
| mrsample | charlesvestal | MIT |
| munchi-delay | CHOMPI Club / Chase Bliss (CHOMPI TEMPO, MIT) · port: charlesvestal | MIT |
| mverb | Andre Louis (DSP: Martin Eastwood) | GPL-3.0 |
| noisemaker | legsmechanical (engine: Patrick Kunz / TAL) | GPL-2.0 |
| nusaw | charlesvestal | MIT |
| obxd | reales (port: charlesvestal) | GPL-3.0 |
| omega | James Fish | NOT STATED |
| ottx | Schwung OTTx port; DSP by Matt Tytel (Vital), Yegor Suslin (vitOTT) | NOT STATED |
| palette | Filliformes | NOT STATED |
| plaits | Emilie Gillet (port: Justin Joe) | MIT |
| psxverb | charlesvestal | MIT |
| pushnpull | legsmechanical | MIT |
| quark | James Fish & Claude | NOT STATED |
| quilt | ? | NOT STATED |
| raffo | Nicolas Roulet, Julian Palladino (port: charlesvestal) | MIT |
| rrverb10 | Schwung RRVerb-10 port; chip emulation by Sergey V. Mikayev (MUNT), ROM research by giulioz | LGPL-2.1-or-later |
| ruminant | mestela | NOT STATED |
| setbfree-organ | Robin Gareus, Fredrik Kilander (port: Pascal Dubucq) | NOT STATED |
| sf2 | FluidLite by Robin Lobel (port: charlesvestal) | LGPL-2.1 |
| shimmerwash | Dan | NOT STATED |
| simian | legsmechanical | GPL-3.0-or-later |
| spectra | fillioning | NOT STATED |
| stereoid | legsmechanical | MIT |
| structor | fillioning | NOT STATED |
| superboom | fillioning | NOT STATED |
| surge | Surge Synth Team (port: charlesvestal) | GPL-3.0 |
| tablor | athousanddetails; after Wavetable (Roland Rabien / FigBug, BSD-3) | NOT STATED |
| tape-echo2 | Tape Echo 2 by Dusk Audio (GPL-3.0); port: athousanddetails | NOT STATED |
| tapedelay | cyrusasfa (port: charlesvestal) | MIT |
| tapescam | charlesvestal | MIT |
| tenebrae | legsmechanical | MIT |
| tinyk | Mathew Taylor | MIT |
| tinypro5 | TinyPro5 | NOT STATED |
| usefulity | charlesvestal | MIT |
| verglas | Emilie Gillet (DSP) / filliformes (port) | NOT STATED |
| war_bells | seajay | AGPL-3.0-or-later |
| weirddreams | Vincent Fillion (DSP: Daniele Filaretti, MIT) | MIT |
| work | timncox | NOT STATED |
| wurl | fillioning (port of OpenWurli by hal0zer0) | NOT STATED |

## Needs checking before release

These 32 modules state no licence in `module.json`: 4k-eq, amino, bizar, crest, cw78, denis, dissolver, essaim, fizzik, hush1, je8086, libpo32, maze, model-72, mono-voice, omega, ottx, palette, quark, quilt, ruminant, setbfree-organ, shimmerwash, spectra, structor, superboom, tablor, tape-echo2, tinypro5, verglas, work, wurl.

With no licence stated, the authors keep all rights, so they may not be redistributed until the author confirms a licence or they are removed from the public repository. Some say a licence in their name or description (for example 4k-eq and tape-echo2 mention GPL-3.0), which should be confirmed with the author.

Also check: `noisemaker` is GPL-2.0, `capicola` and `war_bells` are AGPL-3.0 (network-use clause), and `chiptune` is dual MIT/LGPL-2.1.
