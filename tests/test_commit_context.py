import base64
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

import commit_ops as ops
import gitdesk
import workspace_ops


class CommitContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '한글 repo'
        self.root.mkdir()
        self.g('init', '-b', 'main')
        self.g('config', 'user.name', 'Context QA')
        self.g('config', 'user.email', 'qa@example.invalid')
        self.g('config', 'commit.gpgsign', 'false')
        self.base = self.record('notes', 'base\n', 'initial')

    def g(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.STDOUT).decode().strip()

    def record(self, path, text, message):
        (self.root / path).write_text(text)
        self.g('add', '--', path)
        self.g('commit', '-m', message)
        return self.g('rev-parse', 'HEAD')

    def act(self, op, rev, **data):
        ctx = ops.context(self.root, rev)
        return gitdesk.act(self.root, dict(op=op, rev=rev, expectedHead=ctx['head'], expectedBranch=ctx['branch'], **data))

    def test_context_permissions_and_stale_branch(self):
        ctx = ops.context(self.root, self.base)
        self.assertTrue(ctx['permissions']['checkout_commit'])
        self.assertTrue(ctx['permissions']['merge_commit'])
        self.assertTrue(ctx['permissions']['reorder_commits'])
        self.assertFalse(ctx['permissions']['revert_commit'])
        self.g('switch', '-c', 'other')
        with self.assertRaisesRegex(gitdesk.GitError, '바뀌었습니다'):
            ops.operate(self.root, dict(op='reset_commit', rev=self.base, mode='soft', expectedHead=ctx['head'], expectedBranch=ctx['branch']))
        self.assertEqual(self.g('branch', '--show-current'), 'other')

    def test_detached_checkout_and_dirty_protection(self):
        tip = self.record('new', 'new\n', 'second')
        (self.root / 'notes').write_text('unsaved\n')
        with self.assertRaisesRegex(gitdesk.GitError, '스태시'):
            self.act('checkout_commit', self.base)
        self.assertEqual(self.g('rev-parse', 'HEAD'), tip)
        self.g('restore', 'notes')
        self.act('checkout_commit', self.base)
        self.assertEqual(self.g('branch', '--show-current'), '')
        self.assertEqual(self.g('rev-parse', 'main'), tip)

    def test_soft_mixed_and_hard_resets(self):
        tip = self.record('notes', 'second\n', 'second')
        self.act('reset_commit', self.base, mode='soft')
        self.assertEqual(self.g('show', ':notes'), 'second')
        self.assertEqual(self.g('show', 'HEAD:notes'), 'base')
        self.act('reset_commit', self.base, mode='mixed')
        self.assertEqual(self.g('show', ':notes'), 'base')
        self.assertEqual((self.root / 'notes').read_text(), 'second\n')
        with self.assertRaisesRegex(gitdesk.GitError, 'HARD'):
            self.act('reset_commit', tip, mode='hard', confirmation='')
        self.assertEqual((self.root / 'notes').read_text(), 'second\n')
        self.act('reset_commit', tip, mode='hard', confirmation='HARD')
        self.assertFalse(self.g('status', '--porcelain'))

    def test_merge_and_rebase_selected_commit(self):
        self.g('switch', '-c', 'topic')
        topic = self.record('topic', 'topic\n', 'topic')
        self.g('switch', 'main')
        local = self.record('local', 'local\n', 'local')
        self.act('merge_commit', topic)
        self.assertEqual(self.g('rev-parse', 'HEAD^1'), local)
        self.assertEqual(self.g('rev-parse', 'HEAD^2'), topic)
        self.act('reset_commit', local, mode='hard', confirmation='HARD')
        self.act('rebase_commit', topic)
        self.assertEqual(self.g('rev-parse', 'HEAD^'), topic)
        self.assertTrue((self.root / 'local').exists())

    def test_revert_and_cherry_pick_selected_commit(self):
        self.g('switch', '-c', 'topic')
        change = self.record('feature', 'feature\n', 'feature')
        self.g('switch', 'main')
        self.record('local', 'local\n', 'local')
        self.act('cherry_pick_commit', change)
        self.assertTrue((self.root / 'feature').exists())
        picked = self.g('rev-parse', 'HEAD')
        self.act('revert_commit', picked)
        self.assertFalse((self.root / 'feature').exists())
        self.assertEqual(self.g('rev-parse', 'HEAD^'), picked)

    def test_revert_conflict_can_abort_and_continue(self):
        middle = self.record('notes', 'middle\n', 'middle')
        final = self.record('notes', 'final\n', 'final')
        with self.assertRaises(gitdesk.GitError):
            self.act('revert_commit', middle)
        self.assertEqual(workspace_ops.in_progress(self.root), 'revert')
        gitdesk.act(self.root, {'op': 'abort'})
        self.assertEqual(self.g('rev-parse', 'HEAD'), final)
        self.assertEqual((self.root / 'notes').read_text(), 'final\n')
        with self.assertRaises(gitdesk.GitError):
            self.act('revert_commit', middle)
        (self.root / 'notes').write_text('resolved\n')
        self.g('add', 'notes')
        gitdesk.act(self.root, {'op': 'continue'})
        self.assertFalse(workspace_ops.in_progress(self.root))
        self.assertEqual(self.g('show', 'HEAD:notes'), 'resolved')

    def test_interactive_rebase_reorders_folds_and_drops(self):
        first = self.record('one', 'one\n', 'one')
        second = self.record('two', 'two\n', 'two')
        third = self.record('three', 'three\n', 'three')
        plan = ops.rebase_plan(self.root, self.base)
        self.assertEqual([c['id'] for c in plan['commits']], [first, second, third])
        self.act('reorder_commits', self.base, plan=[dict(id=second, action='pick'), dict(id=first, action='squash'), dict(id=third, action='drop')])
        self.assertEqual(self.g('rev-list', '--count', self.base + '..HEAD'), '1')
        self.assertTrue((self.root / 'one').exists() and (self.root / 'two').exists())
        self.assertFalse((self.root / 'three').exists())
        self.assertIn('one', self.g('log', '-1', '--format=%B'))

    def test_interactive_rebase_rejects_injected_or_incomplete_plan(self):
        first = self.record('one', 'one', 'one')
        second = self.record('two', 'two', 'two')
        for plan in [[dict(id=first, action='pick')], [dict(id=first, action='exec touch unsafe'), dict(id=second, action='pick')], [dict(id=first, action='squash'), dict(id=second, action='pick')]]:
            with self.subTest(plan=plan), self.assertRaises(gitdesk.GitError):
                self.act('reorder_commits', self.base, plan=plan)
            self.assertEqual(self.g('rev-parse', 'HEAD'), second)
            self.assertFalse((self.root / 'unsafe').exists())

    def test_archive_and_root_and_binary_patch_exports(self):
        archive = ops.export(self.root, dict(rev=self.base, kind='archive'))
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(archive['content']))) as z:
            self.assertEqual(z.read('source/notes'), b'base\n')
        patch = base64.b64decode(ops.export(self.root, dict(rev=self.base, kind='patch'))['content'])
        self.assertIn(b'initial', patch)
        self.assertIn(b'new file mode', patch)
        (self.root / 'binary').write_bytes(bytes(range(256)))
        self.g('add', 'binary'); self.g('commit', '-m', 'binary')
        tip = self.g('rev-parse', 'HEAD')
        patch = base64.b64decode(ops.export(self.root, dict(rev=tip, kind='patch'))['content'])
        self.assertIn(b'GIT binary patch', patch)

    def test_merge_mainline_validation_and_no_linear_plan(self):
        self.g('switch', '-c', 'topic')
        topic = self.record('topic', 'topic', 'topic')
        self.g('switch', 'main'); self.record('local', 'local', 'local')
        self.act('merge_commit', topic)
        merge = self.g('rev-parse', 'HEAD')
        self.assertTrue(ops.context(self.root, self.base)['permissions']['reorder_commits'])
        with self.assertRaises(gitdesk.GitError):
            self.act('revert_commit', merge, mainline=3)
        with self.assertRaises(gitdesk.GitError):
            ops.export(self.root, dict(rev=merge, kind='patch'))
        self.act('revert_commit', merge, mainline=1)
        self.assertFalse((self.root / 'topic').exists())
        self.assertTrue((self.root / 'local').exists())
