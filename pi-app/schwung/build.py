"""Fetch and build the Schwung sound generators listed in catalog.py, on the Pi itself.

Each module is fetched from GitHub at the exact version catalog.py names (so an update upstream can't
change what Console runs without us looking at it first) and compiled with the Pi's own gcc / g++,
the way its own build script does it for the Move. The results go in schwung/modules/<id>/ (not kept in
git): dsp.so and module.json, the two files a module is.

  python3 schwung/build.py            build every module that's missing or out of date
  python3 schwung/build.py forge      just that one (or several)
  python3 schwung/build.py --list     what's there

The app runs it in the background at start-up (at low priority) for anything missing, so a software
update that adds a module needs nothing else; run it by hand to watch it work.
"""
import glob
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import catalog  # noqa: E402

SRC = os.path.join(HERE, "src")          # the modules' code, one folder each
OUT = os.path.join(HERE, "modules")      # the built modules
HOST_LIB = os.path.join(HERE, "libschwunghost.so")
DATA = os.environ.get("CONSOLE_DATA", os.path.expanduser("~/console-data"))
LOCAL_CMAKE = os.path.expanduser("~/.local/bin/cmake")


def log(msg):
    print("Schwung modules: %s" % msg, flush=True)


def run(cmd, cwd, timeout=1800):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[-600:] or "failed")
    return r.stdout


def cmake():
    """cmake: the system's, or one installed for this user with pip (no password needed)."""
    found = shutil.which("cmake") or (LOCAL_CMAKE if os.path.exists(LOCAL_CMAKE) else None)
    if found:
        return found
    log("installing cmake (for this user)...")
    run([sys.executable, "-m", "pip", "install", "--user", "--break-system-packages", "--quiet", "cmake"], HERE)
    return LOCAL_CMAKE


def build_host():
    """libschwunghost.so: the small host that loads modules (host.c)."""
    src = os.path.join(HERE, "host.c")
    if os.path.exists(HOST_LIB) and os.path.getmtime(HOST_LIB) >= max(
            os.path.getmtime(src), os.path.getmtime(os.path.join(HERE, "plugin_api_v1.h"))):
        return True
    try:
        run(["gcc", "-O2", "-shared", "-fPIC", "-o", HOST_LIB + ".tmp", src, "-ldl"], HERE)
        os.replace(HOST_LIB + ".tmp", HOST_LIB)
        return True
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        log("couldn't build the host: %s" % e)
        return False


def fetch(m):
    """The module's code at its pinned commit, in src/<id>/."""
    d = os.path.join(SRC, m["id"])
    stamp = os.path.join(d, ".console-commit")
    if os.path.exists(stamp) and open(stamp).read().strip() == m["commit"]:
        return d
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)
    url = "https://github.com/%s.git" % m["repo"]
    run(["git", "init", "-q"], d)
    run(["git", "fetch", "-q", "--depth", "1", url, m["commit"]], d, timeout=900)
    run(["git", "checkout", "-q", "FETCH_HEAD"], d)
    for sub in m.get("submodules", []):
        run(["git", "submodule", "update", "--init", "--depth", "1", sub], d, timeout=900)
    with open(stamp, "w") as f:
        f.write(m["commit"])
    return d


def built(m):
    stamp = os.path.join(OUT, m["id"], ".console-commit")
    return os.path.exists(os.path.join(OUT, m["id"], "dsp.so")) and os.path.exists(stamp) \
        and open(stamp).read().strip() == m["commit"] + catalog.recipe_version(m)


def build(m):
    """Fetch and compile one module. Returns None if it worked, else what went wrong."""
    if built(m):
        return None
    try:
        log("fetching %s..." % m["title"])
        d = fetch(m)
        out_dir = os.path.join(OUT, m["id"])
        os.makedirs(out_dir, exist_ok=True)
        tmp = os.path.join(out_dir, "dsp.so.tmp")
        log("building %s..." % m["title"])
        for step in m["build"]:
            args = []
            for a in step:
                if "*" in a:                        # a wildcard: the files it matches, in order
                    found = sorted(glob.glob(os.path.join(d, a)))
                    args += [os.path.relpath(f, d) for f in found] or [a]
                elif a == "{cmake}":
                    args.append(cmake())
                else:
                    args.append(a.replace("{out}", tmp))
            run(args, d, timeout=3 * 3600)
        os.replace(tmp, os.path.join(out_dir, "dsp.so"))
        # module.json, and anything else the module reads from its folder (presets, kits...)
        shutil.copyfile(os.path.join(d, m["json"]), os.path.join(out_dir, "module.json"))
        for rel in m.get("files", []):
            src = os.path.join(d, rel)
            dst = os.path.join(out_dir, os.path.basename(rel.rstrip("/")))
            if os.path.isdir(src):
                shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst)
            elif os.path.exists(src):
                shutil.copy2(src, dst)              # keeps a helper program runnable
        if m.get("roms"):
            # the module looks for ROMs in its own roms/ folder: that's ~/console-data/roms/<name>, which
            # the file page (http://console.local) can upload to
            roms = os.path.join(DATA, "roms", m["roms"])
            os.makedirs(roms, exist_ok=True)
            link = os.path.join(out_dir, "roms")
            if os.path.islink(link) or os.path.isfile(link):
                os.remove(link)
            elif os.path.isdir(link):
                shutil.rmtree(link)
            os.symlink(roms, link)
        with open(os.path.join(out_dir, ".console-commit"), "w") as f:
            f.write(m["commit"] + catalog.recipe_version(m))
        log("%s ready" % m["title"])
        return None
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        log("couldn't build %s: %s" % (m["title"], e))
        return str(e)


def main(args):
    if "--list" in args:
        for m in catalog.MODULES:
            print("%-14s %-6s %s" % (m["id"], m["kind"], "built" if built(m) else "-"))
        return 0
    if not build_host():
        return 1
    want = [m for m in catalog.MODULES if not args or m["id"] in args]
    bad = [m["title"] for m in want if build(m)]
    if bad:
        log("not built: %s" % ", ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
