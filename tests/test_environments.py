"""Integration checks for native paths, tool selection, worker transport and SSH key safety."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import environments
import gitdesk
from branchdesk import Desk
from process_utils import run
from tab_store import TabStore


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.env = patch.dict(os.environ, HOME=str(self.folder), XDG_STATE_HOME=str(self.folder/'state'))
        self.env.start()
        self.manager = environments.Environments()
        self.repo = self.folder/'repo with 한글'
        self.repo.mkdir()
        subprocess.run(['git', '-C', str(self.repo), 'init', '-b', 'main'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.repo), 'config', 'user.name', 'Tester'], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'config', 'user.email', 'test@example.invalid'], check=True)

    def tearDown(self):
        self.env.stop(); self.temp.cleanup()

    def profile(self):
        # Force a separate interpreter process without requiring another OS on this test host.
        python = self.folder/'python custom'
        python.symlink_to(sys.executable)
        log = self.folder/'git calls'
        git = self.folder/'git custom'
        git.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> '+shlex.quote(str(log))+'\nexec '+shlex.quote(shutil.which('git'))+' "$@"\n')
        git.chmod(0o755)
        result = self.manager.save(dict(kind='local', name='별도 Python', python=str(python), git=str(git)))
        return result['profile']['id'], log

    def test_worker_uses_selected_python_git_and_preserves_paths(self):
        identifier, log = self.profile()
        self.assertEqual(self.manager.call(identifier, 'open', {'path': str(self.repo)}), str(self.repo))
        state = self.manager.call(identifier, 'state', {'root': str(self.repo)})
        self.assertEqual(state['path'], str(self.repo))
        self.assertIn('--version', log.read_text())
        self.assertIn('status', log.read_text())
        restored = environments.Environments()
        self.assertEqual(restored.get(identifier)['name'], '별도 Python')

    def test_failed_save_keeps_previous_profile_and_file(self):
        identifier, _ = self.profile()
        before = self.manager.file.read_bytes()
        profile = dict(self.manager.get(identifier), python='/missing/python')
        with self.assertRaises(OSError): self.manager.save(profile)
        self.assertEqual(self.manager.file.read_bytes(), before)
        self.assertEqual(set(self.manager.profiles), {identifier})

    def test_declared_windows_profile_rejects_linux_python(self):
        with self.assertRaisesRegex(ValueError, '일치'):
            self.manager.save(dict(kind='windows', name='Wrong OS', python=sys.executable))
        self.assertEqual(self.manager.profiles, {})

    def test_worker_file_path_and_root_are_separate_and_tabs_restore(self):
        identifier, _ = self.profile()
        file = self.repo/'test.txt'; file.write_text('before\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'commit', '-m', 'initial'], check=True, capture_output=True)
        file.write_text('after\n')
        with Desk(0) as server:
            value = server.register(str(self.repo), profile=identifier)
            state = server.repo_call(value, 'state', {})
            self.assertEqual(state['displayPath'], str(self.repo))
            self.assertEqual(state['environment'], identifier)
            diff = server.repo_call(value, 'diff', {'kind': 'work', 'path': 'test.txt'})
            self.assertIn('after', diff['patch'] if isinstance(diff, dict) else diff)
            server.repo_call(value, 'action', {'op': 'stage', 'paths': ['test.txt']})
            self.assertEqual(server.repo_call(value, 'state', {})['changes'][0]['x'], 'M')
        with Desk(0) as server:
            self.assertIn(value, server.repos)
            self.assertEqual(server.active, value)

    @unittest.skipUnless(shutil.which('ssh-keygen'), 'OpenSSH is required')
    def test_key_generation_no_overwrite_public_only_and_discovery(self):
        with self.assertRaisesRegex(ValueError, '암호'):
            self.manager.call('default', 'ssh-generate', {'name': 'personal'})
        result = self.manager.call('default', 'ssh-generate', {'name': 'personal', 'unprotected': True})
        path = Path(result['path']); before = path.read_bytes()
        self.assertTrue(result['public'].startswith('ssh-ed25519 '))
        self.assertNotIn('PRIVATE', json.dumps(result))
        with self.assertRaises(FileExistsError):
            self.manager.call('default', 'ssh-generate', {'name': 'personal', 'unprotected': True})
        self.assertEqual(path.read_bytes(), before)
        keys = self.manager.call('default', 'ssh-list', {})
        self.assertIn(str(path), [key['path'] for key in keys])
        self.assertEqual(environments.public_key(str(path)), result['public'])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            self.manager.call('default', 'ssh-generate', {'name': '../escape', 'unprotected': True})

    def test_ssh_override_is_scoped_and_does_not_edit_git_config(self):
        key = self.folder/"key with ' quote"; key.write_text('private placeholder')
        profile = {'key': str(key), 'ssh': '/usr/bin/ssh', 'git': shutil.which('git')}
        args = shlex.split(environments.settings(profile)['env']['GIT_SSH_COMMAND'])
        self.assertEqual(args[-1], str(key))
        self.assertIn('StrictHostKeyChecking=yes', args)
        before = (self.repo/'.git/config').read_bytes()
        environments.invoke('state', {'root': str(self.repo)}, profile)
        self.assertEqual((self.repo/'.git/config').read_bytes(), before)
        self.assertEqual(environments.execution_settings.get(), {})

    def test_default_ssh_settings_preserved_and_agent_socket_is_scoped(self):
        self.assertEqual(environments.settings({})['env'], {})
        self.assertEqual(environments.settings({'agent': '/tmp/agent.sock'})['env'], {'SSH_AUTH_SOCK': '/tmp/agent.sock'})
        override = environments.settings({'ssh': '/custom/ssh'})['env']
        self.assertTrue(override['GIT_SSH_COMMAND'].startswith('/custom/ssh '))
        self.assertNotIn('IdentitiesOnly', override['GIT_SSH_COMMAND'])

    def test_startup_migrates_profile_tab_references_without_copying_keys(self):
        identifier = 'a'*32
        self.manager.profiles[identifier] = dict(id=identifier, kind='windows', name='Windows', python='C:/Python/python.exe', git='C:/Git/cmd/git.exe')
        tabs = TabStore(); tabs.update(str(self.repo))
        destination = self.folder/'windows-state'
        existing = destination/'tabs.json'
        environments.atomic_json(existing, dict(repos=['C:/existing'], recent=['C:/existing'], active='C:/existing'))
        original_call = self.manager.call
        imported = []
        def call(profile, op, data):
            if op == 'probe': return dict(os='windows', distro='', python='C:/Python/python.exe', git='C:/Git/cmd/git.exe')
            if op == 'import-settings':
                imported.append(data)
                with patch('environments.state_root', return_value=destination):
                    return environments.import_settings(data)
            return original_call(profile, op, data)
        with patch.dict(os.environ, WSL_DISTRO_NAME='Ubuntu'), patch.object(self.manager, 'call', side_effect=call), patch.object(self.manager, 'windows_root', return_value=str(self.folder/'Windows/Branchdesk')), patch('updater.wsl_path', side_effect=lambda path, **kwargs: path):
            self.manager.startup(identifier)
        self.assertEqual(len(imported), 1)
        active = imported[0]['active']
        source_profile, native_path = environments.split_repo(active)
        self.assertEqual(native_path, str(self.repo))
        self.assertEqual(imported[0]['profiles'][source_profile]['kind'], 'wsl')
        self.assertEqual(imported[0]['profiles'][source_profile]['distro'], 'Ubuntu')
        saved = json.loads(existing.read_text())
        self.assertIn('C:/existing', saved['repos'])
        self.assertEqual(saved['active'], active)
        host = json.loads((self.folder/'Windows/Branchdesk/host.json').read_text())
        self.assertEqual(host['kind'], 'windows')

    def test_update_drafts_follow_source_profile_after_host_change(self):
        data = dict(repo=str(self.repo), mode='work', drafts=[[str(self.repo), 'unfinished message']])
        with patch.dict(os.environ, WSL_DISTRO_NAME='Ubuntu'):
            snapshot = environments.export_ui(data)
            self.assertEqual(environments.restore_ui(snapshot)['drafts'], data['drafts'])
        with patch('environments.host_kind', return_value='windows'):
            restored = environments.restore_ui(snapshot)
        expected = environments.repo_id(snapshot['sourceProfile'], str(self.repo))
        self.assertEqual(restored['repo'], expected)
        self.assertEqual(restored['drafts'], [[expected, 'unfinished message']])

    def test_worker_argv_does_not_interpret_distro_or_python_as_shell(self):
        command = self.manager.command(dict(kind='wsl', distro='Ubuntu test;literal', python='/opt/python with space'))
        self.assertEqual(command[:5], ['wsl.exe', '--distribution', 'Ubuntu test;literal', '--exec', '/opt/python with space'])
        self.assertNotIn('sh', command)

    def test_bounded_process_timeout_stderr_and_preview(self):
        with self.assertRaisesRegex(ValueError, '시간'):
            run([sys.executable, '-c', 'import time;time.sleep(5)'], timeout=0.05)
        with self.assertRaisesRegex(ValueError, '한도'):
            run([sys.executable, '-c', 'import sys;sys.stderr.write("x"*1000000)'], limit=100)
        code, out, err = run([sys.executable, '-c', 'print("x"*1000000)'], limit=100, preview=True)
        self.assertEqual(code, 0)
        self.assertIn('미리보기'.encode(), out)


if __name__ == '__main__': unittest.main()
