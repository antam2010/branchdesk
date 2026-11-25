"""Operations on an explicitly selected commit in the history context menu."""
import base64
from pathlib import Path
import shlex
import sys
import tempfile

from gitdesk import GitError, changes, current, git, line, verify_commit
from workspace_ops import in_progress, oid

EXPORT_LIMIT = 12 * 1024 * 1024
ACTIONS = {"checkout_commit", "merge_commit", "rebase_commit", "reset_commit", "revert_commit",
           "reorder_commits", "external_diff", "cherry_pick_commit"}


def ancestors(root, rev):
    return line(git(root, "rev-list", "--parents", "-n1", rev)).split()[1:]


def _is_ancestor(root, base, head):
    # Count commits reachable from base but not head, including the base itself.
    return line(git(root, "rev-list", "--count", base, "--not", head)) == "0"


def linear_children(root, base, head):
    if not _is_ancestor(root, base, head):
        raise GitError("현재 브랜치에 포함된 커밋을 선택하세요.")
    rows = line(git(root, "rev-list", "--reverse", "--topo-order", "--parents", base + ".." + head)).splitlines()
    if not rows or len(rows) > 100:
        raise GitError("선택한 커밋 이후 1~100개의 커밋을 정리할 수 있습니다.")
    previous, ids = base, []
    for row in rows:
        rev, *parents = row.split()
        if parents != [previous]:
            raise GitError("병합 커밋이 없는 단일 이력에서만 순서를 정리할 수 있습니다.")
        ids.append(rev)
        previous = rev
    return ids


def context(root, rev):
    verify_commit(root, rev)
    head, branch = oid(root, "HEAD"), current(root)
    progress, dirty = in_progress(root), bool(changes(root))
    parents = ancestors(root, rev)
    ready = "진행 중인 Git 작업을 먼저 마치세요." if progress else "변경 내용을 커밋하거나 스태시에 보관하세요." if dirty else ""
    local = ready or ("로컬 브랜치를 먼저 체크아웃하세요." if not branch else "")
    contained = _is_ancestor(root, rev, head)
    permissions = {
        "checkout_commit": ready or ("현재 HEAD입니다." if rev == head else ""),
        "merge_commit": local or ("현재 브랜치에 이미 포함된 커밋입니다." if contained else ""),
        "rebase_commit": local or ("현재 브랜치에 이미 포함된 커밋입니다." if contained else ""),
        "reset_commit": ("진행 중인 Git 작업을 먼저 마치세요." if progress else "") or
                        ("로컬 브랜치를 먼저 체크아웃하세요." if not branch else ""),
        "revert_commit": local,
        "cherry_pick_commit": local or ("현재 HEAD입니다." if rev == head else ""),
        "external_diff": "외부 비교 도구(diff.tool)를 먼저 설정하세요." if not line(git(root, "config", "--get", "diff.tool", allowed=(0, 1))) else
                         "첫 커밋에는 비교할 부모가 없습니다." if not parents else "",
        "reorder_commits": local,
    }
    if not permissions["reorder_commits"]:
        try:
            linear_children(root, rev, head)
        except GitError as error:
            permissions["reorder_commits"] = str(error)
    return dict(rev=rev, head=head, branch=branch, parents=parents, permissions=permissions,
                subject=line(git(root, "show", "-s", "--format=%s", rev)))


def rebase_plan(root, rev):
    data = context(root, rev)
    if data["permissions"]["reorder_commits"]:
        raise GitError(data["permissions"]["reorder_commits"])
    data["commits"] = [dict(id=entry, subject=line(git(root, "show", "-s", "--format=%s", entry)))
                       for entry in linear_children(root, rev, data["head"])]
    return data


