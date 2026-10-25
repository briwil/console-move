"""Run Console's app code on any computer with Python, no Pi, screen or audio device needed.

    import sim                      # first, before any app module
    e = sim.engine("Test song")     # the audio engine (silent, made-up timing)
    T = sim.transport(e)            # the main screen and its keys and knobs
    T.key("PLAY"); T.knob(11, 4, False)
    sim.shot(T, "main.png")         # what the screen shows, as a picture

Songs and settings go to a scratch folder (CONSOLE_DATA, default ./sim-data), never to ~/console-data.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.normpath(os.path.join(HERE, "..", "..", "pi-app"))
STUBS = os.path.join(HERE, "stubs")
sys.path[:0] = [STUBS, APP]                       # the stand-ins first, so they're used instead of the real ones
os.environ.setdefault("CONSOLE_DATA", os.path.abspath("sim-data"))
os.environ["PATH"] = STUBS + os.pathsep + os.environ.get("PATH", "")     # the stand-in nmcli

import pygame       # noqa: E402  (the stand-in)
import audio        # noqa: E402

audio.usb_inputs = lambda: []                     # no USB audio devices
audio.usb_outputs = lambda: []
audio.hdmi_card = lambda: "vc4hdmi0"              # pretend the headphones (HDMI audio) are there

pygame.init()
LAYOUTS = os.path.join(APP, "layouts")


def engine(song="Sim", bpm=120.0, start=False):
    """The audio engine. start=True runs its audio thread too (needed for the drum synth's sound)."""
    e = audio.Engine(song=song, bpm=bpm)
    if start:
        e.start()
    return e


def transport(e):
    import ui
    import console
    screen = ui.Screen.load(os.path.join(LAYOUTS, "main.ui"))
    t = console.Transport(screen, e)
    t.sim_screen = screen
    return t


def menu(t):
    import menu as menu_mod
    return menu_mod.Menu(os.path.join(LAYOUTS, "menu.ui"), t)


def shot(t, path, m=None):
    """Save the main screen (or the menu m) as a 1280x400 PNG."""
    f = pygame.Surface((1280, 400))
    if m is not None:
        m.refresh()
        m.draw(f)
    else:
        t.update_screen()
        t.sim_screen.draw(f)
        t.focus.draw_panel(f)
    f.img.convert("RGB").save(path)
    return path
