import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error

import updater


def executable(marker):
    data = bytearray(512)
    data[:2] = b'MZ'; struct.pack_into('<I', data, 60, 128)
    data[128:132] = b'PE\0\0'; struct.pack_into('<H', data, 132, 0x8664)
    data[-1] = marker
    return bytes(data)


class UpdaterTests(unittest.TestCase):
    def test_powershell_helper_updates_existing_pointer_and_recovers_from_failures(self):
        powershell = os.environ.get('BRANCHDESK_POWERSHELL') or shutil.which('powershell.exe') or shutil.which('pwsh')
        if not powershell: self.skipTest('PowerShell is required for real helper filesystem checks')
        script = Path(__file__).resolve().parents[1] / 'windows/test-update.ps1'
        result = subprocess.run([powershell, '-NoProfile', '-File', str(script)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS:', result.stdout)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.current = self.root / 'Branchdesk.exe'; self.current.write_bytes(executable(1))
        self.signal = self.root / 'update.signal'
        self.readme = self.root / 'README.md'; self.readme.write_text('local notes\n')
        self.app = updater.Updater(dict(pid=12, path=str(self.current), signal=str(self.signal)))
        self.target = executable(2)
        self.blob = updater.git_blob_sha(self.target)
        self.env = patch.dict(os.environ, XDG_STATE_HOME=str(self.root / 'state')); self.env.start(); self.addCleanup(self.env.stop)
        self.mapping = patch('updater.wsl_path', side_effect=lambda path, windows=False: path); self.mapping.start(); self.addCleanup(self.mapping.stop)
        self.api = patch('updater.get_json', side_effect=self.response); self.api.start(); self.addCleanup(self.api.stop)
        self.addCleanup(lambda: updater.shutil.rmtree(self.app.folder, ignore_errors=True) if self.app.folder else None)

    def response(self, path, **kwargs):
        if path == '/commits/main':
            return dict(sha='a'*40, commit=dict(tree=dict(sha='b'*40), message='Update app\nDetails', committer=dict(date='2026-11-25T00:00:00Z')))
        if path == '/git/trees/' + 'b'*40:
            return dict(tree=[dict(path='Branchdesk.exe', type='blob', sha=self.blob, size=len(self.target))])
        if path == '/git/blobs/' + self.blob:
            return dict(encoding='base64', content=base64.b64encode(self.target).decode())
        raise AssertionError(path)

    def finished(self):
        self.app.worker.join(5)
        self.assertFalse(self.app.worker.is_alive())
        return self.app.status()

    def ready(self):
        self.app.check(); result = self.finished()
        self.app.download(result['ticket'])
        self.assertEqual(self.finished()['state'], 'ready')
        return result['ticket']

    def test_background_download_does_not_touch_source_or_close_app(self):
        started, release = threading.Event(), threading.Event()
        def request(path, **kw):
            if path.startswith('/git/blobs/'):
                started.set(); release.wait(3)
            return self.response(path, **kw)
        with patch('updater.get_json', side_effect=request):
            self.app.check(); available = self.finished()
            self.assertEqual(available['state'], 'available')
            self.app.download(available['ticket']); self.assertTrue(started.wait(1))
            self.assertEqual(self.app.status()['state'], 'downloading')
            self.assertFalse(self.signal.exists())
            release.set(); ready = self.finished()
        self.assertEqual(ready['state'], 'ready')
        self.assertEqual((self.app.folder / 'Branchdesk.exe').read_bytes(), self.target)
        self.assertTrue((self.app.folder / 'update.ps1').read_bytes().startswith(b'\xef\xbb\xbf'))
        self.assertEqual(self.current.read_bytes(), executable(1))
        self.assertEqual(self.readme.read_text(), 'local notes\n')

    def test_shared_resume_path_and_legacy_fallback(self):
        legacy = dict(drafts=[['/repo', 'old draft']])
        updater.save_ui_state(legacy)
        shared = self.root/'WindowsState/resume-ui.json'
        self.assertEqual(updater.restore_ui_state(shared), legacy)
        current = dict(drafts=[['/repo', 'new draft']])
        updater.save_ui_state(current, shared)
        self.assertEqual(updater.restore_ui_state(shared), current)
        self.assertFalse(shared.exists())

    def test_current_binary_and_unsupported_source_mode(self):
        self.current.write_bytes(self.target)
        self.app.check(); self.assertEqual(self.finished()['state'], 'current')
        self.assertEqual(updater.Updater().check()['state'], 'unsupported')

    def test_wrong_ticket_and_tampered_download_are_rejected(self):
        self.app.check(); result = self.finished()
        with self.assertRaises(ValueError): self.app.download('wrong-ticket')
        original = self.response
        def damaged(path, **kwargs):
            if path.startswith('/git/blobs/'): return dict(encoding='base64', content=base64.b64encode(executable(3)).decode())
            return original(path, **kwargs)
        with patch('updater.get_json', side_effect=damaged):
            self.app.download(result['ticket']); self.assertEqual(self.finished()['state'], 'error')
        self.assertFalse(self.signal.exists())
        self.assertEqual(self.current.read_bytes(), executable(1))

    def test_network_failure_leaves_current_app_intact(self):
        with patch('updater.get_json', side_effect=urllib.error.URLError('offline')):
            self.app.check(); result = self.finished()
        self.assertEqual(result['state'], 'error'); self.assertIn('연결', result['message'])
        self.assertFalse(self.signal.exists())

    def test_apply_waits_for_helper_then_explicit_restart_and_restores_draft(self):
        ticket = self.ready()
        ui = dict(drafts=[['/repo', 'unsaved commit message']], mode='work', repo='/repo')
        def launch(args, **kwargs):
            self.assertEqual(args[0], 'powershell.exe')
            request = json.loads((self.app.folder / 'request.json').read_text())
            self.assertEqual(request['parentPid'], 12)
            self.assertEqual(request['sha256'], hashlib.sha256(self.target).hexdigest())
            Path(str(self.signal) + '.helper').write_text('ready')
        with patch('updater.shutil.which', return_value='powershell.exe'), patch('updater.subprocess.Popen', side_effect=launch):
            self.assertEqual(self.app.apply(ticket, ui)['state'], 'restarting')
        self.assertFalse(self.signal.exists())
        self.app.restart(ticket); self.assertTrue(self.signal.exists())
        self.assertEqual(updater.restore_ui_state(), ui)
        self.assertEqual(updater.restore_ui_state(), {})
        self.assertEqual(self.readme.read_text(), 'local notes\n')

    def test_helper_failure_does_not_signal_shutdown(self):
        ticket = self.ready()
        def failure(*args, **kwargs): Path(str(self.signal) + '.error').write_text('helper failed')
        with patch('updater.shutil.which', return_value='powershell.exe'), patch('updater.subprocess.Popen', side_effect=failure):
            with self.assertRaisesRegex(ValueError, 'helper failed'): self.app.apply(ticket, {})
        self.assertEqual(self.app.status()['state'], 'error')
        self.assertFalse(self.signal.exists())

    def test_rejects_non_windows_binary(self):
        with self.assertRaises(ValueError): updater.verify_executable(b'not executable')
        data = bytearray(executable(1)); struct.pack_into('<H', data, 132, 0x14c)
        with self.assertRaises(ValueError): updater.verify_executable(data)

    def test_failed_restart_signal_is_retryable_without_shutdown(self):
        self.app.state.update(state='restarting', ticket='ready')
        with patch('updater.wsl_path', side_effect=OSError('offline path')):
            with self.assertRaises(ValueError): self.app.restart('ready')
        self.assertEqual(self.app.status()['state'], 'error')
        self.assertFalse(self.signal.exists())

    def test_large_draft_does_not_replace_saved_resume_state(self):
        updater.save_ui_state({'drafts': [['/repo', 'keep this']]})
        with self.assertRaises(ValueError): updater.save_ui_state({'drafts': [['/repo', 'x' * 1_000_000]]})
        self.assertEqual(updater.restore_ui_state(), {'drafts': [['/repo', 'keep this']]})
