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
    (repo/"src").mkdir();(repo/"src"/"another.txt").write_text("added\n");git("add",".");git("commit","-m","second")
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
            page.evaluate("document.addEventListener('contextmenu', event => window.contextSuppressed = event.defaultPrevented)")
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
                # An update can download while repository work continues; apply sends a draft snapshot.
                click('#app-update-open')
                expect(loc('#app-update-status')).to_contain_text('Windows EXE')
                click('#app-update-close')
                update_state = {'state': 'available', 'supported': True, 'ticket': 'test-update', 'summary': 'Test update'}
                update_calls = []
                def update_api(route):
                    request = route.request.post_data_json
                    action = request.get('action')
                    update_calls.append(request)
                    if action == 'download': update_state['state'] = 'downloading'
                    if action in ('apply', 'restart'): update_state['state'] = 'restarting'
                    route.fulfill(json={'value': update_state})
                page.route('**/api/app-update', update_api)
                click('#app-update-open'); click('#app-update-check')
                expect(loc('#app-update-download')).to_be_visible()
                click('#app-update-download')
                expect(loc('#app-update-status')).to_contain_text('내려받고')
                click('#app-update-close')
                click("#open-empty")
                path_input = loc("#repo-path")
                page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
                path_input.fill('menu-test'); path_input.press('Control+a'); path_input.click(button='right')
                modal_edit = page.get_by_role('menu', name='텍스트 편집')
                expect(modal_edit).to_be_visible()
                modal_edit.get_by_role('menuitem', name='복사', exact=False).click()
                assert page.evaluate('navigator.clipboard.readText()') == 'menu-test'
                path_input.click(button='right'); page.keyboard.press('Escape')
                expect(modal_edit).to_have_count(0)
                expect(loc('#dialog')).to_be_visible()
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
                click('#go-work'); fill('#message', 'draft survives app update')
                expect(loc('body')).not_to_have_class('busy')
                update_state['state'] = 'ready'
                expect(loc('#app-update-open')).to_have_text('업데이트 적용')
                click('#app-update-open'); click('#app-update-apply')
                expect(loc('#app-update-status')).to_contain_text('다시 여는 중')
                page.wait_for_function("!document.body.classList.contains('busy')")
                applied = next(call for call in update_calls if call['action'] == 'apply')
                assert applied['ui']['drafts'] == [[str(repo), 'draft survives app update']]
                assert applied['ui']['mode'] == 'work'
                assert any(call['action'] == 'restart' for call in update_calls)
                click('#app-update-close')
                # The real Windows process restart is deliberately stubbed in this Linux browser test.
                page.unroute('**/api/app-update', update_api)
                page.evaluate("appUpdate={state:'current'};paintAppUpdate()")
                fill('#message', ''); click('#go-log')
                origin = page.evaluate('performance.timeOrigin')
                page.keyboard.press('F5')
                expect(loc('body')).not_to_have_class('busy')
                assert page.evaluate('performance.timeOrigin') == origin
                # Every page surface gets app commands rather than browser navigation commands.
                loc('header .caption').click(button='right')
                workspace_menu = page.get_by_role('menu', name='워크스페이스')
                expect(workspace_menu).to_be_visible()
                assert page.evaluate('window.contextSuppressed')
                expect(workspace_menu.get_by_role('menuitem', name='새로고침', exact=False)).to_be_visible()
                assert page.evaluate("getComputedStyle(document.querySelector('.commit-context')).borderRadius") == '0px'
                page.keyboard.press('Escape')
                loc('.repo-tab').first.click(button='right')
                tab_menu = page.get_by_role('menu', name='저장소 탭')
                expect(tab_menu).to_be_visible()
                expect(tab_menu.get_by_role('menuitem', name='이 저장소로 전환', exact=True)).to_be_disabled()
                page.keyboard.press('Escape')
                loc('.nav-ref.current-ref').click(button='right')
                branch_menu = page.get_by_role('menu', name='브랜치 작업')
                expect(branch_menu).to_be_visible()
                expect(branch_menu.get_by_role('menuitem', name='로컬 브랜치 삭제…', exact=True)).to_be_disabled()
                page.keyboard.press('Escape')
                page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
                search = loc('#search')
                search.fill('first'); search.press('Control+a'); search.click(button='right')
                edit_menu = page.get_by_role('menu', name='텍스트 편집')
                expect(edit_menu).to_be_visible()
                edit_menu.get_by_role('menuitem', name='복사', exact=False).click()
                assert page.evaluate('navigator.clipboard.readText()') == 'first'
                search.press('Control+a'); search.click(button='right')
                edit_menu.get_by_role('menuitem', name='잘라내기', exact=False).click()
                expect(search).to_have_value('')
                search.click(button='right')
                edit_menu.get_by_role('menuitem', name='붙여넣기', exact=False).click()
                expect(search).to_have_value('first')
                search.press('Control+z'); expect(search).to_have_value('')
                search.fill('')
                expect(loc('.logrow')).to_have_count(3)
                # Commands bind to the right-clicked commit, not the prior selection.
                menu = page.get_by_role('menu', name='커밋 작업')
                first_row = loc('[data-rev="' + first + '"]')
                first_row.focus(); first_row.press('Shift+F10')
                expect(menu).to_be_visible()
                expect(menu.get_by_role('menuitem', name='병합…', exact=True)).to_be_disabled()
                page.keyboard.press('ArrowDown'); page.keyboard.press('Escape')
                expect(menu).to_have_count(0)
                expect(first_row).to_be_focused()
                first_row.click(button='right')
                menu.get_by_role('menuitem', name='브랜치…', exact=True).click()
                fill('#new-name', 'context-at-first'); submit()
                assert git('rev-parse', 'context-at-first') == first
                assert git('branch', '--show-current') == 'main'
                first_row.click(button='right')
                with page.expect_download() as download_info:
                    menu.get_by_role('menuitem', name='아카이브…', exact=True).click()
                import zipfile
                with zipfile.ZipFile(download_info.value.path()) as exported:
                    assert exported.read('source/sample.txt') == b'line 1\n'
                first_row.click(button='right')
                with page.expect_download() as download_info:
                    menu.get_by_role('menuitem', name='패치 생성…', exact=True).click()
                assert b'new file mode' in Path(download_info.value.path()).read_bytes()
                first_row.click(button='right')
                menu.get_by_role('menuitem', name='이 커밋까지 현재 브랜치를 초기화…', exact=True).click()
                loc('#reset-mode').select_option('hard')
                expect(loc('#confirm')).to_be_disabled()
                fill('#hard-confirm', 'HARD'); expect(loc('#confirm')).to_be_enabled()
                click('#cancel'); assert git('rev-parse', 'HEAD') == last
                first_row.click(button='right')
                menu.get_by_role('menuitem', name=first[:7] + '의 자식 커밋을 쌍방향 재배치…', exact=True).click()
                expect(loc('.rebase-row')).to_have_count(2)
                loc('.rebase-row select').first.select_option('squash')
                expect(loc('#confirm')).to_be_disabled()
                click('#cancel')
                last_row = loc('[data-rev="' + last + '"]')
                last_row.click(button='right')
                expect(menu.get_by_role('menuitem', name='체크아웃…', exact=True)).to_be_disabled()
                expect(menu.get_by_role('menuitem', name='외부 비교 도구', exact=False)).to_be_disabled()
                page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
                menu.get_by_role('menuitem', name='SHA 값을 클립보드에 복사', exact=True).click()
                assert page.evaluate('navigator.clipboard.readText()') == last
                last_row.click(button='right')
                menu.get_by_role('menuitem', name='추가 작업', exact=False).hover()
                submenu = page.get_by_role('menu', name='추가 작업', exact=True)
                expect(submenu).to_be_visible()
                box, sub = menu.bounding_box(), submenu.bounding_box()
                assert abs(sub['x'] - (box['x'] + box['width'])) < 5
                menu.get_by_role('menuitem', name='추가 작업', exact=False).focus()
                page.keyboard.press('ArrowRight')
                expect(submenu.get_by_role('menuitem', name='HEAD와 비교', exact=True)).to_be_focused()
                page.keyboard.press('ArrowLeft')
                expect(submenu).to_have_count(0)
                expect(menu.get_by_role('menuitem', name='태그…', exact=True)).to_be_visible()
                menu.get_by_role('menuitem', name='태그…', exact=True).click()
                fill('#tag-name', 'context-tip'); submit()
                assert git('rev-parse', 'context-tip') == last
                git('tag', '-d', 'context-tip')
                git('branch', '-d', 'context-at-first')
                tool('refresh')
                click('[data-rev="'+first+'"]')
                loc('[data-rev="'+last+'"]').click(modifiers=["Control"])
                expect(loc(".badge")).to_have_text("두 커밋 비교")
                expect(loc(".file")).to_have_count(2)
                loc("button[data-file]").filter(has_text="sample.txt").click()
                expect(loc(".patch")).to_contain_text("+line 2")
                click('[data-file-view="tree"]')
                expect(loc(".file-folder summary")).to_have_text("src")
                loc('.file-folder button[data-file]').dblclick()
                expect(loc("#diff-popup")).to_be_visible()
                expect(loc("#popup-file")).to_have_text("src/another.txt")
                expect(loc("#popup-patch")).to_contain_text("+added")
                page.keyboard.press("Escape")
                expect(loc("#diff-popup")).not_to_be_visible()
                click('[data-file-view="list"]')
                expect(loc("[data-file]").filter(has_text="src/another.txt")).to_be_visible()
                for name, pane, key, axis in [
                    ("nav", "aside", "ArrowRight", "width"),
                    ("files", ".files", "ArrowRight", "width"),
                    ("history", ".history", "ArrowDown", "height"),
                ]:
                    before = loc(pane).bounding_box()[axis]
                    loc('[data-pane="'+name+'"]').press(key)
                    assert loc(pane).bounding_box()[axis] > before
                bar = loc('[data-pane="files"]').bounding_box()
                x, y = bar["x"] + bar["width"]/2, bar["y"] + 10
                before = loc(".files").bounding_box()["width"]
                page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+55,y);page.mouse.up()
                assert loc(".files").bounding_box()["width"] > before
                click("#compare-clear")
                tool("fetch");loc("#fetch-remote").select_option("origin")
                loc("#fetch-prune").check();loc("#fetch-tags").check();submit()
                expect(loc("#toast")).to_contain_text("페치를 완료")
                tool("remote");expect(loc("#url-values input").first).to_have_value(str(bare));submit()
                tool("branch");fill("#new-name","try-ui");submit()
                expect(loc(".head-branch")).to_have_text("try-ui")
                (repo/"sample.txt").write_text("line 1\nline 2\npart one\npart two\n")
                tool("refresh");click("#go-work")
                work_file = loc('button[data-file]').filter(has_text='sample.txt')
                work_file.click(button='right')
                file_menu = page.get_by_role('menu', name='파일 작업')
                expect(file_menu).to_be_visible()
                file_menu.get_by_role('menuitem', name='파일 경로 복사', exact=True).click()
                assert page.evaluate('navigator.clipboard.readText()') == 'sample.txt'
                work_file.click(button='right')
                file_menu.get_by_role('menuitem', name='스테이징', exact=True).click()
                expect(page.locator('body')).not_to_have_class('busy')
                indexed_file = loc('.file button[data-file]').filter(has_text='sample.txt')
                indexed_file.click(button='right')
                file_menu.get_by_role('menuitem', name='스테이징 해제', exact=True).click()
                expect(page.locator('body')).not_to_have_class('busy')
                loc("button[data-file]").filter(has_text="sample.txt").dblclick()
                expect(loc("#popup-patch")).to_contain_text("+part one")
                loc("#diff-popup button").click()
                click("#partial")
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
                expect(loc('body')).not_to_have_class('busy')
                click('#environment-open')
                expect(loc('#environment-dialog')).to_be_visible()
                expect(loc('#environment-title')).to_have_text('실행 환경')
                expect(loc('#env-profile')).not_to_contain_text('현재 OS')
                expect(loc('#env-tool-settings')).not_to_have_attribute('open', '')
                click('#env-check')
                expect(loc('#env-message')).to_contain_text('연결 정상')
                click('#env-add')
                expect(loc('#env-add-heading')).to_be_visible()
                expect(loc('[data-env-kind="windows"]')).to_be_visible()
                expect(loc('[data-env-kind="wsl"]')).to_be_visible()
                page.screenshot(path=str(ROOT.parent/'environment-add.png'))
                click('[data-env-kind="local"]')
                fill('#env-name', 'UI test environment')
                # Automatic discovery should connect without asking for executable paths.
                expect(loc('#env-tool-settings')).not_to_have_attribute('open', '')
                click('#env-save')
                expect(loc('#env-message')).to_contain_text('연결 완료')
                profile_id = loc('#env-profile').input_value()
                assert len(profile_id) == 32
                click('#environment-close')
                click('#add'); operation('clone'); fill('#repo-url', bare)
                click('#repo-add-environment')
                expect(loc('#env-add-heading')).to_be_visible()
                click('#env-add-back'); loc('#env-profile').select_option(profile_id)
                click('#environment-close')
                expect(loc('#dialog')).to_be_visible()
                expect(loc('#repo-url')).to_have_value(str(bare))
                expect(loc('#repo-environment')).to_have_value(profile_id)
                operation('open'); loc('#repo-environment').select_option(profile_id)
                fill('#repo-path', repo); submit()
                expect(loc('#foot-repo')).to_contain_text('UI test environment')
                expect(loc('.repo-tab')).to_have_count(2)
                click('#environment-open')
                expect(loc('#env-profile')).to_have_value(profile_id)
                page.screenshot(path=str(ROOT.parent/'environment-settings.png'))
                click('#environment-close')
                assert not errors,errors
                print("PASS Chromium: background app-update UI, Git work during download, apply/restart requests with draft snapshot (Windows restart mocked), desktop menus, clipboard, submenus, commit actions, exports, reset confirmation, rebase plan, and existing Git workflows.",flush=True)
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
