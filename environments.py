"""User-owned execution profiles. Repository paths stay in their native OS."""
from contextlib import contextmanager
from contextvars import ContextVar
import io
import json
import os
import platform
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import uuid
import zipfile

execution_settings = ContextVar('execution_settings', default={})
SOURCES = ('gitdesk.py', 'partial.py', 'workspace_ops.py', 'commit_ops.py', 'environments.py', 'process_utils.py', 'desktop_actions.py', 'updater.py', 'windows/desktop.ps1')


def state_root():
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local') / 'Branchdesk' / 'state'
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'branchdesk'


@contextmanager
def file_lock(file):
    if os.name == 'nt':
        import msvcrt
        file.seek(0); file.write(' '); file.flush(); file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)
        try: yield
        finally:
            file.seek(0); msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(file, fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(file, fcntl.LOCK_UN)


def atomic_json(path, data):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=True); file.flush(); os.fsync(file.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def native_tool(name):
    found = shutil.which(name)
    if found: return found
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home())))
        candidates = {
            'git': [base/'Branchdesk/tools/git/cmd/git.exe', base/'Programs/Git/cmd/git.exe', Path('C:/Program Files/Git/cmd/git.exe')],
            'ssh': [Path(os.environ.get('SystemRoot', 'C:/Windows'))/'System32/OpenSSH/ssh.exe'],
            'ssh-keygen': [Path(os.environ.get('SystemRoot', 'C:/Windows'))/'System32/OpenSSH/ssh-keygen.exe']
        }.get(name, [])
        # Prefer the SSH bundled with the selected Git when Windows OpenSSH is absent.
        if name.startswith('ssh'):
            git = native_tool('git')
            if git: candidates.append(Path(git).parent.parent/'usr/bin'/(name+'.exe'))
        return next((str(path) for path in candidates if path.is_file()), '')
    return ''


def profile_tool(profile, name):
    if name == 'ssh' and profile.get('ssh'): return profile['ssh']
    if name == 'ssh-keygen' and profile.get('ssh'):
        sibling = Path(profile['ssh']).with_name('ssh-keygen.exe' if os.name == 'nt' else 'ssh-keygen')
        if sibling.is_file(): return str(sibling)
    found = native_tool(name)
    if found: return found
    if os.name == 'nt' and profile.get('git'):
        candidate = Path(profile['git']).parent.parent/'usr/bin'/(name+'.exe')
        if candidate.is_file(): return str(candidate)
    return name


def checked_text(value, label, required=False):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value) or (required and not value.strip()):
        raise ValueError(label + '을 확인하세요.')
    return value.strip()


