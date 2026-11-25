"""Exercise the exact WSL probe with missing tools and version boundaries."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROBE = re.search(r"\$Probe = @'\n(.*?)\n'@", (ROOT / "windows/setup.ps1").read_text(), re.S)[1]


@unittest.skipIf(os.name == "nt", "The probe runs inside WSL; use a Linux test host.")
class SetupProbeTests(unittest.TestCase):
    def probe(self, python=None, git=None, apt=False):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            if python:
                (folder / "python3").write_text(
                    f"#!{sys.executable}\nimport sys\nsys.version_info = {python!r}\nexec(sys.argv[-1])\n")
            if git:
                (folder / "git").write_text("#!/bin/sh\nprintf '%s\\n' 'git version " + git + "'\n")
            if apt:
                (folder / "apt-get").write_text("#!/bin/sh\nexit 99\n")
            for command in folder.iterdir():
                command.chmod(0o755)
            result = subprocess.run(["/bin/sh", "-s"], input=PROBE, text=True, capture_output=True,
                                    env={**os.environ, "PATH": directory}, check=True)
            self.assertEqual(result.stderr, "")
            marker, *fields = result.stdout.splitlines()
            self.assertEqual(marker, "BD_ENV/1")
            return dict(field.split("=") for field in fields)

    def test_missing_tools_and_unsupported_package_manager(self):
        self.assertEqual(self.probe(), {"PYTHON": "0", "GIT": "0", "APT": "0"})

    def test_supported_version_boundaries(self):
        for python, git in [((3, 9, 0), "2.28.0"), ((3, 12, 1), "2.48.1"), ((4, 0, 0), "3.0.0")]:
            with self.subTest(python=python, git=git):
                self.assertEqual(self.probe(python, git, True), {"PYTHON": "1", "GIT": "1", "APT": "1"})

    def test_old_and_malformed_versions_are_rejected_independently(self):
        self.assertEqual(self.probe((3, 8, 20), "2.28.0"), {"PYTHON": "0", "GIT": "1", "APT": "0"})
        for git in ["2.27.9", "1.99.0", "unknown"]:
            with self.subTest(git=git):
                self.assertEqual(self.probe((3, 9, 0), git), {"PYTHON": "1", "GIT": "0", "APT": "0"})
