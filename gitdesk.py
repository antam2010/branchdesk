"""Git operations for one local worktree. Requires Python 3.9+ and Git 2.28+."""
import os
import re
import selectors
import signal
import subprocess
import time
from pathlib import Path

DIFF_LIMIT = 192 * 1024
META_LIMIT = 16 * 1024 * 1024


class GitError(ValueError):
    pass


def git(root, *args, allowed=(0,), limit=META_LIMIT, preview=False, timeout=90, editor="false", object_dir=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_PAGER="cat",
               GIT_LITERAL_PATHSPECS="1", GIT_EDITOR=editor, GIT_MERGE_AUTOEDIT="no")
    if object_dir is not None:
        env["GIT_OBJECT_DIRECTORY"] = str(object_dir)
    command = ["git", "--no-pager", "-c", "color.ui=false", "-c", "core.quotepath=false",
               "-C", os.fspath(root), *args]
    proc = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)
    out, err = bytearray(), bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as events:
            for pipe, buf in ((proc.stdout, out), (proc.stderr, err)):
                events.register(pipe, selectors.EVENT_READ, buf)
            while events.get_map():
                left = deadline - time.monotonic()
                if left <= 0:
                    raise GitError("Git 응답 시간이 초과되었습니다. 저장소 상태를 새로고침해 주세요.")
                for key, _ in events.select(left):
                    part = os.read(key.fd, 65536)
                    if not part:
                        events.unregister(key.fileobj)
                        continue
                    buf = key.data
                    buf.extend(part)
                    if len(buf) > limit:
                        if preview and buf is out:
                            return bytes(out[:limit]) + "\n… 미리보기 한도에 도달했습니다.".encode()
                        raise GitError("결과가 표시 한도를 초과했습니다.")
        if proc.wait(timeout=max(0.1, deadline-time.monotonic())) not in allowed:
            raise GitError(bytes(err or out).decode(errors="replace").strip() or "Git 명령 실패")
        return bytes(out)
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        proc.stdout.close()
        proc.stderr.close()


def decode(data):
    return data.decode("utf-8", "surrogateescape")


def fields(data):
    return decode(data).removesuffix("\0").split("\0") if data else []


def line(data):
    return decode(data).removesuffix("\n")


def repository(path):
    p = Path(path).expanduser().resolve(strict=True)
    return Path(line(git(p, "rev-parse", "--show-toplevel")))


def current(root):
    return line(git(root, "symbolic-ref", "--quiet", "--short", "HEAD", allowed=(0, 1)))


def has_head(root):
    return bool(git(root, "rev-parse", "--verify", "--quiet", "HEAD", allowed=(0, 1)))


def changes(root, *paths):
    raw = git(root, "--no-optional-locks", "status", "--porcelain=v1", "-z",
              "--no-renames", "--untracked-files=all", "--", *paths)
    return [dict(x=s[0], y=s[1], path=s[3:]) for s in fields(raw)]


def history(root, count):
    args = ["log", "--branches", "--remotes", "--tags", "--topo-order", "-z", "-n", str(count+1),
            "--format=%H%x00%P%x00%an%x00%aI%x00%s"]
    if has_head(root):
        args.append("HEAD")
    raw = fields(git(root, *args, "--"))
    rows = [dict(zip(("id", "parents", "author", "date", "subject"), raw[i:i+5]))
            for i in range(0, len(raw), 5)]
    for row in rows:
        row["parents"] = row["parents"].split()
    return rows[:count], len(rows) > count


def state(root, count):
    commits, more = history(root, min(5000, max(50, int(count))))
    refs = []
    fmt = "%(refname)%00%(objectname)%00%(*objectname)%00%(upstream:short)%00%(symref)%00%(upstream:remotename)%00%(upstream:remoteref)"
    for record in decode(git(root, "for-each-ref", "--format=" + fmt,
                             "refs/heads", "refs/remotes", "refs/tags")).split("\n"):
        if record:
            ref, obj, peeled, upstream, symbolic, remote, tracking = record.split("\0")
            if not symbolic:
                _, group, name = ref.split("/", 2)
                refs.append(dict(group=group, name=name, id=peeled or obj, upstream=upstream, remote=remote, target=tracking.removeprefix("refs/heads/")))
    stash_fields = fields(git(root, "stash", "list", "-z", "--format=%H%x00%gs", "-n", "100"))
    stashes = [dict(id=oid, title=title) for oid, title in zip(stash_fields[::2], stash_fields[1::2])]
    from workspace_ops import flow_config, in_progress
    return dict(flow=flow_config(root), progress=in_progress(root), stashes=stashes, path=str(root), name=root.name or str(root), branch=current(root),
                head=line(git(root, "rev-parse", "--verify", "--quiet", "HEAD", allowed=(0, 1))),
                refs=refs, changes=changes(root), commits=commits, more=more,
                remotes=line(git(root, "remote")).splitlines())


