"""Repository management and Git Flow operations used by Branchdesk."""
import heapq
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from gitdesk import GitError, changes, current, fields, git, line, verify_commit


def branch_name(root, name):
    if not name or name.startswith("-") or line(git(root, "check-ref-format", "--branch", name)) != name:
        raise GitError("브랜치 이름을 확인하세요.")
    return name


def valid_ref(root, group, name):
    if not name or name.startswith("-"):
        raise GitError("참조 이름이 올바르지 않습니다.")
    ref = "refs/" + group + "/" + name
    git(root, "check-ref-format", ref)
    return ref


def oid(root, ref):
    return line(git(root, "rev-parse", "--verify", ref))


def existing(root, group, name):
    ref = valid_ref(root, group, name)
    git(root, "show-ref", "--verify", ref)
    return ref


def remote_name(root, name):
    if name not in line(git(root, "remote")).splitlines() or name.startswith("-"):
        raise GitError("등록된 원격 저장소를 선택하세요.")
    return name


def address(value):
    if not value or value.startswith("-") or "::" in value.split("/", 1)[0] or any(ord(c)<32 for c in value):
        raise GitError("원격 주소를 확인하세요.")
    if "://" in value and value.split("://", 1)[0] not in ("http", "https", "ssh", "git", "file"):
        raise GitError("지원하지 않는 전송 방식입니다.")
    return os.path.expanduser(value)


def remote_urls(root):
    return [dict(name=name, fetch=line(git(root, "remote", "get-url", "--all", name)).splitlines(),
                 push=line(git(root, "remote", "get-url", "--push", "--all", name)).splitlines())
            for name in line(git(root, "remote")).splitlines()]


def directory_suggestions(path):
    """Complete a single WSL path component without walking the directory tree."""
    if not isinstance(path, str) or len(path) > 4096 or "\x00" in path:
        return []
    if not path:
        return ["~/", "/"]
    if path == "~":
        return ["~/"]
    parent, slash, prefix = path.rpartition("/")
    display_parent = parent + slash
    try:
        with os.scandir(os.path.expanduser(display_parent or ".")) as entries:
            def matches():
                for entry in entries:
                    if not entry.name.startswith(prefix) or (entry.name.startswith(".") and not prefix.startswith(".")):
                        continue
                    try:
                        if entry.is_dir():
                            yield display_parent + entry.name + "/"
                    except OSError:
                        continue
            return heapq.nsmallest(50, matches())
    except OSError:
        return []