def settings(profile):
    git = profile.get('git') or native_tool('git') or 'git'
    env = {}
    if profile.get('agent') and os.name != 'nt':
        env['SSH_AUTH_SOCK'] = str(Path(profile['agent']).expanduser())
    key = profile.get('key', '')
    if key or profile.get('ssh'):
        ssh = profile_tool(profile, 'ssh')
        args = [ssh.replace('\\', '/'), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes']
        if key:
            key = str(Path(key).expanduser())
            if not Path(key).is_file(): raise ValueError('선택한 SSH 개인키 파일을 찾을 수 없습니다.')
            args += ['-o', 'IdentitiesOnly=yes', '-i', key.replace('\\', '/')]
        env.update(GIT_SSH_COMMAND=' '.join(shlex.quote(arg) for arg in args), GIT_SSH_VARIANT='ssh')
    return {'git': git, 'env': env}


def invoke(op, data, profile):
    """Executed entirely in the selected Python's OS, including all file reads."""
    import gitdesk, partial, workspace_ops, commit_ops
    token = execution_settings.set(settings(profile))
    try:
        if op == 'probe':
            from process_utils import run
            git_path = profile.get('git') or native_tool('git')
            code, out, err = run([git_path or 'git', '--version'], timeout=15)
            version = out.decode(errors='replace').strip()
            match = re.search(r'\b(\d+)\.(\d+)', version)
            if code or not match or tuple(map(int, match.groups())) < (2, 28):
                raise ValueError('Git 2.28 이상이 필요합니다. Git 실행 파일 경로를 확인하세요.')
            return dict(platform=native_platform(), os='windows' if os.name == 'nt' else 'wsl' if os.environ.get('WSL_DISTRO_NAME') else 'linux',
                        distro=os.environ.get('WSL_DISTRO_NAME', ''), python=sys.executable, pythonVersion=sys.version.split()[0],
                        git=git_path or 'git', gitVersion=version, ssh=profile_tool(profile, 'ssh'),
                        keygen=profile_tool(profile, 'ssh-keygen'), home=str(Path.home()), key=profile.get('key', ''))
        if op == 'import-settings': return import_settings(data)
        if op.startswith('ssh-'): return ssh_operation(op, data, profile)
        if op == 'directories': return workspace_ops.directory_suggestions(data.get('path', ''))
        if op == 'open': return str(gitdesk.repository(data['path']))
        if op == 'new': return str(workspace_ops.new_repository(data))
        root = gitdesk.repository(data.get('root', data.get('path')))
        if op == 'locate-commit': return gitdesk.locate_commit(root, data['rev'], data.get('count', 150))
        if op == 'switch-plan': return workspace_ops.switch_plan(root, data['name'])
        if op == 'state': return gitdesk.state(root, data.get('count', 150))
        if op == 'detail': return gitdesk.detail(root, data['rev'], data.get('base'))
        if op == 'diff': return gitdesk.diff(root, data)
        if op == 'commit-context': return commit_ops.context(root, data['rev'])
        if op == 'rebase-plan': return commit_ops.rebase_plan(root, data['rev'])
        if op == 'export': return commit_ops.export(root, data)
        if op == 'urls': return workspace_ops.remote_urls(root)
        if op == 'remote-websites': return workspace_ops.remote_websites(root)
        if op in ('conflict', 'resolve'): return partial.conflict_file(root, data, resolve=op == 'resolve')
        if op in ('lines', 'lines-apply'): return partial.partial(root, data, apply=op == 'lines-apply')
        if op == 'action': return gitdesk.act(root, data)
        raise ValueError('지원하지 않는 작업입니다.')
    finally: execution_settings.reset(token)


def ssh_operation(op, data, profile):
    from process_utils import run
    directory = Path.home()/'.ssh'
    keygen = profile_tool(profile, 'ssh-keygen')
    if op == 'ssh-list':
        return [dict(path=str(path.with_suffix('')), public=str(path)) for path in sorted(list(directory.glob('*.pub')) + list(directory.glob('branchdesk-*/*.pub')))
                if path.with_suffix('').is_file()][:100]
    if op == 'ssh-generate':
        name = data.get('name', '')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,70}', name):
            raise ValueError('키 이름은 영문·숫자·점·밑줄·하이픈을 사용하세요.')
        if data.get('unprotected') is not True:
            raise ValueError('앱에서 생성하는 키는 암호가 없습니다. 암호로 보호할 키는 터미널에서 생성한 뒤 연결하세요.')
        directory.mkdir(mode=0o700, exist_ok=True)
        # Reserve a directory exclusively before invoking keygen: no overwrite prompt or race with existing keys.
        keydir = directory/('branchdesk-' + name)
        keydir.mkdir(mode=0o700)
        path = keydir/'id_ed25519'
        comment = checked_text(data.get('comment', 'Branchdesk'), '설명')
        code, out, err = run([keygen, '-t', 'ed25519', '-f', str(path), '-N', '', '-C', comment], timeout=30)
        if code:
            if not any(keydir.iterdir()): keydir.rmdir()
            raise ValueError('SSH 키 생성에 실패했습니다: ' + err.decode(errors='replace')[:2000])
        return dict(path=str(path), public=public_key(str(path)))
    if op == 'ssh-public': return public_key(data.get('key') or profile.get('key', ''))
    if op == 'ssh-test':
        host = data.get('host', '')
        if host not in ('github.com', 'gitlab.com', 'bitbucket.org'):
            raise ValueError('연결 확인은 GitHub·GitLab.com·Bitbucket을 지원합니다. 사내 서버는 터미널에서 확인하세요.')
        ssh = profile_tool(profile, 'ssh')
        args = [ssh, '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10']
        if profile.get('key'): args += ['-o', 'IdentitiesOnly=yes', '-i', str(Path(profile['key']).expanduser())]
        code, out, err = run(args + ['git@'+host], timeout=20, limit=16000,
                             env=dict(os.environ, **settings(profile)['env']))
        message = (out+err).decode(errors='replace').strip()
        authenticated = (host == 'github.com' and code == 1 and 'successfully authenticated' in message) or (host == 'gitlab.com' and code == 0) or (host == 'bitbucket.org' and code == 0)
        return dict(authenticated=authenticated, message=message, hint='' if authenticated else
                    '호스트 키가 등록되지 않았다면 해당 환경의 터미널에서 ssh -T git@'+host+'를 실행해 공식 지문을 확인하세요. 암호가 있는 키는 해당 환경의 ssh-agent에 먼저 등록하세요.')
    raise ValueError('SSH 작업을 확인하세요.')


