#!/usr/bin/env python3
"""Console file page: open http://console.local in a browser on the same Wi-Fi.

Lets you browse the console's storage, download files (or whole folders as a
zip), upload files, make folders and delete things. Uses only Python's
standard library.

Storage lives in ~/console-data (or $CONSOLE_DATA), with three folders:
projects, samples and exports.

Run by hand:   python3 server.py --port 8080
As a service:  see ../console-web.service (port 80)
"""
import argparse
import json
import mimetypes
import os
import shutil
import sys
import time
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "..", "fonts")
DATA = os.path.realpath(os.path.expanduser(os.environ.get("CONSOLE_DATA", "~/console-data")))
TOP_FOLDERS = ["projects", "samples", "exports"]
CHUNK = 1024 * 256


def safe_path(rel):
    """Turn a path from the browser into a real path inside DATA, or None if it points outside."""
    rel = urllib.parse.unquote(rel or "").strip("/")
    full = os.path.realpath(os.path.join(DATA, rel))
    if full != DATA and not full.startswith(DATA + os.sep):
        return None
    return full


def rel_of(full):
    return os.path.relpath(full, DATA).replace(os.sep, "/") if full != DATA else ""


def folder_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


class Handler(BaseHTTPRequestHandler):
    server_version = "Console"

    def log_message(self, fmt, *args):
        sys.stderr.write("web: %s\n" % (fmt % args))

    # ------------------------------------------------------------ helpers

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def fail(self, status, message):
        self.send_json({"error": message}, status)

    def query(self):
        u = urllib.parse.urlsplit(self.path)
        return u.path, {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}

    def send_file(self, full, download):
        size = os.path.getsize(full)
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        if download:
            name = urllib.parse.quote(os.path.basename(full))
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''%s" % name)
        else:
            self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        with open(full, "rb") as f:
            shutil.copyfileobj(f, self.wfile, CHUNK)

    # ------------------------------------------------------------ GET

    def do_GET(self):
        path, q = self.query()
        if path in ("/", "/index.html"):
            return self.send_file(os.path.join(HERE, "index.html"), False)
        if path.startswith("/fonts/"):
            name = os.path.basename(path)
            full = os.path.join(FONT_DIR, name)
            if name.endswith(".ttf") and os.path.isfile(full):
                return self.send_file(full, False)
            return self.fail(404, "No such font")
        if path == "/api/list":
            return self.list_folder(q.get("path", ""))
        if path == "/api/download":
            full = safe_path(q.get("path"))
            if not full or not os.path.isfile(full):
                return self.fail(404, "That file isn't there any more")
            return self.send_file(full, q.get("inline") != "1")
        if path == "/api/zip":
            return self.send_zip(q.get("path", ""))
        self.fail(404, "Not found")

    def list_folder(self, rel):
        full = safe_path(rel)
        if not full or not os.path.isdir(full):
            return self.fail(404, "That folder isn't there any more")
        entries = []
        for name in sorted(os.listdir(full), key=str.lower):
            if name.startswith("."):
                continue
            p = os.path.join(full, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            is_dir = os.path.isdir(p)
            entries.append({
                "name": name,
                "folder": is_dir,
                "size": folder_size(p) if is_dir else st.st_size,
                "modified": int(st.st_mtime),
            })
        entries.sort(key=lambda e: (not e["folder"], e["name"].lower()))
        du = shutil.disk_usage(DATA)
        self.send_json({"path": rel_of(full), "entries": entries,
                        "free": du.free, "total": du.total, "top": TOP_FOLDERS})

    def send_zip(self, rel):
        full = safe_path(rel)
        if not full or not os.path.isdir(full):
            return self.fail(404, "That folder isn't there any more")
        name = os.path.basename(full) or "console"
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''%s.zip" % urllib.parse.quote(name))
        self.send_header("Connection", "close")
        self.end_headers()
        # WAV files barely compress, so store them as-is: faster and the same size
        with zipfile.ZipFile(self.wfile, "w", zipfile.ZIP_STORED) as z:
            for root, dirs, files in os.walk(full):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for f in files:
                    if f.startswith("."):
                        continue
                    p = os.path.join(root, f)
                    z.write(p, os.path.join(name, os.path.relpath(p, full)))
        self.close_connection = True

    # ------------------------------------------------------------ POST

    def do_POST(self):
        path, q = self.query()
        if path == "/api/upload":
            return self.upload(q.get("path", ""), q.get("name", ""))
        if path == "/api/mkdir":
            return self.mkdir(q.get("path", ""), q.get("name", ""))
        if path == "/api/delete":
            return self.delete(q.get("path", ""))
        self.fail(404, "Not found")

    def clean_name(self, name):
        name = os.path.basename(name.replace("\\", "/")).strip()
        return name if name and name not in (".", "..") and not name.startswith(".") else None

    def upload(self, rel, name):
        folder = safe_path(rel)
        name = self.clean_name(name)
        if not folder or not os.path.isdir(folder) or not name:
            return self.fail(400, "Can't upload there")
        length = int(self.headers.get("Content-Length") or 0)
        if length > shutil.disk_usage(DATA).free - 50 * 1024 * 1024:
            return self.fail(507, "Not enough free space for %s" % name)
        dest = os.path.join(folder, name)
        base, ext = os.path.splitext(name)
        n = 2
        while os.path.exists(dest):          # never overwrite: add a number instead
            dest = os.path.join(folder, "%s %d%s" % (base, n, ext))
            n += 1
        tmp = os.path.join(folder, ".upload-%d" % time.time_ns())
        try:
            with open(tmp, "wb") as f:
                left = length
                while left > 0:
                    chunk = self.rfile.read(min(CHUNK, left))
                    if not chunk:
                        raise IOError("upload stopped early")
                    f.write(chunk)
                    left -= len(chunk)
            os.replace(tmp, dest)
        except Exception as e:
            if os.path.exists(tmp):
                os.remove(tmp)
            return self.fail(500, "Upload of %s failed: %s" % (name, e))
        self.send_json({"saved": os.path.basename(dest)})

    def mkdir(self, rel, name):
        folder = safe_path(rel)
        name = self.clean_name(name)
        if not folder or not os.path.isdir(folder) or not name:
            return self.fail(400, "That folder name won't work")
        dest = os.path.join(folder, name)
        if os.path.exists(dest):
            return self.fail(409, "%s already exists" % name)
        os.mkdir(dest)
        self.send_json({"made": name})

    def delete(self, rel):
        full = safe_path(rel)
        if not full or full == DATA or rel_of(full) in TOP_FOLDERS:
            return self.fail(400, "That can't be deleted")
        if not os.path.exists(full):
            return self.fail(404, "Already gone")
        if os.path.isdir(full):
            shutil.rmtree(full)
        else:
            os.remove(full)
        self.send_json({"deleted": rel_of(full)})


def main():
    ap = argparse.ArgumentParser(description="Console file page")
    ap.add_argument("--port", type=int, default=int(os.environ.get("CONSOLE_WEB_PORT", "80")))
    args = ap.parse_args()
    for d in TOP_FOLDERS:
        os.makedirs(os.path.join(DATA, d), exist_ok=True)
    srv = ThreadingHTTPServer(("", args.port), Handler)
    srv.daemon_threads = True
    print("Console file page: http://%s.local%s  (storage: %s)" % (
        os.uname().nodename, "" if args.port == 80 else ":%d" % args.port, DATA))
    srv.serve_forever()


if __name__ == "__main__":
    main()
