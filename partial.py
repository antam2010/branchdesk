"""Choose individual text changes and apply them only to the Git index."""
import difflib
import hashlib
import os
import stat
import tempfile
from pathlib import Path

from gitdesk import GitError, changes, fields, git, line

LIMIT = 256 * 1024


def tree_entry(root, path):
    if not git(root, "rev-parse", "--quiet", "--verify", "HEAD", allowed=(0, 1)):
        return None
    rows = fields(git(root, "ls-tree", "-z", "HEAD", "--", path))
    if rows:
        mode, _, blob = rows[0].split("\t", 1)[0].split()
        return mode, blob


def snapshot(root, path, kind):
    if not path or path.startswith("/") or ".." in Path(path).parts or kind not in ("index", "work"):
        raise GitError("파일을 다시 선택하세요.")
    status = changes(root, path)
    if len(status)!=1 or status[0]["path"] != path:
        raise GitError("파일 상태가 바뀌었습니다.")
    rows = fields(git(root, "ls-files", "--stage", "-z", "--", path))
    index = None
    if rows:
        mode, blob, stage = rows[0].split("\t",1)[0].split()
        if stage!="0" or len(rows)!=1:
            raise GitError("충돌 파일은 해결 후 파일 단위로 스테이징하세요.")
        index = mode, blob
    filtered = None
    if kind == "index":
        other = tree_entry(root,path)
    else:
        file = root/path
        try:
            st = file.lstat()
        except FileNotFoundError:
            other = None
        else:
            if not stat.S_ISREG(st.st_mode) or st.st_size > LIMIT:
                raise GitError("256 KiB 이하 일반 텍스트 파일을 선택하세요.")
            # Let Git apply clean filters with a disposable object database.
            with tempfile.TemporaryDirectory(prefix="branchdesk-preview-") as tmp:
                blob = line(git(root,"hash-object","-w","--",path,object_dir=tmp))
                filtered = git(root,"cat-file","blob",blob,limit=LIMIT,object_dir=tmp)
            other = ("100755" if st.st_mode & stat.S_IXUSR else "100644", blob)
    def content(entry,raw=None):
        if not entry:
            return []
        if entry[0] not in ("100644","100755"):
            raise GitError("일반 텍스트 파일만 줄을 선택할 수 있습니다.")
        if raw is None:
            raw = git(root, "cat-file","blob",entry[1],limit=LIMIT)
        if b"\0" in raw:
            raise GitError("바이너리 파일은 파일 단위로 스테이징하세요.")
        try:
            raw.decode("utf-8")
        except UnicodeError:
            raise GitError("줄 선택은 UTF-8 텍스트를 지원합니다.")
        # Only LF delimits a Git diff line; CR remains part of its contents.
        chunks=raw.split(b"\n")
        lines=[part+b"\n" for part in chunks[:-1]]
        if chunks[-1]:
            lines.append(chunks[-1])
        if len(lines)>5000:
            raise GitError("5,000줄 이하 파일에서 줄을 선택할 수 있습니다.")
        return lines
    old, new = content(index), content(other,filtered)
    stamp = hashlib.sha256(repr((path,kind,index,other)).encode("utf-8","surrogatepass")).hexdigest()
    return index,other,old,new,stamp


def transform(old,new,chosen=None):
    output, display = [], []
    for tag,a,b,c,d in difflib.SequenceMatcher(None,old,new).get_opcodes():
        if tag == "equal":
            output.extend(old[a:b])
            continue
        for side,lines,offset in (("-",old[a:b],a),("+",new[c:d],c)):
            for i,raw in enumerate(lines):
                ident=len(display)
                display.append(dict(id=ident,side=side,number=offset+i+1,text=raw.decode().rstrip("\n")))
                picked=chosen is not None and ident in chosen
                if (side=="+" and picked) or (side=="-" and not picked):
                    output.append(raw)
    return output,display


def quoted(prefix,path):
    raw = prefix+os.fsencode(path)
    return b'"'+b"".join(bytes([n]) if 32<=n<127 and n not in (34,92) else b"\\%03o"%n for n in raw)+b'"'


def partial(root,data,apply=False):
    path,kind = data["path"],data["kind"]
    index,other,old,new,stamp=snapshot(root,path,kind)
    chosen=set(data.get("lines",[]))
    output,display=transform(old,new,chosen)
    if not apply:
        return dict(stamp=stamp,lines=display)
    if data["stamp"]!=stamp or not chosen or not chosen.issubset(range(len(display))):
        raise GitError("변경 내용이 바뀌었습니다. 비교 화면을 다시 여세요.")
    remove=other is None and len(chosen)==len(display)
    a,b=quoted(b"a/",path),quoted(b"b/",path)
    header=b"diff --git "+a+b" "+b+b"\n"
    if not index:
        header+=b"new file mode "+other[0].encode()+b"\n"
        a=b"/dev/null"
    elif remove:
        header+=b"deleted file mode "+index[0].encode()+b"\n"
        b=b"/dev/null"
    patch=difflib.diff_bytes(difflib.unified_diff,old,output,fromfile=a,tofile=b,n=max(len(old),len(output)))
    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(header)
        for row in patch:
            tmp.write(row)
            if not row.endswith(b"\n"):
                tmp.write(b"\n\\ No newline at end of file\n")
        tmp.flush()
        git(root,"apply","--cached","--whitespace=nowarn","--",tmp.name)


def conflict_file(root, data, resolve=False):
    path = data["path"]
    if not path or path.startswith("/") or ".." in Path(path).parts:
        raise GitError("파일 경로를 확인하세요.")
    rows = fields(git(root, "ls-files", "-u", "-z", "--", path))
    entries = {}
    for row in rows:
        meta, name = row.split("\t",1)
        if name == path:
            mode, blob, stage = meta.split()
            entries[stage] = (mode,blob)
    if not entries:
        raise GitError("충돌 상태를 다시 확인하세요.")
    file = root/path
    try:
        st = file.lstat()
    except FileNotFoundError:
        st = None
    stamp=hashlib.sha256(repr((rows,(st.st_ino,st.st_size,st.st_mtime_ns) if st else None)).encode("utf-8","surrogatepass")).hexdigest()
    editable=all(mode in ("100644","100755") for mode,_ in entries.values()) and (
        st is None or stat.S_ISREG(st.st_mode) and st.st_size<=LIMIT)
    current=b""
    if editable and st:
        current=file.read_bytes()
        try:
            current.decode()
            editable=b"\0" not in current
        except UnicodeError:
            editable=False
    if not resolve:
        return dict(stamp=stamp,editable=editable,text=current.decode() if editable else "",
                    ours="2" in entries,theirs="3" in entries)
    if data["stamp"]!=stamp:
        raise GitError("파일이 바뀌었습니다. 충돌 화면을 다시 여세요.")
    choice=data["choice"]
    if choice in ("ours","theirs"):
        stage="2" if choice=="ours" else "3"
        if stage not in entries:
            git(root,"rm","--",path)
            return
        git(root,"checkout","--"+choice,"--",path)
    elif choice=="edit" and editable:
        tmp=None
        try:
            with tempfile.NamedTemporaryFile(dir=file.parent,delete=False) as dest:
                tmp=Path(dest.name)
                dest.write(data["text"].encode())
            tmp.chmod(stat.S_IMODE(st.st_mode) if st else 0o644)
            tmp.replace(file)
        finally:
            if tmp:
                tmp.unlink(missing_ok=True)
    else:
        raise GitError("해결 방법을 선택하세요.")
    git(root,"add","-A","--",path)
