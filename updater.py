"""Download verified app binaries without pulling or modifying a user's Git worktree."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

API = 'https://api.github.com/repos/antam2010/branchdesk'
MAX_EXE = 32 * 1024 * 1024


def git_blob_sha(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()


def verify_executable(data):
    if not 256 <= len(data) <= MAX_EXE or data[:2] != b'MZ':
        raise ValueError('업데이트 실행 파일 형식을 확인할 수 없습니다.')
    pe = struct.unpack_from('<I', data, 60)[0]
    if pe > len(data) - 26 or data[pe:pe+4] != b'PE\0\0' or struct.unpack_from('<H', data, pe+4)[0] != 0x8664:
        raise ValueError('Windows x64 업데이트 파일이 아닙니다.')


def get_json(path, limit=1024*1024):
    request = urllib.request.Request(API + path, headers={'User-Agent': 'Branchdesk-Updater', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=25) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('업데이트 응답이 크기 제한을 초과했습니다.')
    return json.loads(data)


def wsl_path(path, windows=False):
    if os.name == 'nt': return path
    return subprocess.check_output(['wslpath', '-w' if windows else '-u', path], text=True, timeout=10,
                                   stdin=subprocess.DEVNULL, stderr=subprocess.PIPE).strip()


def state_root():
    from environments import state_root as root
    return root()


def save_ui_state(data, path=None):
    payload = json.dumps(data, ensure_ascii=True)
    if len(payload.encode('utf-8')) > 1_000_000:
        raise ValueError('작성 중인 메시지가 너무 큽니다. 메시지를 저장한 뒤 업데이트를 적용하세요.')
    path = path or state_root() / 'update-ui.json'
    folder = path.parent; folder.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='update-ui-', dir=folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            file.write(payload)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def restore_ui_state(path=None):
    if path is None or not path.exists(): path = state_root() / 'update-ui.json'
    try:
        if path.stat().st_size > 1_000_000: return {}
        data = json.loads(path.read_text(encoding='utf-8'))
        path.unlink()
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


class Updater:
    def __init__(self, launcher=None, resume_path=None):
        self.launcher = launcher or {}
        self.resume_path = resume_path
        self.supported = bool(self.launcher.get('pid', 0) > 0 and self.launcher.get('path') and self.launcher.get('signal'))
        self.lock = threading.RLock()
        self.state = {'state': 'idle', 'supported': self.supported}
        self.release = None
        self.folder = None
        self.worker = None

    def status(self):
        with self.lock: return dict(self.state)

    def _set(self, **values):
        with self.lock: self.state.update(values)

    def _run(self, function):
        def task():
            try: function()
            except Exception as error:
                message = '업데이트 서버에 연결하지 못했습니다. 인터넷 연결이나 GitHub API 이용 한도를 확인하세요.' if isinstance(error, (urllib.error.URLError, urllib.error.HTTPError)) else str(error)
                self._set(state='error', message=message)
        self.worker = threading.Thread(target=task, daemon=True)
        self.worker.start()

    def check(self):
        with self.lock:
            if not self.supported:
                self._set(state='unsupported', message='자동 업데이트는 Windows EXE로 실행할 때 사용할 수 있습니다.')
            elif self.state['state'] not in ('checking', 'downloading', 'applying', 'restarting'):
                if self.folder:
                    shutil.rmtree(self.folder, ignore_errors=True); self.folder = None
                self.state = dict(state='checking', supported=True)
                self._run(self._check)
            return self.status()

    def _check(self):
        commit = get_json('/commits/main')
        sha, tree_sha = commit['sha'], commit['commit']['tree']['sha']
        if not all(isinstance(value, str) and re.fullmatch('[0-9a-f]{40}', value) for value in (sha, tree_sha)):
            raise ValueError('업데이트 버전 정보를 확인할 수 없습니다.')
        tree = get_json('/git/trees/' + tree_sha)
        entry = next((entry for entry in tree['tree'] if entry.get('path') == 'Branchdesk.exe' and entry.get('type') == 'blob'), None)
        if not entry or not re.fullmatch('[0-9a-f]{40}', entry.get('sha', '')) or not 256 <= entry.get('size', 0) <= MAX_EXE:
            raise ValueError('배포 실행 파일을 찾을 수 없습니다.')
        current = Path(wsl_path(self.launcher['path']))
        if current.stat().st_size > MAX_EXE: raise ValueError('현재 실행 파일 크기를 확인하세요.')
        digest = git_blob_sha(current.read_bytes())
        self.release = dict(commit=sha, blob=entry['sha'], size=entry['size'])
        self._set(state='current' if digest == entry['sha'] else 'available', ticket=secrets.token_urlsafe(32),
                  commit=sha, summary=commit['commit']['message'].splitlines()[0], date=commit['commit']['committer']['date'])

    def download(self, ticket):
        with self.lock:
            self._require('available', ticket)
            self._set(state='downloading')
            self._run(self._download)
            return self.status()

    def _require(self, state, ticket):
        if self.state['state'] != state or not isinstance(ticket, str) or ticket != self.state.get('ticket'):
            raise ValueError('업데이트 상태가 바뀌었습니다. 다시 확인하세요.')

    def _download(self):
        result = get_json('/git/blobs/' + self.release['blob'], limit=MAX_EXE * 2)
        if result.get('encoding') != 'base64': raise ValueError('업데이트 인코딩을 확인할 수 없습니다.')
        data = base64.b64decode(''.join(result['content'].split()), validate=True)
        if len(data) != self.release['size'] or git_blob_sha(data) != self.release['blob']:
            raise ValueError('업데이트 파일 검증에 실패했습니다. 현재 앱을 계속 사용할 수 있습니다.')
        verify_executable(data)
        self.folder = Path(tempfile.mkdtemp(prefix='branchdesk-update-'))
        (self.folder / 'Branchdesk.exe').write_bytes(data)
        (self.folder / 'update.ps1').write_bytes(b'\xef\xbb\xbf' + (Path(__file__).parent / 'windows/update.ps1').read_bytes())
        from language import copy_windows_translations
        copy_windows_translations(self.folder)
        self._set(state='ready', sha256=hashlib.sha256(data).hexdigest())

    def apply(self, ticket, ui_state):
        with self.lock:
            self._require('ready', ticket)
            powershell = shutil.which('powershell.exe')
            if not powershell: raise ValueError('Windows 업데이트 도우미를 실행할 수 없습니다. WSL의 Windows 실행 연동을 확인하세요.')
            self._set(state='applying')
        request = dict(parentPid=self.launcher['pid'], launcher=self.launcher['path'], signal=self.launcher['signal'],
                       source=wsl_path(str(self.folder / 'Branchdesk.exe'), windows=True), sha256=self.state['sha256'])
        request_path = self.folder / 'request.json'
        request_path.write_text(json.dumps(request, ensure_ascii=True), encoding='utf-8')
        ready = Path(wsl_path(self.launcher['signal'] + '.helper'))
        error_file = Path(wsl_path(self.launcher['signal'] + '.error'))
        try:
            subprocess.Popen([powershell, '-NoProfile', '-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass', '-File',
                              wsl_path(str(self.folder / 'update.ps1'), windows=True), '-RequestFile',
                              wsl_path(str(request_path), windows=True)], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            deadline = time.monotonic() + 15
            while not ready.exists():
                if error_file.exists(): raise ValueError(error_file.read_text(encoding='utf-8-sig').strip())
                if time.monotonic() > deadline: raise ValueError('업데이트 도우미를 시작하지 못했습니다. 현재 앱은 계속 사용할 수 있습니다.')
                time.sleep(0.1)
            save_ui_state(ui_state, self.resume_path)
            self._set(state='restarting')
            return self.status()
        except Exception as error:
            Path(wsl_path(self.launcher['signal'] + '.cancel')).write_text('cancel', encoding='ascii')
            self._set(state='error', message=str(error))
            raise

    def restart(self, ticket):
        with self.lock:
            self._require('restarting', ticket)
            # The launcher closes only its own app window; Git worktrees stay untouched.
            try:
                Path(wsl_path(self.launcher['signal'])).write_text('restart', encoding='ascii')
            except (OSError, subprocess.SubprocessError) as error:
                self._set(state='error', message='앱을 다시 시작하지 못했습니다. 업데이트를 다시 확인하세요.')
                raise ValueError(self.state['message']) from error
            return self.status()
