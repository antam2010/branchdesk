"""Optional UI integration test. Needs Playwright for Python and Chromium."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from desktop_pipe import desktop
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def run(base):
    repo=base/"한글 repo"
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(["git","-C",str(repo),*args],stderr=subprocess.STDOUT).decode().strip()
    git("init","-b","main")
    git("config","user.name","Branchdesk Test");git("config","user.email","qa@example.invalid")
    git("config","commit.gpgsign","false")
    (repo/"sample.txt").write_text("line 1\n")
    git("add",".");git("commit","-m","first");first=git("rev-parse","HEAD")
    (repo/"another.txt").write_text("added\n");git("add",".");git("commit","-m","second")
    (repo/"sample.txt").write_text("line 1\nline 2\n");git("add",".");git("commit","-m","third")
    last=git("rev-parse","HEAD")
    bare=base/"remote.git"
    git("init","--bare","-b","main",str(bare))
    git("remote","add","origin",str(bare));git("push","-u","origin","main")
    packed=os.environ.get("BRANCHDESK_EXE")
    if packed:
        session=desktop(packed,base)
        url=session.__enter__()
    else:
        server=subprocess.Popen([sys.executable,str(ROOT/"branchdesk.py"),"--no-browser"],cwd=base,
                                env=dict(os.environ, XDG_STATE_HOME=str(base / ".test-state")), stdout=subprocess.PIPE)
    try:
        if not packed:
            server.stdout.readline()
            url=server.stdout.readline().decode().strip()
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.getenv("CHROMIUM") or shutil.which("chromium"))
            page=browser.new_page(viewport={"width":1440,"height":900})
            errors=[]
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.set_default_timeout(7000)
            page.goto(url)
            loc=page.locator
            def click(selector):
                loc(selector).click()
            def fill(selector,value):
                loc(selector).fill(str(value))
            def tool(name):
                click('[data-tool="'+name+'"]')
            def submit():
                click("#confirm")
                expect(loc("body")).not_to_have_class("busy")
            def operation(name):
                loc("#operation").select_option(name)
            try:
                click("#open-empty")
                path_input = loc("#repo-path")
                path_input.fill("/h")
                page.get_by_role("option", name="home/", exact=True).click()
                expect(path_input).to_have_value("/home/")
                path_input.fill(str(base.parent) + "/" + base.name[:-1])
                page.get_by_role("option", name=base.name + "/", exact=True).click()
                expect(page.get_by_role("option", name=repo.name + "/", exact=True)).to_be_visible()
                expect(path_input).to_have_value(str(base) + "/")
                expect(loc("#repo-path-options li")).to_have_text(sorted([repo.name + "/", bare.name + "/"]))
                path_input.fill(str(base / "한"))
                expect(page.get_by_role("option", name=repo.name + "/", exact=True)).to_be_visible()
                path_input.press("ArrowDown")
                path_input.press("Enter")
                expect(path_input).to_have_value(str(repo) + "/")
                expect(loc("#dialog")).to_be_visible()
                submit()
                expect(loc(".logrow")).to_have_count(3)
                click('[data-rev="'+first+'"]')
                loc('[data-rev="'+last+'"]').click(modifiers=["Control"])
                expect(loc(".badge")).to_have_text("두 커밋 비교")
                expect(loc(".file")).to_have_count(2)
                loc("button[data-file]").filter(has_text="sample.txt").click()
                expect(loc(".patch")).to_contain_text("+line 2")
                click("#compare-clear")
                tool("fetch");loc("#fetch-remote").select_option("origin")
                loc("#fetch-prune").check();loc("#fetch-tags").check();submit()
                expect(loc("#toast")).to_contain_text("페치를 완료")
                tool("remote");expect(loc("#url-values input").first).to_have_value(str(bare));submit()
                tool("branch");fill("#new-name","try-ui");submit()
                expect(loc(".head-branch")).to_have_text("try-ui")
                (repo/"sample.txt").write_text("line 1\nline 2\npart one\npart two\n")
                tool("refresh");click("#go-work");click("#partial")
                loc(".pick-line").filter(has_text="part one").locator("input").check();submit()
                assert git("show",":sample.txt").endswith("part one")
                fill("#message","UI partial commit");click("#do-commit")
                expect(loc(".commit-title")).to_have_text("UI partial commit")
                assert git("show","HEAD:sample.txt").endswith("part one")
                tool("stash");fill("#answer","UI stash");submit()
                click("[data-stash]");operation("pop");submit()
                assert (repo/"sample.txt").read_text().endswith("part two\n")
                click("#go-work");click('[data-all="work"]');fill("#message","UI commit");click("#do-commit")
                expect(loc(".commit-title")).to_have_text("UI commit")
                tool("tag");fill("#tag-name","v-ui");submit();assert git("tag","-l")=="v-ui"
                tool("push");submit();assert git("rev-parse","origin/try-ui")==git("rev-parse","HEAD")
                tool("pull");submit()
                tool("flow");loc("#production").select_option("main");fill("#development","dev");submit()
                tool("flow");fill("#flow-name","ui-flow");submit()
                expect(loc(".head-branch")).to_have_text("feature/ui-flow")
                tool("flow");submit();expect(loc(".head-branch")).to_have_text("dev")
                click("#add");operation("clone");fill("#repo-url",bare);fill("#repo-path",base/"clone");submit()
                expect(loc(".repo-tab")).to_have_count(2)
                click('[data-close="1"]');expect(loc(".repo-tab")).to_have_count(1)
                click("#add")
                page.locator("#dialog [data-recent]").filter(has_text=str(base / "clone")).click()
                expect(loc(".repo-tab.active")).to_have_text("clone")
                click('[data-close="1"]')
                click('[data-close="0"]')
                page.locator("#main [data-recent]").filter(has_text=str(repo)).click()
                expect(loc(".repo-tab.active")).to_have_text(repo.name)
                assert not errors,errors
                print("PASS Chromium: directory autocomplete (mouse, keyboard, nested paths), open, two-commit diff, fetch options, remote URLs, branch, partial stage, commit, stash pop, tag, push/pull, Git Flow, clone and tabs.",flush=True)
            except Exception:
                print(page.locator("body").inner_text()[-3500:],flush=True)
                print("Page errors:",errors,flush=True)
                raise
            finally:
                browser.close()
    finally:
        if packed:
            session.__exit__(None,None,None)
        else:
            server.terminate()
            server.wait(timeout=10)


if __name__=="__main__":
    with tempfile.TemporaryDirectory(prefix="branchdesk-ui-") as directory:
        run(Path(directory))