def new_repository(data):
    raw = data["path"].strip()
    if not raw:
        raise GitError("저장소 경로를 입력하세요.")
    path = Path(raw).expanduser().resolve()
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise GitError("새 경로 또는 빈 폴더를 지정하세요.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if data["mode"] == "clone":
        git(path.parent, "clone", "--", address(data["url"]), str(path), timeout=600)
    elif data["mode"] == "init":
        name = branch_name(path.parent, data.get("name") or "main")
        git(path.parent, "init", "-b", name, "--", str(path))
    else:
        raise GitError("생성 방식을 확인하세요.")
    return path


def launch_desktop(root, op):
    if os.environ.get("WSL_DISTRO_NAME"):
        if op == "explorer":
            unc = subprocess.check_output(["wslpath", "-w", str(root)], text=True).rstrip("\n")
            command = ["explorer.exe", unc]
        else:
            # The path stays a single Windows argument, even with spaces and shell punctuation.
            arguments = subprocess.list2cmdline(["-d", os.environ["WSL_DISTRO_NAME"], "--cd", str(root)])
            script = ("$ErrorActionPreference='Stop';"
                      "$a=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([Console]::ReadLine()));"
                      "Start-Process -FilePath ([IO.Path]::Combine([Environment]::SystemDirectory,'wsl.exe')) -ArgumentList $a")
            import base64
            subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                           input=base64.b64encode(arguments.encode())+b"\n", check=True, timeout=20,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            return
    else:
        command = ["xdg-open", str(root)] if op == "explorer" else ["x-terminal-emulator"]
    if not shutil.which(command[0]):
        raise GitError(command[0] + " 실행 파일을 찾지 못했습니다.")
    subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def flow_config(root):
    raw = line(git(root, "config", "--local", "--get", "branchdesk.flow", allowed=(0, 1)))
    return json.loads(raw) if raw else None


def in_progress(root):
    directory = Path(line(git(root, "rev-parse", "--absolute-git-dir")))
    for name, markers in (("rebase", ("rebase-merge","rebase-apply")), ("cherry-pick", ("CHERRY_PICK_HEAD",)),
                          ("merge", ("MERGE_HEAD",))):
        if any((directory / marker).exists() for marker in markers):
            return name
    return ""


def flow(root, data):
    op = data["op"]
    if op == "flow_init":
        prod = branch_name(root, data["production"])
        dev = branch_name(root, data["development"])
        ref = existing(root, "heads", prod)
        if prod == dev:
            raise GitError("운영 브랜치와 개발 브랜치는 서로 달라야 합니다.")
        if not git(root, "show-ref", "--verify", "refs/heads/"+dev, allowed=(0, 128, 1)):
            git(root, "branch", dev, ref)
        git(root, "config", "--local", "branchdesk.flow", json.dumps([prod, dev]))
        return
    config = flow_config(root)
    if not config:
        raise GitError("먼저 Git Flow의 운영·개발 브랜치를 설정하세요.")
    prod, dev = config
    kind = data["kind"]
    if kind not in ("feature", "release", "hotfix"):
        raise GitError("Git Flow 유형이 올바르지 않습니다.")
    topic = branch_name(root, kind + "/" + data["name"])
    if topic in (prod, dev) or changes(root) or in_progress(root):
        raise GitError("작업 트리와 진행 중인 Git 작업을 정리한 뒤 실행하세요.")
    prod_ref, dev_ref = (existing(root, "heads", n) for n in config)
    if op == "flow_start":
        git(root, "switch", "-c", topic, prod_ref if kind == "hotfix" else dev_ref)
        return
    if current(root) != topic:
        raise GitError("종료할 작업 브랜치를 먼저 체크아웃하세요.")
    topic_ref = existing(root, "heads", topic)
    tip = oid(root, topic_ref)
    destinations = [dev_ref] if kind == "feature" else [prod_ref, dev_ref]
    occupied = set(fields(git(root, "worktree", "list", "--porcelain").replace(b"\n", b"\0")))
    if any("branch "+ref in occupied for ref in destinations):
        raise GitError("다른 작업 트리가 대상 브랜치를 사용 중입니다.")
    tag = None
    if kind != "feature":
        tag = valid_ref(root, "tags", data.get("tag") or data["name"])
        if git(root, "show-ref", "--verify", tag, allowed=(0, 1, 128)):
            raise GitError("이미 있는 태그입니다. 다른 버전 태그를 선택하세요.")
    updates = []
    source = tip
    # Prepare every merge away from the user's worktree. Publish refs in one Git transaction.
    with tempfile.TemporaryDirectory(prefix="branchdesk-flow-") as temp:
        work = Path(temp)/"merge"
        git(root, "worktree", "add", "--detach", str(work), tip)
        try:
            for ref in destinations:
                old = oid(root, ref)
                git(work, "switch", "--detach", old)
                git(work, "merge", "--no-ff", "--no-edit", "-m", "Merge "+topic+" into "+ref[11:], source)
                new = oid(work, "HEAD")
                updates.append(f"update {ref} {new} {old}")
                if ref == prod_ref:
                    updates.append(f"create {tag} {new}")
                    source = new
            updates.append(f"verify {topic_ref} {tip}")
            with tempfile.TemporaryFile() as txn:
                txn.write(("\n".join(updates)+"\n").encode("utf-8","surrogateescape"))
                txn.seek(0)
                proc = subprocess.run(["git", "-C", str(root), "update-ref", "--stdin"], stdin=txn,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                if proc.returncode:
                    raise GitError(proc.stderr.decode(errors="replace"))
        finally:
            git(root, "worktree", "remove", "--force", str(work))
    git(root, "switch", dev)
    # Compare-and-delete refuses removal if an external process advanced the topic.
    git(root, "update-ref", "-d", topic_ref, tip)


def operate(root, d):
    op = d["op"]
    name = d.get("name", "")
    if op in ("flow_init", "flow_start", "flow_finish"):
        flow(root, d)
    elif op in ("terminal", "explorer"):
        launch_desktop(root, op)
    elif op in ("branch_rename", "branch_delete"):
        existing(root, "heads", name)
        if op == "branch_delete":
            git(root, "branch", "-d", "--", name)
        else:
            git(root, "branch", "-m", "--", name, branch_name(root,d["new"]))
    elif op == "track":
        ref = existing(root, "remotes", d["upstream"])
        git(root, "switch", "--track", "-c", branch_name(root,name), ref)
    elif op == "tag_create":
        verify_commit(root, d["rev"])
        valid_ref(root, "tags", name)
        git(root, "tag", "--", name, d["rev"])
    elif op in ("tag_delete", "tag_push"):
        ref = existing(root, "tags", name)
        if op == "tag_delete":
            git(root, "tag", "-d", "--", name)
        else:
            git(root, "push", "--", remote_name(root,d["remote"]), ref+":"+ref)
    elif op in ("remote_add", "remote_edit", "remote_remove"):
        if op == "remote_add":
            valid_ref(root,"remotes",name)
            git(root, "remote", "add", "--", name, address(d["url"]))
        elif op == "remote_edit":
            args = ["--push"] if d.get("pushUrl") else []
            git(root, "remote", "set-url", *args, "--", remote_name(root,name), address(d["url"]))
        else:
            git(root, "remote", "remove", "--", remote_name(root,name))
    elif op in ("stash_drop", "stash_pop"):
        ids = fields(git(root, "stash", "list", "-z", "--format=%H"))
        i = d["index"]
        if type(i) is not int or not 0 <= i < len(ids) or ids[i] != d["id"]:
            raise GitError("스태시 목록이 바뀌었습니다. 새로고침하세요.")
        git(root,"stash",*(["pop","--index"] if op == "stash_pop" else ["drop"]),f"stash@{{{i}}}")
    elif op == "cherry_pick":
        verify_commit(root,d["rev"])
        mainline = ["-m", "1"] if len(line(git(root,"rev-list","--parents","-n1",d["rev"])).split())>2 else []
        git(root,"cherry-pick",*mainline,d["rev"])
    elif op == "rebase":
        git(root,"rebase",existing(root,"heads",name))
    elif op in ("continue", "abort"):
        progress = in_progress(root)
        if not progress:
            raise GitError("진행 중인 Git 작업이 없습니다.")
        if op == "abort":
            git(root,progress,"--abort")
        else:
            continue_operation(root,progress)
    else:
        raise GitError("지원하지 않는 작업입니다.")


def continue_operation(root, progress):
    if progress == "merge":
        git(root,"commit","--no-edit")
    elif progress == "cherry-pick":
        git(root,"cherry-pick","--continue",editor="true")
    else:
        # GIT_EDITOR has precedence over core.editor; accept Git's existing message.
        git(root,"rebase","--continue", editor="true")
