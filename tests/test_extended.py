import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import gitdesk
import partial
import workspace_ops as ops


class ExtendedTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base=Path(temp.name)
        self.root=ops.new_repository(dict(mode="init",path=str(self.base/"work repo")))
        self.g("config","user.name","Branchdesk QA")
        self.g("config","user.email","qa@example.invalid")
        self.g("config","commit.gpgsign","false")
        self.write("notes","base\n")
        self.record("initial")
        self.base_rev=self.rev()

    def g(self,*args):
        return subprocess.check_output(["git","-C",str(self.root),*args],stderr=subprocess.STDOUT).decode().strip()

    def write(self,name,data):
        (self.root/name).write_text(data)

    def record(self,msg):
        self.g("add","-A")
        self.g("commit","-m",msg)

    def rev(self,ref="HEAD"):
        return self.g("rev-parse",ref)

    def act(self,op,**kwargs):
        return gitdesk.act(self.root,dict(op=op,**kwargs))

    def remote(self,name):
        dest=self.base/(name+".git")
        self.g("init","--bare","-b","main",str(dest))
        self.act("remote_add",name=name,url=str(dest))
        return dest

    def test_compare_nonadjacent_and_reverse(self):
        self.write("한글 파일","one\n");self.record("add")
        self.write("notes","changed\n");self.record("change")
        self.g("rm","한글 파일");self.record("remove")
        for a,b in [(self.base_rev,self.rev()),(self.rev(),self.base_rev)]:
            result=gitdesk.detail(self.root,b,a)
            self.assertEqual(result["files"],[dict(code="M",path="notes")])
            self.assertEqual(gitdesk.diff(self.root,dict(kind="commit",rev=b,base=a,path="notes")).strip(),
                             self.g("diff",a,b,"--","notes"))
        self.assertFalse(gitdesk.detail(self.root,self.rev(),self.rev())["files"])

    def test_fetch_remote_prune_tags(self):
        one=self.remote("origin");self.remote("other")
        self.act("push",remote="origin");self.g("push","other","main")
        self.g("branch","gone");self.g("push","origin","gone")
        self.g("push","other","gone")
        # Modify the bare remotes directly to leave stale tracking refs in the client.
        for n in ("origin","other"):
            self.g("--git-dir="+str(self.base/(n+".git")),"update-ref","-d","refs/heads/gone")
        self.g("switch","--orphan","orphan");self.write("onlytag","x");self.record("tag only")
        self.g("tag","detached-tag");self.g("push","origin","refs/tags/detached-tag")
        self.g("tag","-d","detached-tag");self.g("switch","main");self.g("branch","-D","orphan")
        self.g("config","remote.origin.tagOpt","--no-tags")
        self.act("fetch",remote="origin")
        self.assertIn("origin/gone",self.g("branch","-r"));self.assertFalse(self.g("tag","-l"))
        self.act("fetch",remote="origin",prune=True,tags=True)
        self.assertNotIn("origin/gone",self.g("branch","-r"));self.assertIn("other/gone",self.g("branch","-r"))
        self.assertIn("gone",self.g("branch","--list","gone"));self.assertEqual(self.g("tag","-l"),"detached-tag")
        self.act("fetch",remote="",prune=True);self.assertNotIn("other/gone",self.g("branch","-r"))

    def test_branch_tag_remote_clone_and_sync(self):
        origin=self.remote("origin");self.act("push",remote="origin")
        self.act("branch",name="local",checkout=False,rev=self.base_rev)
        self.assertEqual(self.g("branch","--show-current"),"main")
        self.act("branch_rename",name="local",new="renamed");self.act("branch_delete",name="renamed")
        self.act("track",name="tracking",upstream="origin/main")
        self.assertEqual(self.g("rev-parse","--abbrev-ref","@{u}"),"origin/main")
        self.act("tag_create",name="v1",rev=self.base_rev);self.act("tag_push",name="v1",remote="origin")
        self.assertIn(self.base_rev,self.g("ls-remote","origin","refs/tags/v1"))
        self.act("tag_delete",name="v1");self.assertEqual(self.g("tag","-l"),"")
        other=ops.new_repository(dict(mode="clone",path=str(self.base/"cloned"),url=str(origin)))
        for key,val in (("user.name","Test"),("user.email","qa@example.invalid")):self.g("-C",str(other),"config",key,val)
        (other/"remote-file").write_text("new")
        self.g("-C",str(other),"add",".");self.g("-C",str(other),"commit","-m","remote");self.g("-C",str(other),"push")
        self.act("pull");self.assertTrue((self.root/"remote-file").exists())
        second=self.remote("other")
        self.act("remote_edit",name="other",url=str(origin))
        self.act("remote_edit",name="other",url=str(second),pushUrl=True)
        info=next(i for i in ops.remote_urls(self.root) if i["name"]=="other")
        self.assertEqual(info,dict(name="other",fetch=[str(origin)],push=[str(second)]))
        self.act("remote_remove",name="other");self.assertEqual(self.g("remote"),"origin")

    def test_stash_pop_drop_stale(self):
        self.write("notes","1\n");self.act("stash",message="one")
        one=gitdesk.state(self.root,50)["stashes"][0]["id"]
        self.write("notes","2\n");self.act("stash",message="two")
        two=gitdesk.state(self.root,50)["stashes"][0]["id"]
        with self.assertRaises(gitdesk.GitError):self.act("stash_drop",index=0,id=one)
        self.act("stash_drop",index=1,id=one)
        self.act("stash_pop",index=0,id=two)
        self.assertEqual((self.root/"notes").read_text(),"2\n")
        self.assertFalse(self.g("stash","list"))

    def test_flow_feature_release_hotfix(self):
        self.act("flow_init",production="main",development="dev")
        for kind,name in (("feature","login"),("release","1.0"),("hotfix","1.1")):
            self.act("flow_start",kind=kind,name=name)
            self.assertEqual(self.rev(),self.rev("main" if kind=="hotfix" else "dev"))
            self.write(kind,"content");self.record(kind);tip=self.rev()
            self.act("flow_finish",kind=kind,name=name,tag="v"+name)
            self.assertEqual(self.g("branch","--show-current"),"dev")
            self.assertFalse(self.g("branch","--list",kind+"/"+name))
            self.g("merge-base","--is-ancestor",tip,"dev")
            if kind!="feature":
                self.assertEqual(self.rev("v"+name),self.rev("main"))
                self.g("merge-base","--is-ancestor","main","dev")
            else:self.assertEqual(self.rev("main"),self.base_rev)

    def test_flow_conflict_keeps_refs_and_worktree(self):
        self.act("flow_init",production="main",development="dev")
        self.act("flow_start",kind="release",name="v2");self.write("notes","release\n");self.record("release")
        self.g("switch","dev");self.write("notes","dev\n");self.record("dev");dev=self.rev()
        self.g("switch","release/v2");topic=self.rev()
        with self.assertRaises(gitdesk.GitError):self.act("flow_finish",kind="release",name="v2",tag="v2")
        self.assertEqual((self.rev("main"),self.rev("dev"),self.rev()),(self.base_rev,dev,topic))
        self.assertFalse(self.g("tag","-l"));self.assertFalse(self.g("status","--porcelain"))

    def test_partial_new_file_and_unstage_stale(self):
        name='한글 [x] "a".txt';self.write(name,"one\ntwo\nthree")
        def get(kind):return partial.partial(self.root,dict(path=name,kind=kind))
        def apply(kind,d,*ids):return partial.partial(self.root,dict(path=name,kind=kind,stamp=d["stamp"],lines=ids),True)
        data=get("work");apply("work",data,0,2)
        self.assertEqual(self.g("show",":"+name),"one\nthree")
        with self.assertRaises(gitdesk.GitError):apply("work",data,1)
        data=get("index");apply("index",data,0)
        self.assertEqual(self.g("show",":"+name),"three")
        data=get("index");apply("index",data,0)
        self.assertFalse(self.g("ls-files","--",name))
        self.assertEqual((self.root/name).read_text(),"one\ntwo\nthree")

    def test_partial_replacement_and_delete(self):
        self.write("notes","a\nb\nc\n");self.record("lines")
        self.write("notes","a\nB\nc\nD\n")
        d=partial.partial(self.root,dict(path="notes",kind="work"))
        keep=[l["id"] for l in d["lines"] if l["text"] in ("B","b")]
        partial.partial(self.root,dict(path="notes",kind="work",stamp=d["stamp"],lines=keep),True)
        self.assertEqual(self.g("show",":notes"),"a\nB\nc")
        (self.root/"notes").unlink()
        d=partial.partial(self.root,dict(path="notes",kind="work"))
        partial.partial(self.root,dict(path="notes",kind="work",stamp=d["stamp"],lines=[l["id"] for l in d["lines"]]),True)
        self.assertFalse(self.g("ls-files","notes"))

    def test_cherry_pick_amend_rebase(self):
        self.act("branch",name="topic");self.write("topic","1");self.record("topic");c=self.rev()
        self.g("switch","main");self.write("main","1");self.record("main");self.act("cherry_pick",rev=c)
        self.act("commit",amend=True,message="amended");self.assertEqual(self.g("log","-1","--format=%s"),"amended")
        self.act("branch",name="work");self.write("x","1");self.record("work")
        self.g("switch","main");self.write("y","1");self.record("advance")
        self.g("switch","work");self.act("rebase",name="main")
        self.assertEqual(self.rev("HEAD^"),self.rev("main"))

    def test_conflict_edit_continue_and_abort(self):
        self.act("branch",name="topic");self.write("notes","topic\n");self.record("topic")
        self.g("switch","main");self.write("notes","main\n");self.record("main");before=self.rev()
        with self.assertRaises(gitdesk.GitError):self.act("merge",name="topic")
        self.assertEqual(ops.in_progress(self.root),"merge")
        self.act("abort");self.assertEqual(self.rev(),before)
        with self.assertRaises(gitdesk.GitError):self.act("merge",name="topic")
        c=partial.conflict_file(self.root,dict(path="notes"))
        self.assertTrue(c["editable"] and c["ours"] and c["theirs"])
        partial.conflict_file(self.root,dict(path="notes",choice="edit",text="merged\n",stamp=c["stamp"]),True)
        self.act("continue");self.assertFalse(ops.in_progress(self.root))
        self.assertEqual(self.g("show","HEAD:notes"),"merged")

    def test_desktop_arguments(self):
        with patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu"}), patch("workspace_ops.shutil.which", return_value="/mnt/c/bin/wt.exe"), patch("workspace_ops.subprocess.run") as run:
            ops.launch_desktop(self.root / "공백 ; 폴더", "terminal")
            self.assertEqual(run.call_args.args[0], ["/mnt/c/bin/wt.exe", "--window", "new", "new-tab", "--startingDirectory", ".", "wsl.exe", "--distribution", "Ubuntu"])
            self.assertEqual(run.call_args.kwargs["cwd"], self.root / "공백 ; 폴더")
        with patch.dict(os.environ,{"WSL_DISTRO_NAME":"Ubuntu"}), patch("workspace_ops.shutil.which",return_value="explorer.exe"), patch("workspace_ops.subprocess.check_output",return_value="WSL path\n"), patch("workspace_ops.subprocess.Popen") as spawn:
            self.act("explorer");self.assertEqual(spawn.call_args.args[0],["explorer.exe","WSL path"])

    def test_selective_pull_merge_and_rebase(self):
        source=self.remote("origin");self.act("push",remote="origin")
        clone=ops.new_repository(dict(mode="clone",path=str(self.base/"other-work"),url=str(source)))
        for k,v in (("user.name","Test"),("user.email","qa@example.invalid")):
            self.g("-C",str(clone),"config",k,v)
        for method in ("merge","rebase"):
            (clone/(method+"-up")).write_text("remote")
            self.g("-C",str(clone),"add",".");self.g("-C",str(clone),"commit","-m",method);self.g("-C",str(clone),"push")
            self.write(method+"-local","local");self.record("local "+method)
            with self.assertRaises(gitdesk.GitError):
                self.act("pull",remote="origin",target="main",strategy="ff")
            self.act("pull",remote="origin",target="main",strategy=method)
            self.g("merge-base","--is-ancestor","origin/main","HEAD")

    def test_conflict_choose_side(self):
        self.act("branch",name="other");self.write("notes","other\n");self.record("other")
        self.g("switch","main");self.write("notes","main\n");self.record("main")
        with self.assertRaises(gitdesk.GitError):self.act("merge",name="other")
        c=partial.conflict_file(self.root,dict(path="notes"))
        partial.conflict_file(self.root,dict(path="notes",choice="theirs",stamp=c["stamp"]),True)
        self.act("continue");self.assertEqual(self.g("show","HEAD:notes"),"other")

    def test_changed_index_rejects_stale_line_selection(self):
        self.write("notes","line\nnew\n")
        d=partial.partial(self.root,dict(path="notes",kind="work"))
        self.write("notes","external edit\n");self.g("add","notes");self.write("notes","another\n")
        with self.assertRaises(gitdesk.GitError):
            partial.partial(self.root,dict(path="notes",kind="work",stamp=d["stamp"],lines=[0]),True)
        self.assertEqual(self.g("show",":notes"),"external edit")
