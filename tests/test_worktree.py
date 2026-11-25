import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gitdesk


class WorktreeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.STDOUT)

    def act(self, op, **kwargs):
        gitdesk.act(self.root, dict(op=op, **kwargs))

    def seed(self):
        (self.root / "readme").write_text("base\n")
        self.git("add", "readme")
        self.git("commit", "-m", "initial")

    def test_unborn_and_literal_path(self):
        name = "[a] 한글.txt"
        for path in (name, "a 한글.txt"):
            (self.root / path).write_text(path)
        self.act("stage", paths=[name])
        self.assertEqual(self.git("ls-files", "-z").decode(), name+"\0")
        self.act("unstage", paths=[name])
        self.assertEqual(self.git("ls-files"), b"")
        self.assertTrue((self.root / name).exists())

    def test_stash_preserves_partial_stage(self):
        self.seed()
        p = self.root / "readme"
        p.write_text("staged\n")
        self.act("stage", paths=["readme"])
        p.write_text("unstaged\n")
        before = [gitdesk.diff(self.root, dict(kind=k, path="readme")) for k in ("index", "work")]
        self.act("stash", message="partial")
        state = gitdesk.state(self.root, 50)
        self.assertEqual(len(state["commits"]), 1)
        self.assertFalse(state["changes"])
        self.act("apply_stash", id=state["stashes"][0]["id"])
        after = [gitdesk.diff(self.root, dict(kind=k, path="readme")) for k in ("index", "work")]
        self.assertEqual(after, before)
        self.assertIn("+staged", after[0])
        self.assertIn("+unstaged", after[1])

    def test_merge_first_parent_detail(self):
        self.seed()
        self.act("branch", name="feature")
        (self.root / "feature").write_text("change")
        self.act("stage", paths=["feature"])
        self.act("commit", message="feature")
        self.act("switch", name="main")
        (self.root / "main").write_text("main")
        self.act("stage", paths=["main"])
        self.act("commit", message="main")
        self.act("merge", name="feature")
        state = gitdesk.state(self.root, 50)
        self.assertEqual(len(state["commits"][0]["parents"]), 2)
        detail = gitdesk.detail(self.root, state["head"])
        self.assertEqual(detail["files"], [dict(code="A", path="feature")])


if __name__ == "__main__":
    unittest.main()
