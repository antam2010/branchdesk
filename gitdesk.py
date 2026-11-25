"""Git operations for one local worktree. Requires Python 3.9+ and Git 2.28+."""
import os
import re
from pathlib import Path

DIFF_LIMIT = 192 * 1024
META_LIMIT = 16 * 1024 * 1024


class GitError(ValueError):
    pass


def git(root, *args, allowed=(0,), limit=META_LIMIT, preview=False, timeout=90, editor="false", object_dir=None, sequence_editor=None, input_data=None):
    from environments import execution_settings
    settings = execution_settings.get()
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_PAGER="cat",
               GIT_LITERAL_PATHSPECS="1", GIT_EDITOR=editor, GIT_MERGE_AUTOEDIT="no")
    if object_dir is not None:
        env["GIT_OBJECT_DIRECTORY"] = str(object_dir)
    if sequence_editor is not None:
        env["GIT_SEQUENCE_EDITOR"] = sequence_editor
    env.update(settings.get("env", {}))
    command = [settings.get("git") or "git", "--no-pager", "-c", "color.ui=false", "-c", "core.quotepath=false",
               "-C", os.fspath(root), *args]
    from process_utils import run
    try:
        code, out, err = run(command, env=env, data=input_data, timeout=timeout, limit=limit, preview=preview)
    except ValueError as error:
        raise GitError(str(error)) from error
    if code not in allowed:
        raise GitError((err or out).decode(errors="replace").strip() or "Git 명령 실패")
    return out


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


def locate_commit(root, rev, count=150):
    verify_commit(root, rev)
    args = ['log', '--branches', '--remotes', '--tags', '--topo-order', '--format=%H', '-n', '5000']
    if has_head(root): args.append('HEAD')
    ids = line(git(root, *args, '--')).splitlines()
    if rev not in ids: raise GitError('이 커밋은 최근 5,000개 이력에 없습니다. Git 로그 범위를 확인하세요.')
    return dict(count=max(int(count), min(5000, ids.index(rev)+40)), rev=rev)


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


def valid_path(path):
    return isinstance(path, str) and bool(path) and "\x00" not in path and not Path(path).is_absolute() and not Path(path).drive and ".." not in Path(path).parts


def file_preview(root, path, *, source='work', rev=None, title='파일 전체 내용'):
    """Read the selected version, never substitute the worktree for the index/commit."""
    if not valid_path(path): raise GitError('파일 경로가 올바르지 않습니다.')
    truncated = False
    if source == 'work':
        file = root / path
        if file.is_symlink():
            raw = os.fsencode(os.readlink(file)); size = len(raw)
        elif file.is_file():
            with file.open('rb') as stream: raw = stream.read(DIFF_LIMIT+1)
            size = file.stat().st_size; truncated = len(raw)>DIFF_LIMIT
            raw = raw[:DIFF_LIMIT]
        else: return dict(type='file', message='파일이 삭제되었거나 일반 파일이 아닙니다.', title=title)
    else:
        if source == 'index':
            records = fields(git(root, 'ls-files', '--stage', '-z', '--', path))
            candidates = [row.split('\t',1)[0].split()[1] for row in records if row.split('\t',1)[1]==path and row.split('\t',1)[0].split()[2]=='0']
        else:
            verify_commit(root, rev)
            records = fields(git(root, 'ls-tree', '-z', rev, '--', path))
            candidates = [row.split('\t',1)[0].split()[2] for row in records if row.split('\t',1)[1]==path and row.split('\t',1)[0].split()[1]=='blob']
        if not candidates: return dict(type='file', message='이 버전에 파일 내용이 없습니다. 삭제 또는 서브모듈 여부를 확인하세요.', title=title)
        blob = candidates[0]
        if line(git(root, 'cat-file', '-t', blob)) != 'blob':
            return dict(type='file', message='서브모듈은 파일 내용 대신 연결된 커밋을 관리합니다.', title=title)
        size = int(line(git(root, 'cat-file', '-s', blob)))
        raw = git(root, 'cat-file', 'blob', blob, limit=DIFF_LIMIT, preview=True)
        truncated = size>DIFF_LIMIT
        raw = raw[:DIFF_LIMIT]
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        text = raw.decode('utf-16', errors='replace')
    elif b'\0' in raw:
        return dict(type='file', message='바이너리 파일입니다. 텍스트 미리보기를 지원하지 않습니다.', size=size, title=title)
    else: text = raw.decode('utf-8-sig', errors='replace')
    return dict(type='file', text=text, empty=size==0, truncated=truncated, size=size, title=title, source=source)


def diff(root, data):
    kind, path = data.get("kind"), data.get("path")
    if not valid_path(path):
        raise GitError("파일 경로가 올바르지 않습니다.")
    options = ["--no-ext-diff", "--no-textconv", "--no-color", "--no-renames"]
    if kind == "commit":
        rev = data.get("rev")
        ends = endpoints(root, rev, data.get("base"))
        if data.get('code') == 'A':
            return file_preview(root, path, source='commit', rev=rev, title='새 파일 · 커밋의 전체 내용')
        args = ["diff-tree", "--no-commit-id", "-p", *options, *ends, "--", path]
    elif kind in ("index", "work"):
        item = next((f for f in changes(root, path) if f["path"] == path), None)
        if not item:
            return file_preview(root, path, source=kind, title='변경 비교 없음 · 파일 전체 내용')
        if (item['x'] == '?' and kind == 'work') or (item['x'] == 'A' and kind == 'index'):
            return file_preview(root, path, source=kind, title='새 파일 · 전체 내용')
        else:
            args = ["diff", *options, *(["--cached"] if kind == "index" else []), "--", path]
    else:
        raise GitError("비교 대상을 확인해 주세요.")
    patch = git(root, *args, allowed=(0, 1), limit=DIFF_LIMIT, preview=True).decode(errors='replace')
    return patch or file_preview(root, path, source='commit' if kind=='commit' else kind, rev=data.get('rev'), title='변경 비교 없음 · 파일 전체 내용')


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
            from workspace_ops import switch_branch
            switch_branch(root, d)
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
        from commit_ops import ACTIONS, operate as commit_operate
        if op in ACTIONS:
            return commit_operate(root, d)
        from workspace_ops import operate
        return operate(root, d)