def public_key(key):
    key = checked_text(key, '개인키 경로', True)
    path = Path(key).expanduser()
    if path.suffix == '.pub': path = path.with_suffix('')
    public = Path(str(path)+'.pub')
    if public.stat().st_size > 16000: raise ValueError('공개키 파일 크기를 확인하세요.')
    content = public.read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'(ssh-(?:ed25519|rsa)|ecdsa-sha2-\S+) [A-Za-z0-9+/=]+(?: [^\r\n]*)?', content):
        raise ValueError('올바른 SSH 공개키(.pub)가 아닙니다.')
    return content


def import_settings(data):
    """Merge tool paths and tab references when changing the app host; never copy key material."""
    folder = state_root(); folder.mkdir(parents=True, exist_ok=True)
    with (folder/'environments.lock').open('a+') as lock, file_lock(lock):
        path = folder/'environments.json'
        try: previous = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError: previous = {}
        previous.update(data['profiles'])
        atomic_json(path, previous)
    with (folder/'tabs.lock').open('a+') as lock, file_lock(lock):
        path = folder/'tabs.json'
        try: previous = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError: previous = {}
        repos = list(dict.fromkeys(previous.get('repos', []) + data.get('repos', [])))
        recent = list(dict.fromkeys(data.get('recent', []) + previous.get('recent', []) + repos))
        atomic_json(path, dict(repos=repos, recent=recent, active=data.get('active') or previous.get('active')))
    return True


def worker_main():
    request = json.loads(sys.stdin.buffer.readline(2_000_001))
    try:
        if sys.version_info < (3, 9): raise ValueError('Python 3.9 이상이 필요합니다.')
        result = {'value': invoke(request['op'], request['data'], request['profile'])}
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        result = {'error': str(error)}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=True).encode('ascii'))
    sys.stdout.buffer.flush()