def export(root, data):
    rev, kind = data.get("rev"), data.get("kind")
    verify_commit(root, rev)
    if kind == "archive":
        blob = git(root, "archive", "--format=zip", "--prefix=source/", rev, limit=EXPORT_LIMIT)
        extension, mime = "zip", "application/zip"
    elif kind == "patch":
        if len(ancestors(root, rev)) > 1:
            raise GitError("병합 커밋은 단일 패치로 만들 수 없습니다. 아카이브를 사용하세요.")
        blob = git(root, "format-patch", "--stdout", "--binary", "--no-signature", "--root", "-1", rev,
                   limit=EXPORT_LIMIT)
        extension, mime = "patch", "text/plain"
    else:
        raise GitError("내보내기 형식을 확인하세요.")
    return dict(name="commit-" + rev[:12] + "." + extension, mime=mime,
                content=base64.b64encode(blob).decode("ascii"))


def mainline(data, parents):
    if len(parents) <= 1:
        return []
    parent = data.get("mainline", 1)
    if type(parent) is not int or not 1 <= parent <= len(parents):
        raise GitError("병합 커밋의 기준 부모를 선택하세요.")
    return ["-m", str(parent)]


def operate(root, data):
    op, rev = data["op"], data.get("rev")
    ctx = context(root, rev)
    if data.get("expectedHead") != ctx["head"] or data.get("expectedBranch") != ctx["branch"]:
        raise GitError("현재 브랜치 또는 HEAD가 바뀌었습니다. 새로고침한 뒤 다시 실행하세요.")
    if ctx["permissions"].get(op):
        raise GitError(ctx["permissions"][op])
    if op == "checkout_commit":
        git(root, "switch", "--detach", rev)
    elif op == "merge_commit":
        git(root, "merge", "--no-edit", rev)
    elif op == "rebase_commit":
        git(root, "rebase", "--no-autostash", rev)
    elif op == "revert_commit":
        git(root, "revert", "--no-edit", *mainline(data, ctx["parents"]), rev)
    elif op == "cherry_pick_commit":
        git(root, "cherry-pick", *mainline(data, ctx["parents"]), rev)
    elif op == "reset_commit":
        mode = data.get("mode")
        if mode not in ("soft", "mixed", "hard"):
            raise GitError("초기화 방식을 선택하세요.")
        if mode == "hard" and data.get("confirmation") != "HARD":
            raise GitError("변경 내용을 버리려면 HARD를 입력하세요.")
        git(root, "reset", "--" + mode, rev)
    elif op == "external_diff":
        git(root, "difftool", "--no-prompt", ctx["parents"][0], rev, "--", timeout=600)
    elif op == "reorder_commits":
        ids = linear_children(root, rev, ctx["head"])
        plan = data.get("plan")
        if not isinstance(plan, list) or len(plan) != len(ids) or any(not isinstance(row, dict) for row in plan):
            raise GitError("정리할 커밋 목록을 확인하세요.")
        if sorted(row.get("id", "") for row in plan) != sorted(ids):
            raise GitError("커밋 목록이 바뀌었습니다. 다시 확인하세요.")
        kept, todo = False, []
        for row in plan:
            action = row.get("action")
            if action not in ("pick", "squash", "fixup", "drop") or (action in ("squash", "fixup") and not kept):
                raise GitError("첫 번째로 유지할 커밋은 pick이어야 합니다.")
            kept = kept or action != "drop"
            todo.append(action + " " + row["id"])
        with tempfile.TemporaryDirectory(prefix="branchdesk-rebase-") as directory:
            editor = Path(directory) / "sequence.py"
            editor.write_text("from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text(" +
                              repr("\n".join(todo) + "\n") + ", encoding='utf-8')\n", encoding="utf-8")
            git(root, "-c", "rebase.updateRefs=false", "rebase", "--interactive", "--no-autostash", rev, editor="true",
                sequence_editor=shlex.quote(sys.executable.replace("\\", "/")) + " " + shlex.quote(str(editor).replace("\\", "/")))
    else:
        raise GitError("지원하지 않는 커밋 작업입니다.")
