# Runs once when the controller powers up, before code.py.
# Names the controller so the Pi can tell it apart from other USB devices.
import supervisor
import usb_midi

try:
    supervisor.set_usb_identification("DIY", "Console Controls")
except Exception:
    pass
try:
    usb_midi.set_names(audio_control_interface_name="Console Controls",
                       in_jack_name="Console Controls", out_jack_name="Console Controls")
except Exception:
    pass