class Environments:
    def __init__(self):
        self.file = state_root()/'environments.json'
        self.lock = threading.RLock()
        self.install_state = {'state': 'idle'}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in SOURCES: archive.writestr(name, (Path(__file__).parent/name).read_bytes())
        self.payload = buf.getvalue()
        self.profiles = self.read()
        self._windows_root = None
        self.default_git = native_tool('git')
        if os.name == 'nt' and 'default' not in self.profiles:
            try:
                host = json.loads((Path(os.environ.get('LOCALAPPDATA', ''))/'Branchdesk/host.json').read_text(encoding='utf-8-sig'))
                if host.get('kind') == 'windows' and host.get('git'):
                    self.default_git = host['git']
            except (OSError, ValueError): pass

    def read(self):
        try:
            value = json.loads(self.file.read_text(encoding='utf-8'))
            if not isinstance(value, dict): raise ValueError()
            return value
        except FileNotFoundError: return {}
        except (ValueError, UnicodeError):
            raise ValueError('실행 환경 설정 파일을 읽을 수 없습니다: ' + str(self.file))

    def get(self, identifier='default'):
        if identifier == 'default':
            profile = dict(dict(id='default', name='', kind='local', python=sys.executable,
                             git=self.default_git, ssh='', key=''), **self.profiles.get('default', {}))
        else:
            if identifier not in self.profiles: raise ValueError('실행 환경을 찾을 수 없습니다. 환경 설정을 확인하세요.')
            profile = dict(self.profiles[identifier])
        if profile['kind'] == 'local':
            profile.update(platform=native_platform(), distro=os.environ.get('WSL_DISTRO_NAME', ''))
        else:
            profile.setdefault('platform', 'Windows' if profile['kind'] == 'windows' else 'WSL')
        if not profile.get('name') or profile['name'] == '현재 실행 환경':
            profile['name'] = profile['platform'] + (' · ' + profile['distro'] if profile.get('distro') else '')
        return profile

    def windows_root(self):
        if self._windows_root is not None: return self._windows_root
        if os.name == 'nt':
            self._windows_root = str(Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData/Local')/'Branchdesk')
        elif shutil.which('powershell.exe'):
            from process_utils import run
            code, out, _ = run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                "[Console]::OutputEncoding=[Text.Encoding]::UTF8;[Environment]::GetFolderPath('LocalApplicationData')"], timeout=15)
            if not code: self._windows_root = out.decode('utf-8-sig').strip() + '/Branchdesk'
        return self._windows_root or ''

    def startup(self, identifier):
        profile = self.get(identifier)
        probe = self.call(identifier, 'probe', {})
        base = self.windows_root()
        if not base: raise ValueError('Windows 시작 설정에 접근할 수 없습니다.')
        from updater import wsl_path
        destination = Path(wsl_path(base))/'host.json'
        if probe['os'] == 'windows':
            data = dict(kind='windows', python=probe['python'], git=probe['git'])
        elif probe['os'] == 'wsl':
            # The launcher uses the system default WSL distribution, retaining existing behavior.
            from process_utils import run
            code, output, error = run(['wsl.exe', '--exec', 'printenv', 'WSL_DISTRO_NAME'], timeout=30)
            if code or output.decode('utf-8', errors='replace').strip() != probe['distro']:
                raise ValueError('앱 시작용 WSL은 기본 배포판을 사용합니다. 기본 WSL 환경을 선택하세요.')
            data = dict(kind='wsl')
        else: raise ValueError('앱 시작은 Windows 또는 WSL 환경을 선택하세요.')
        current_os = 'windows' if os.name == 'nt' else 'wsl' if os.environ.get('WSL_DISTRO_NAME') else 'linux'
        if current_os != probe['os']:
            default_id = default_profile_id()
            profiles = {}
            for item in self.list()['profiles']:
                item = dict(item)
                if item['id'] == 'default': item['id'] = default_id
                if item['kind'] == 'local':
                    item['kind'] = current_os
                    item['distro'] = os.environ.get('WSL_DISTRO_NAME', '')
                profiles[item['id']] = item
            from tab_store import TabStore
            repos, active, recent = TabStore().read()
            def translate(value):
                if not value: return value
                kind, path = split_repo(value)
                return repo_id(default_id if kind == 'default' else kind, path)
            self.call(identifier, 'import-settings', dict(profiles=profiles, repos=list(map(translate, repos)),
                       recent=list(map(translate, recent)), active=translate(active)))
        atomic_json(destination, data)
        return '다음 앱 실행부터 ' + ('Windows 단독' if data['kind']=='windows' else '기본 WSL') + ' 환경으로 시작합니다.'

    def list(self):
        with self.lock:
            return dict(profiles=[self.get('default')] + [self.get(k) for k in self.profiles if k != 'default'],
                        os='windows' if os.name == 'nt' else 'wsl' if os.environ.get('WSL_DISTRO_NAME') else 'linux',
                        install=dict(self.install_state), windowsRoot=self.windows_root())

    def command(self, profile):
        python = profile.get('python') or (sys.executable if profile['kind'] == 'local' else 'python.exe' if profile['kind'] == 'windows' else 'python3')
        bootstrap = ('import io,os,sys,tempfile,zipfile,struct;'
                     "os.name=='nt' and (__import__('msvcrt').setmode(sys.stdin.fileno(),os.O_BINARY),__import__('msvcrt').setmode(sys.stdout.fileno(),os.O_BINARY));"
                     'n=struct.unpack("<I",sys.stdin.buffer.read(4))[0];'
                     'd=tempfile.TemporaryDirectory(prefix="branchdesk-worker-");'
                     'z=zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read(n)));z.extractall(d.name);z.close();'
                     'sys.path.insert(0,d.name);import environments;environments.worker_main();d.cleanup()')
        command = [python, '-I', '-u', '-c', bootstrap]
        if profile['kind'] == 'wsl':
            distro = profile.get('distro', '')
            return ['wsl.exe'] + (['--distribution', distro] if distro else []) + ['--exec'] + command
        if profile['kind'] == 'windows' and os.name != 'nt':
            # WSL interoperability takes a Linux mount path for the executable only; its argv stays Windows-native.
            if re.match(r'^[A-Za-z]:[\\/]', python):
                python = subprocess.check_output(['wslpath', '-u', python], text=True, timeout=10).strip()
                command[0] = python
        return command

    def call(self, identifier, op, data):
        with self.lock: profile = self.get(identifier)
        return self.execute(profile, op, data)

    def execute(self, profile, op, data):
        if profile['kind'] == 'local' and os.path.normcase(profile.get('python') or sys.executable) == os.path.normcase(sys.executable):
            return invoke(op, data, profile)
        from process_utils import run
        request = json.dumps(dict(op=op, data=data, profile=profile), ensure_ascii=True).encode('ascii') + b'\n'
        payload = struct.pack('<I', len(self.payload)) + self.payload + request
        timeout = 45 if op in ('probe', 'open', 'directories') else 660 if op in ('new', 'action') else 120
        code, out, err = run(self.command(profile), data=payload, timeout=timeout, limit=32*1024*1024)
        if code: raise ValueError('선택한 Python을 실행하지 못했습니다. 경로와 Windows/WSL 환경을 확인하세요. ' + err.decode(errors='replace')[:2000])
        try: reply = json.loads(out)
        except ValueError as error: raise ValueError('실행 환경에서 올바른 응답을 받지 못했습니다. Python 3.9 이상인지 확인하세요.') from error
        if 'error' in reply: raise ValueError(reply['error'])
        return reply['value']

    def discover_python(self, profile):
        kind = profile['kind']
        if kind == 'local' or (kind == 'windows' and os.name == 'nt') or (kind == 'wsl' and os.environ.get('WSL_DISTRO_NAME') and profile.get('distro') == os.environ['WSL_DISTRO_NAME']):
            return sys.executable
        if kind == 'windows':
            from process_utils import run
            powershell = shutil.which('powershell.exe')
            if powershell:
                # Fixed discovery script; no profile or repository text becomes PowerShell source.
                script = r"[Console]::OutputEncoding=[Text.Encoding]::UTF8;$p=@();$p+=Join-Path $env:LOCALAPPDATA 'Branchdesk/tools/python/python.exe';$c=Get-Command python.exe -ErrorAction SilentlyContinue;if($c){$p+=$c.Source};foreach($h in @('HKCU:\Software\Python\PythonCore','HKLM:\Software\Python\PythonCore')){Get-ChildItem $h -ErrorAction SilentlyContinue|ForEach-Object{$v=Get-ItemProperty ($_.PSPath+'\InstallPath') -ErrorAction SilentlyContinue;if($v.ExecutablePath){$p+=$v.ExecutablePath}}};@($p|Where-Object{$_ -notlike '*\WindowsApps\*' -and (Test-Path -LiteralPath $_ -PathType Leaf)}|Select-Object -Unique)|ConvertTo-Json -Compress"
                code, output, error = run([powershell, '-NoProfile', '-NonInteractive', '-Command', script], timeout=20, limit=32000)
                if not code and output.strip():
                    paths = json.loads(output.decode('utf-8-sig'))
                    if isinstance(paths, str): paths = [paths]
                    if isinstance(paths, list) and paths: return paths[0]
            return 'python.exe'
        return 'python3'

    def save(self, raw):
        kind = raw.get('kind')
        identifier = raw.get('id') or uuid.uuid4().hex
        if kind not in ('local', 'windows', 'wsl') or not re.fullmatch(r'(?:default|[0-9a-f]{32})', identifier):
            raise ValueError('실행 환경을 확인하세요.')
        profile = {field: checked_text(raw.get(field, ''), field, required=field=='name')
                   for field in ('name', 'python', 'git', 'ssh', 'key', 'distro', 'agent')}
        profile.update(id=identifier, kind=kind)
        if identifier == 'default' and kind != 'local': raise ValueError('현재 실행 환경의 종류는 변경할 수 없습니다. 새 환경을 추가하세요.')
        if not profile['python']: profile['python'] = self.discover_python(profile)
        # Verify before publishing. Existing open repositories keep their saved configuration on failure.
        probe = self.execute(profile, 'probe', {})
        expected = 'windows' if kind == 'windows' else 'wsl' if kind == 'wsl' else None
        if expected and probe['os'] != expected:
            raise ValueError('선택한 Python이 실행 환경과 일치하지 않습니다.')
        profile.update(python=probe['python'], git=probe['git'], platform=probe['platform'],
                       distro=probe.get('distro', profile['distro']), pythonVersion=probe['pythonVersion'], gitVersion=probe['gitVersion'])
        with self.lock:
            folder = self.file.parent; folder.mkdir(parents=True, exist_ok=True)
            with (folder/'environments.lock').open('a+') as lock, file_lock(lock):
                latest = self.read(); latest[identifier] = profile
                atomic_json(self.file, latest); self.profiles = latest
        return dict(profile=profile, probe=probe)

    def install(self, kind, directory='', distro=''):
        if kind not in ('windows', 'wsl'): raise ValueError('설치 환경을 선택하세요.')
        directory = checked_text(directory, '설치 경로', required=kind=='windows')
        distro = checked_text(distro, 'WSL 배포판')
        powershell = native_tool('powershell.exe')
        if not powershell: raise ValueError('Windows PowerShell을 찾을 수 없습니다. 직접 설치한 실행 파일 경로를 연결하세요.')
        with self.lock:
            if self.install_state['state'] == 'running': raise ValueError('설치가 이미 진행 중입니다.')
            self.install_state = dict(state='running', message='설치 창에서 진행 상황을 확인하세요.')
        def task():
            folder = Path(tempfile.mkdtemp(prefix='branchdesk-tools-'))
            try:
                script = folder/'tools.ps1'
                script.write_bytes(b'\xef\xbb\xbf' + (Path(__file__).parent/'windows/tools.ps1').read_bytes())
                from updater import wsl_path
                target = wsl_path(str(script), windows=True)
                # Start a visible helper, keep this app usable while package managers run.
                command = [powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', target,
                           '-Kind', kind, '-Directory', directory, '-Distro', distro]
                result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        timeout=1800, **({'creationflags': subprocess.CREATE_NEW_CONSOLE} if os.name == 'nt' else {}))
                if result.returncode: raise ValueError('설치가 완료되지 않았습니다. 설치 창 안내 또는 직접 설치 경로를 확인하세요.')
                with self.lock: self.install_state = dict(state='done', message='설치가 끝났습니다. 경로를 연결하고 확인·저장하세요.')
            except Exception as error:
                with self.lock: self.install_state = dict(state='error', message=str(error))
            finally: shutil.rmtree(folder, ignore_errors=True)
        threading.Thread(target=task, daemon=True).start()
        return self.list()['install']


