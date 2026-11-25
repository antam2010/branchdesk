"""Open Windows desktop applications through a visible-window-aware helper."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def open_windows(action, root=None, url=None):
    from updater import wsl_path
    from process_utils import run
    powershell = shutil.which('powershell.exe')
    if not powershell:
        raise ValueError('Windows PowerShell을 찾지 못했습니다. Windows 실행 연동과 PATH를 확인하세요.')
    request = dict(action=action, path='', nativePath=str(root or ''), distro=os.environ.get('WSL_DISTRO_NAME', ''), url=url or '')
    if root is not None:
        request['path'] = wsl_path(str(root), windows=True)
    with tempfile.TemporaryDirectory(prefix='branchdesk-desktop-') as directory:
        folder = Path(directory)
        script = folder/'desktop.ps1'
        script.write_bytes(b'\xef\xbb\xbf' + (Path(__file__).parent/'windows/desktop.ps1').read_bytes())
        from language import copy_windows_translations
        copy_windows_translations(folder)
        source = folder/'request.json'; result = folder/'result.json'
        source.write_text(json.dumps(request, ensure_ascii=True), encoding='utf-8')
        code, out, err = run([powershell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
            wsl_path(str(script), windows=True), '-RequestFile', wsl_path(str(source), windows=True),
            '-ResultFile', wsl_path(str(result), windows=True)], timeout=35, limit=64000)
        try: reply = json.loads(result.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            raise ValueError('Windows 창을 열지 못했습니다. ' + err.decode(errors='replace')[:2000])
        if code or reply.get('error'): raise ValueError(reply.get('error') or 'Windows 실행 요청이 실패했습니다.')
        return reply
