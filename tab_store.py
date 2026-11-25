"""Remember open worktrees for the current WSL user."""
import fcntl
import json
import os
import tempfile
from pathlib import Path


class TabStore:
    def __init__(self):
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
        self.file = base / "branchdesk" / "tabs.json"

    def read(self):
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (FileNotFoundError, UnicodeError, json.JSONDecodeError):
            return [], None
        if not isinstance(data, dict) or not isinstance(data.get("repos"), list):
            return [], None
        repos = list(dict.fromkeys(p for p in data["repos"] if isinstance(p, str) and p.startswith("/") and "\x00" not in p))
        return repos, data.get("active") if data.get("active") in repos else None

    def update(self, path, *, closing=False, fallback=None):
        directory = self.file.parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Merge a single tab event with the latest state from other windows.
        with (directory / "tabs.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            repos, active = self.read()
            if closing:
                if path in repos:
                    repos.remove(path)
                if active == path:
                    active = fallback if fallback in repos else next(iter(repos), None)
            else:
                if path not in repos:
                    repos.append(path)
                active = path
            with tempfile.NamedTemporaryFile(mode="w", dir=directory, encoding="utf-8", delete=False) as tmp:
                try:
                    json.dump({"repos": repos, "active": active}, tmp)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                    os.replace(tmp.name, self.file)
                finally:
                    Path(tmp.name).unlink(missing_ok=True)