def verify_commit(root, rev):
    if not isinstance(rev, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", rev):
        raise GitError("커밋 ID를 확인해 주세요.")
    if line(git(root, "cat-file", "-t", rev)) != "commit":
        raise GitError("커밋을 찾을 수 없습니다.")


def baseline(root, rev):
    parents = line(git(root, "rev-list", "--parents", "-n1", rev)).split()[1:]
    return [parents[0], rev] if parents else ["--root", rev]


def endpoints(root, rev, base=None):
    verify_commit(root, rev)
    if base:
        verify_commit(root, base)
        return [base, rev]
    return baseline(root, rev)


def detail(root, rev, base=None):
    ends = endpoints(root, rev, base)
    raw = fields(git(root, "diff-tree", "--no-commit-id", "-r", "--no-renames",
                     "--name-status", "-z", *ends, "--"))
    msg = decode(git(root, "show", "-s", "--format=%B", rev)).strip()
    return dict(message=msg, files=[dict(code=k, path=v) for k, v in zip(raw[::2], raw[1::2])])


def diff(root, data):
    kind, path = data.get("kind"), data.get("path")
    if not isinstance(path, str) or not path or path.startswith("/") or ".." in Path(path).parts:
        raise GitError("파일 경로가 올바르지 않습니다.")
    options = ["--no-ext-diff", "--no-textconv", "--no-color", "--no-renames"]
    if kind == "commit":
        rev = data.get("rev")
        ends = endpoints(root, rev, data.get("base"))
        args = ["diff-tree", "--no-commit-id", "-p", *options, *ends, "--", path]
    elif kind in ("index", "work"):
        item = next((f for f in changes(root, path) if f["path"] == path), None)
        if not item:
            return ""
        if item["x"] == "?" and kind == "work":
            entry = root / path
            if entry.is_dir() and not entry.is_symlink():
                return "별도 Git 저장소 디렉터리"
            if not entry.is_symlink() and not entry.is_file():
                return "이 파일 형식은 미리보기를 지원하지 않습니다."
            args = ["diff", "--no-index", *options, "--", "/dev/null", path]
        else:
            args = ["diff", *options, *(["--cached"] if kind == "index" else []), "--", path]
    else:
        raise GitError("비교 대상을 확인해 주세요.")
    return git(root, *args, allowed=(0, 1), limit=DIFF_LIMIT, preview=True).decode(errors="replace")


def act(root, d):
    op = d.get("op")
    if op in ("stage", "unstage"):
        paths = d.get("paths")
        known = {f["path"] for f in changes(root)}
        if not isinstance(paths, list) or not paths or any(p not in known for p in paths):
            raise GitError("변경 목록을 새로고침한 뒤 다시 선택해 주세요.")
        if op == "stage":
            args = ["add", "-A"]
        elif has_head(root):
            args = ["reset", "-q", "HEAD"]
        else:
            args = ["rm", "--cached", "-q", "-f"]
        git(root, *args, "--", *paths)
    elif op == "commit":
        msg = d.get("message", "").strip()
        if not msg:
            raise GitError("커밋 메시지를 입력해 주세요.")
        git(root, "commit", *(["--amend"] if d.get("amend") else []), "-m", msg)
    elif op in ("branch", "switch"):
        name = d.get("name", "")
        if not name or name.startswith("-") or line(git(root, "check-ref-format", "--branch", name)) != name:
            raise GitError("브랜치 이름을 확인해 주세요.")
        if op == "switch":
            git(root, "show-ref", "--verify", "refs/heads/" + name)
        if op == "branch":
            rev = d.get("rev")
            if rev:
                verify_commit(root, rev)
            args = ["switch", "-c"] if d.get("checkout", True) else ["branch"]
            git(root, *args, name, rev or "HEAD")
        else:
            git(root, "switch", name)
    elif op == "merge":
        name = d.get("name", "")
        if not current(root):
            raise GitError("로컬 브랜치를 먼저 체크아웃해 주세요.")
        git(root, "show-ref", "--verify", "refs/heads/" + name)
        git(root, "merge", "--no-edit", "--", "refs/heads/" + name)
    elif op == "stash":
        message = d.get("message", "").strip()
        git(root, "stash", "push", "--include-untracked", *(["-m", message] if message else []))
    elif op == "apply_stash":
        oid = d.get("id", "")
        if oid not in fields(git(root, "stash", "list", "-z", "--format=%H")):
            raise GitError("스태시 목록을 새로고침해 주세요.")
        git(root, "stash", "apply", "--index", oid)
    elif op == "fetch":
        remote = d.get("remote", "")
        if remote and remote not in line(git(root, "remote")).splitlines():
            raise GitError("원격 저장소를 선택해 주세요.")
        flags = [flag for key, flag in (("prune", "--prune"), ("tags", "--tags")) if d.get(key)]
        git(root, "fetch", *flags, *(["--", remote] if remote else ["--all"]))
    elif op in ("pull", "push"):
        branch = current(root)
        if not branch:
            raise GitError("로컬 브랜치를 먼저 체크아웃해 주세요.")
        remote = line(git(root, "config", "--get", "branch." + branch + ".remote", allowed=(0, 1)))
        target = line(git(root, "config", "--get", "branch." + branch + ".merge", allowed=(0, 1)))
        if d.get("target"):
            from workspace_ops import valid_ref
            remote, target = d.get("remote"), valid_ref(root, "heads", d["target"])
        elif not remote and op == "push":
            remote, target = d.get("remote"), "refs/heads/" + branch
        if remote not in line(git(root, "remote")).splitlines() or not target.startswith("refs/heads/"):
            raise GitError("연결된 원격 브랜치를 확인해 주세요.")
        if op == "pull":
            flag = {"ff": "--ff-only", "merge": "--no-rebase", "rebase": "--rebase"}.get(d.get("strategy","ff"))
            if not flag:
                raise GitError("풀 방식을 확인하세요.")
            git(root, "pull", flag, "--", remote, target)
        else:
            git(root, "push", "--set-upstream", "--", remote, "HEAD:" + target)
    else:
        from workspace_ops import operate
        operate(root, d)