def split_repo(value):
    if value.startswith('bd:'):
        _, identifier, path = value.split(':', 2)
        if not re.fullmatch('[0-9a-f]{32}', identifier): raise ValueError('저장소 환경을 확인하세요.')
        return identifier, path
    return 'default', value


def native_platform():
    if os.name == 'nt': return 'Windows'
    if os.environ.get('WSL_DISTRO_NAME'):
        return 'WSL2' if 'wsl2' in platform.release().lower() else 'WSL'
    return 'Linux'


def host_kind():
    return 'windows' if os.name == 'nt' else 'wsl' if os.environ.get('WSL_DISTRO_NAME') else 'linux'


def default_profile_id():
    return uuid.uuid5(uuid.NAMESPACE_URL, host_kind() + str(Path.home()) + sys.executable + os.environ.get('WSL_DISTRO_NAME', '')).hex


def export_ui(data):
    return dict(data, sourceHost=host_kind(), sourceProfile=default_profile_id())


def restore_ui(data):
    if data.get('sourceHost') and data['sourceHost'] != host_kind() and re.fullmatch('[0-9a-f]{32}', data.get('sourceProfile', '')):
        def translate(value):
            if not isinstance(value, str) or not value: return value
            identifier, path = split_repo(value)
            return repo_id(data['sourceProfile'], path) if identifier == 'default' else value
        data = dict(data, repo=translate(data.get('repo')), drafts=[[translate(path), message] for path, message in data.get('drafts', [])])
    return data


def repo_id(identifier, path):
    return path if identifier == 'default' else 'bd:'+identifier+':'+path
