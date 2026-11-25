#!/usr/bin/env python3
import argparse
import hmac
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import gitdesk
import partial
import workspace_ops

WEB = Path(__file__).resolve().parent / "web"
ASSETS = {"/": "index.html", "/app.js": "app.js", "/commands.js": "commands.js", "/style.css": "style.css"}


class Desk(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, desktop=False):
        super().__init__(("127.0.0.1", port), Handler, bind_and_activate=not desktop)
        if desktop:
            self.server_port = port  # Windows owns the listening socket.
        self.token = secrets.token_urlsafe(32)
        self.repos = {}
        self.registry_lock = threading.Lock()

    def register(self, path):
        root = gitdesk.repository(path)
        with self.registry_lock:
            self.repos.setdefault(str(root), (root, threading.Lock()))
        return str(root)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, body, mime="application/json"):
        if mime == "application/json":
            body = json.dumps(body, ensure_ascii=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def host_ok(self):
        port = self.server.server_port
        return self.headers.get("Host") in (f"localhost:{port}", f"127.0.0.1:{port}")

    def do_GET(self):
        if self.host_ok() and self.path == "/_ready":
            return self.reply(200, b"branchdesk-ready", "text/plain")
        if not self.host_ok() or self.path not in ASSETS:
            return self.reply(404, {})
        name = ASSETS[self.path]
        self.reply(200, (WEB / name).read_bytes(), mimetypes.guess_type(name)[0] or "text/plain")

    def do_POST(self):
        host = self.headers.get("Host")
        if (not self.host_ok() or self.headers.get("Origin") not in (None, "http://" + host)
                or not hmac.compare_digest(self.headers.get("X-Desk-Key", "").encode(), self.server.token.encode())):
            return self.reply(403, {"error": "터미널에 표시된 접속 주소로 다시 열어 주세요."})
        try:
            size = int(self.headers.get("Content-Length", 0))
            if size < 0 or size > 2_000_000:
                return self.reply(413, {"error": "요청이 너무 큽니다."})
            d = json.loads(self.rfile.read(size))
            if not isinstance(d, dict):
                raise ValueError("잘못된 요청입니다.")
            if self.path == "/api/open":
                value = self.server.register(d["path"])
            elif self.path == "/api/new":
                value = self.server.register(workspace_ops.new_repository(d))
            elif self.path == "/api/close":
                with self.server.registry_lock:
                    self.server.repos.pop(d["repo"], None)
                    value = list(self.server.repos)
            elif self.path == "/api/repos":
                with self.server.registry_lock:
                    value = list(self.server.repos)
            else:
                root, lock = self.server.repos[d["repo"]]
                with lock:
                    if self.path == "/api/state":
                        value = gitdesk.state(root, d.get("count", 150))
                    elif self.path == "/api/detail":
                        value = gitdesk.detail(root, d["rev"], d.get("base"))
                    elif self.path == "/api/diff":
                        value = gitdesk.diff(root, d)
                    elif self.path in ("/api/conflict","/api/resolve"):
                        value = partial.conflict_file(root, d, resolve=self.path.endswith("resolve"))
                    elif self.path == "/api/urls":
                        value = workspace_ops.remote_urls(root)
                    elif self.path in ("/api/lines", "/api/lines-apply"):
                        value = partial.partial(root, d, apply=self.path.endswith("-apply"))
                    elif self.path == "/api/action":
                        value = gitdesk.act(root, d)
                    else:
                        return self.reply(404, {})
            self.reply(200, {"value": value})
        except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as e:
            self.reply(400, {"error": str(e)})


def open_page(url):
    if shutil.which("wslview"):
        command = ["wslview", url]
    elif shutil.which("explorer.exe"):
        command = ["explorer.exe", url]
    else:
        webbrowser.open(url)
        return
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser(description="WSL 저장소용 Git GUI")
    parser.add_argument("repositories", nargs="*", metavar="REPO")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        server = Desk(args.port)
        for path in args.repositories:
            server.register(path)
        if not args.repositories:
            try:
                server.register(os.getcwd())
            except gitdesk.GitError:
                pass
    except (ValueError, OSError) as e:
        parser.exit(1, f"{e}\n")
    url = f"http://localhost:{server.server_port}/#{server.token}"
    print(f"Branchdesk · Windows 브라우저에서 열기\n{url}\n종료하려면 Ctrl+C", flush=True)
    if not args.no_browser:
        try:
            open_page(url)
        except OSError as e:
            print(str(e), file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
