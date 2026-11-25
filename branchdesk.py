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
import commit_ops
import updater
import environments
from tab_store import TabStore

WEB = Path(__file__).resolve().parent / "web"
ASSETS = {"/panes.js": "panes.js", "/": "index.html", "/app.js": "app.js", "/commands.js": "commands.js", "/style.css": "style.css",
          "/icon.png": "icon.png", "/favicon.ico": "favicon.ico", "/context.js": "context.js", "/update.js": "update.js", "/environments.js": "environments.js"}


class Desk(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, desktop=False, launcher=None):
        super().__init__(("127.0.0.1", port), Handler, bind_and_activate=not desktop)
        if desktop:
            self.server_port = port  # Windows owns the listening socket.
        self.token = secrets.token_urlsafe(32)
        self.repos = {}
        self.registry_lock = threading.Lock()
        self.environments = environments.Environments()
        self.tabs = TabStore()
        self.tab_warning = None
        self.active = None
        resume_path = None
        if launcher and launcher.get('pid', 0) > 0:
            try:
                windows_root = self.environments.windows_root()
                if windows_root: resume_path = Path(updater.wsl_path(windows_root)) / 'resume-ui.json'
            except (ValueError, OSError, subprocess.SubprocessError): pass
        self.updater = updater.Updater(launcher, resume_path=resume_path)
        try:
            paths, active, self.recent = self.tabs.read()
        except OSError:
            self.tab_warning = "이전에 열었던 저장소 목록을 읽지 못했습니다."
            paths, active, self.recent = [], None, []
        for path in paths:
            try:
                profile, native_path = environments.split_repo(path)
                root = self.environments.call(profile, 'open', {'path': native_path})
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                continue
            if root == native_path:
                self.repos[path] = (root, threading.Lock())
        self.active = active if active in self.repos else next(iter(self.repos), None)

    def remember(self, path, *, closing=False):
        try:
            self.recent = self.tabs.update(path, closing=closing, fallback=self.active)
        except OSError:
            if not closing:
                self.recent = [path] + [p for p in self.recent if p != path]
            self.tab_warning = "열린 탭을 저장하지 못했습니다. 사용자 상태 폴더의 쓰기 권한을 확인하세요."

    def select_tab(self, path):
        with self.registry_lock:
            if path not in self.repos:
                raise ValueError("열려 있는 저장소를 선택하세요.")
            self.active = path
            self.remember(path)

    def close_tab(self, path):
        with self.registry_lock:
            if path in self.repos:
                index = list(self.repos).index(path)
                del self.repos[path]
                remaining = list(self.repos)
                if self.active == path:
                    self.active = remaining[min(index, len(remaining)-1)] if remaining else None
                self.remember(path, closing=True)
            return list(self.repos)

    def forget(self, path):
        if not isinstance(path, str) or len(path)>4096 or "\x00" in path:
            raise ValueError('제거할 저장소 경로를 확인하세요.')
        # No filesystem access or runtime connection: stale/offline paths must also be removable.
        with self.registry_lock:
            remaining = [item for item in self.repos if item != path]
            active = self.active if self.active != path else next(iter(remaining), None)
            recent = self.tabs.update(path, forgetting=True, fallback=active)
            self.repos.pop(path, None)
            self.active = active
            self.recent = recent
            return dict(repos=remaining, active=active, recent=recent)

    def register(self, path, exact=False, profile=None):
        if profile is None:
            profile, path = environments.split_repo(path)
        root = self.environments.call(profile, 'open', {'path': path})
        if exact and root != path:
            raise ValueError("해당 경로에서 이전 저장소를 찾을 수 없습니다.")
        identifier = environments.repo_id(profile, root)
        with self.registry_lock:
            self.repos.setdefault(identifier, (root, threading.Lock()))
            self.active = identifier
            self.remember(self.active)
        return identifier

    def repo_call(self, identifier, op, data):
        root, lock = self.repos[identifier]
        profile, native_path = environments.split_repo(identifier)
        with lock:
            value = self.environments.call(profile, op, dict(data, root=native_path))
            if op == 'state':
                value.update(path=identifier, displayPath=native_path, environment=profile,
                             environmentName=self.environments.get(profile)['name'],
                             environmentPlatform=self.environments.get(profile)['platform'])
            return value


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, body, mime="application/json"):
        if mime == "application/json":
            body = json.dumps(body, ensure_ascii=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") or mime in ("application/json", "application/javascript") else ""))
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
            if self.path == "/api/app-update":
                action = d.get('action', 'status')
                app = self.server.updater
                if action == 'check': value = app.check()
                elif action == 'download': value = app.download(d.get('ticket'))
                elif action == 'apply':
                    ui = d.get('ui', {})
                    if not isinstance(ui, dict): raise ValueError('화면 상태를 확인하세요.')
                    raw_drafts = ui.get('drafts', [])
                    if not isinstance(raw_drafts, list): raise ValueError('입력 상태를 확인하세요.')
                    drafts = []
                    for row in raw_drafts:
                        if not isinstance(row, list) or len(row) != 2: raise ValueError('입력 상태를 확인하세요.')
                        path, message = row
                        if not isinstance(path, str) or not (os.path.isabs(path) or path.startswith('bd:')) or len(path) > 4096 or not isinstance(message, str) or len(message) > 100000:
                            raise ValueError('작성 중인 메시지를 확인한 뒤 다시 적용하세요.')
                        drafts.append([path, message])
                    resume = dict(drafts=drafts, repo=ui.get('repo') if ui.get('repo') in self.server.repos else self.server.active,
                                  mode='work' if ui.get('mode') == 'work' else 'history')
                    value = app.apply(d.get('ticket'), environments.export_ui(resume))
                elif action == 'restart': value = app.restart(d.get('ticket'))
                elif action == 'restore': value = environments.restore_ui(updater.restore_ui_state(app.resume_path))
                elif action == 'status': value = app.status()
                else: raise ValueError('업데이트 작업을 확인하세요.')
            elif self.path == "/api/environments":
                manager = self.server.environments
                action = d.get('action', 'list')
                if action == 'list': value = manager.list()
                elif action == 'save': value = manager.save(d['profile'])
                elif action == 'startup': value = manager.startup(d.get('profile', 'default'))
                elif action == 'probe': value = manager.call(d.get('profile', 'default'), 'probe', {})
                elif action in ('ssh-list', 'ssh-public', 'ssh-generate', 'ssh-test'):
                    value = manager.call(d.get('profile', 'default'), action, d)
                elif action == 'install': value = manager.install(d['kind'], d.get('directory', ''), d.get('distro', ''))
                else: raise ValueError('환경 설정 작업을 확인하세요.')
            elif self.path == "/api/directories":
                value = self.server.environments.call(d.get('profile', 'default'), 'directories', d)
            elif self.path == "/api/open":
                value = self.server.register(d["path"], exact=d.get("exact") is True, profile=d.get('profile'))
            elif self.path == "/api/new":
                profile = d.get('profile', 'default')
                value = self.server.register(self.server.environments.call(profile, 'new', d), profile=profile)
            elif self.path == "/api/forget":
                value = self.server.forget(d["path"])
            elif self.path == "/api/close":
                value = self.server.close_tab(d["repo"])
            elif self.path == "/api/select-tab":
                value = self.server.select_tab(d["repo"])
            elif self.path == "/api/workspace":
                with self.server.registry_lock:
                    value = {"repos": list(self.server.repos), "active": self.server.active}
            elif self.path == "/api/recent":
                with self.server.registry_lock:
                    if not self.server.tab_warning:
                        try:
                            self.server.recent = self.server.tabs.read()[2]
                        except OSError:
                            self.server.tab_warning = "최근 저장소 목록을 읽지 못했습니다."
                    value = list(self.server.recent)
            elif self.path == "/api/repos":
                with self.server.registry_lock:
                    value = list(self.server.repos)
            else:
                op = self.path.removeprefix('/api/')
                if op not in ('state', 'locate-commit', 'switch-plan', 'detail', 'commit-context', 'rebase-plan', 'export', 'diff',
                              'conflict', 'resolve', 'urls', 'remote-websites', 'lines', 'lines-apply', 'action'):
                    return self.reply(404, {})
                value = self.server.repo_call(d['repo'], op, d)
            response = {"value": value}
            if self.server.tab_warning:
                response["warning"] = self.server.tab_warning
            self.reply(200, response)
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
    parser = argparse.ArgumentParser(description="Windows·WSL 저장소용 Git GUI")
    parser.add_argument("repositories", nargs="*", metavar="REPO")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        server = Desk(args.port)
        for path in args.repositories:
            server.register(path)
        if not args.repositories and not server.repos and not server.tabs.file.is_file():
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
