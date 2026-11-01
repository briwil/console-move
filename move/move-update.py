"""Update Console on the Move, on the Move itself: no Pi, no Mac.

    python3 /data/UserData/console/move/move-update.py              get the latest from GitHub and build
    python3 /data/UserData/console/move/move-update.py setup        one time: install the compiler (Zig)

It downloads briwil/console-move from GitHub (a private repo: it needs a read-only access key, saved in
/data/UserData/console/github-token), puts the app's files in /data/UserData/console, and builds the C parts
that change most (the sound core and the effects) with Zig, a compiler that is a single download and builds
for exactly the Move's system (glibc 2.35). The rest (drum machines, synths) were built once on the Pi and
stay as they are.
"""
import io
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

BASE = "/data/UserData"
CONSOLE = os.path.join(BASE, "console")
TOKEN = os.path.join(CONSOLE, "github-token")
ZIG_VERSION = "0.13.0"
ZIG_DIR = os.path.join(BASE, "zig")
ZIG = os.path.join(ZIG_DIR, "zig")
REPO = "briwil/console-move"
SKIP = ("pi-app/splash/", "pi-app/fonts/", "pi-app/schwung/src/", "pi-app/schwung/modules/")
TARGET = "aarch64-linux-gnu.2.35"


def say(text):
    print(text, flush=True)


def setup():
    """Download Zig into /data/UserData/zig (about 45 MB)."""
    if os.path.exists(ZIG):
        say("Zig is already installed: %s" % ZIG)
        return
    url = "https://ziglang.org/download/%s/zig-linux-aarch64-%s.tar.xz" % (ZIG_VERSION, ZIG_VERSION)
    say("Downloading Zig %s (about 45 MB)..." % ZIG_VERSION)
    tmp = os.path.join(BASE, "Scratch", "zig.tar.xz")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    urllib.request.urlretrieve(url, tmp)
    say("Unpacking...")
    out = os.path.join(BASE, "Scratch", "zig-unpack")
    shutil.rmtree(out, ignore_errors=True)
    try:
        with tarfile.open(tmp, "r:xz") as t:
            t.extractall(out)
    except (tarfile.CompressionError, ImportError):
        os.makedirs(out, exist_ok=True)                  # this Python can't read .xz: the system's tar can
        subprocess.run(["tar", "xJf", tmp, "-C", out], check=True)
    inner = os.path.join(out, os.listdir(out)[0])
    shutil.rmtree(ZIG_DIR, ignore_errors=True)
    shutil.move(inner, ZIG_DIR)
    os.remove(tmp)
    say("Installed: %s" % subprocess.run([ZIG, "version"], capture_output=True, text=True).stdout.strip())


def download():
    """The latest main branch, as a tar archive in memory."""
    if not os.path.exists(TOKEN):
        sys.exit("No GitHub access key yet: save it in %s (see MOVE-NOTES.md)." % TOKEN)
    key = open(TOKEN).read().strip()
    req = urllib.request.Request("https://api.github.com/repos/%s/tarball/main" % REPO,
                                 headers={"Authorization": "Bearer " + key, "Accept": "application/vnd.github+json",
                                          "User-Agent": "console-move-updater"})
    say("Downloading the latest from GitHub...")
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def unpack(data):
    """Puts pi-app/, move/ and the simulator's stand-ins (tools/sim/stubs/, the Move app uses them) from the archive into /data/UserData/console, over what's there (files that
    aren't in the archive, like the built libraries, stay)."""
    n = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        for m in t.getmembers():
            parts = m.name.split("/", 1)                 # the archive's top folder is "<owner>-<repo>-<commit>"
            if len(parts) < 2:
                continue
            rel = parts[1]
            if not (rel.startswith(("pi-app/", "move/", "tools/sim/stubs/"))) or (rel + "/").startswith(SKIP):
                continue
            if ".." in rel.split("/") or os.path.isabs(rel):
                continue                                 # never write outside the console folder
            dest = os.path.join(CONSOLE, rel)
            if m.isdir():
                os.makedirs(dest, exist_ok=True)
            elif m.isfile():
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with t.extractfile(m) as src, open(dest + ".new", "wb") as out:
                    shutil.copyfileobj(src, out)
                os.replace(dest + ".new", dest)
                if m.mode & 0o111:
                    os.chmod(dest, 0o755)
                n += 1
    say("Updated %d files." % n)


def build():
    if not os.path.exists(ZIG):
        say("No compiler yet (run with 'setup'): the C parts weren't rebuilt.")
        return False
    app = os.path.join(CONSOLE, "pi-app")
    jobs = [("the sound core", ["core/core.c"], "core/libconsolecore.so", ["-ldl", "-lm"]),
            ("the effects", ["fx/fx.c"], "fx/libconsolefx.so", ["-lm"])]
    ok = True
    for label, srcs, out, libs in jobs:
        say("Building %s..." % label)
        cmd = [ZIG, "cc", "-target", TARGET, "-O2", "-shared", "-fPIC",
               "-o", os.path.join(app, out + ".new")] + [os.path.join(app, s) for s in srcs] + libs
        r = subprocess.run(cmd, capture_output=True, text=True,
                           env=dict(os.environ, ZIG_GLOBAL_CACHE_DIR=os.path.join(BASE, "Scratch", "zig-cache")))
        if r.returncode != 0:
            say("  couldn't build %s:\n%s" % (label, (r.stderr or r.stdout)[-1500:]))
            ok = False
            continue
        os.replace(os.path.join(app, out + ".new"), os.path.join(app, out))
    # the libraries must look newer than their code, or the app tries to rebuild them (with a compiler it
    # doesn't have)
    now = time.time()
    for root, _dirs, files in os.walk(app):
        for f in files:
            if f.endswith(".so"):
                os.utime(os.path.join(root, f), (now, now))
    return ok


if __name__ == "__main__":
    if sys.argv[1:] == ["setup"]:
        setup()
    else:
        unpack(download())
        say("Done." if build() else "Done (see above).")
