# Branchdesk

**English** · [한국어](README.ko.md) · [日本語](README.ja.md)

A local Git GUI for Windows and WSL. Manage Windows repositories with Windows Git and WSL repositories with the selected distribution's Git in the same application. The application UI is currently in Korean; this guide includes the button labels used in the app.

## Start on Windows

Double-click `Branchdesk.exe` on Windows 11 x64. The executable contains the application, web assets, icon, and setup helpers. It requires Microsoft Edge, Python 3.9+, and Git 2.28+ in the environment doing the Git work. No frontend build or third-party Python package is needed to run the app.

| Your setup | How to start |
| --- | --- |
| An existing, working WSL distribution | Continue with the default WSL environment |
| Windows without WSL | Select Windows Python and Git executables in the startup helper |
| Windows Python or Git is missing | Use **앱 전용 폴더에 설치** (install in the app's tools folder) |
| You prefer WSL | Select **WSL 방식 사용** and follow the Ubuntu/Debian setup helper |

The default Windows tools directory is `%LOCALAPPDATA%\Branchdesk\tools`: Python at `python\python.exe`, Git at `git\cmd\git.exe`. Windows installations use WinGet and its package-manifest hash verification. WinGet comes with Microsoft's **App Installer**. If a package is already installed elsewhere, connect its existing executable instead of expecting WinGet to duplicate it in a new directory.

Automatic WSL package installation supports Ubuntu/Debian. Initial WSL installation may require administrator approval, a restart, and creation of a Linux account. The helper does not replace an existing distribution or change the default one. Edge must be installed on Windows.

### Connect Windows and WSL2 environments

1. Open **실행 환경** (execution environments).
2. Click **＋ 실행 환경 추가** (add environment).
3. Choose **Windows** or **WSL2**. Enter a name and, optionally, a WSL distribution name.
4. Click **이 환경 연결하기** (connect this environment). The app discovers Python/Git and checks their versions.
5. Use **프로그램 경로 직접 지정** (set executable paths) if discovery fails or you need a specific installation.

The list shows the actual platform and distribution rather than an ambiguous “current OS.” Native Linux source launches also offer a Linux environment. Existing profile IDs and repository connections are preserved.

In **저장소 열기** (open repository), choose an environment and enter its native path:

| Environment | Example path |
| --- | --- |
| Windows | `C:\projects\my-app` or `C:/projects/my-app` |
| WSL2 | `~/projects/my-app` or `/home/user/projects/my-app` |

The add-environment button in the repository dialog lets you add a missing environment and return without losing the clone URL or folder you typed. Each repository tab remembers its environment. Git/Python paths are app settings; selecting them does not change global Git settings or the system PATH. Installers may register their own PATH entries when you explicitly install tools.

Expand **Git·Python이 없나요? 프로그램 설치** to install missing tools. Windows accepts a user directory; WSL uses the selected distribution's package manager. After installation, connect or save the environment.

**앱 시작 설정 (고급)** changes the Python environment that starts the EXE on its next launch. This is separate from each repository's Git environment and normally needs no change. Switching the host OS merges profile and tab references into the destination state directory; repository and private-key files are not copied. App startup uses Windows or the default WSL distribution; other distributions remain available for repository work.

Git identity, credentials, line endings, and SSH agents are separate between Windows and WSL. Prefer one Git environment per worktree and use `.gitattributes` to define shared line-ending rules.

### SSH keys

Expand **SSH 키 연결 · 관리** in a saved environment. Select an existing private-key path, or use **기존 키 찾기** to find keys in that environment's `.ssh` directory. **공개키 보기/복사** displays or copies only the public key for registration in your Git service account. Save with **SSH 설정 저장**. The app does not return private-key contents, edit `~/.ssh/config`, or change global Git configuration. Leaving the key blank keeps existing Git/SSH authentication.

New Ed25519 keys are created in `~/.ssh/branchdesk-NAME/id_ed25519`. Existing directories are never overwritten. App-generated keys require explicitly selecting the unencrypted-key checkbox. To use a passphrase, generate the key in that environment's terminal with `ssh-keygen -t ed25519`, connect it, and unlock it with `ssh-add`. For WSL/Linux, specify an agent socket if `SSH_AUTH_SOCK` is not inherited by the app. Windows OpenSSH uses the Windows agent service.

Authentication checks support GitHub, GitLab.com, and Bitbucket. Unknown host keys are not automatically accepted. Run the appropriate `ssh -T git@HOST` command in the selected environment, verify the service's published host fingerprint, and register your public key yourself. Use a terminal for private servers or custom connection details.

## Everyday work

| Action | Behavior |
| --- | --- |
| Repository tabs | Open, clone, or initialize repositories; restore tab order and the active tab on restart; reopen recent repositories |
| Single-click a branch | Select its commit and scroll the graph there, without checking it out; load more history if needed, within the 5,000-commit limit |
| Double-click a local branch | Open **브랜치 변경 확인** (confirm branch change) before checkout |
| Clean checkout | Off by default. Explicitly selecting **청소** discards the listed modifications, staged changes, and new files. Ignored files and nested Git repositories remain. A changed confirmation snapshot is rejected |
| File status and commits | Stage or unstage whole files or selected text changes; commit or amend the latest commit |
| New files | Show the complete selected text version with line numbers, even without an old file to compare. Index previews read staged content; commit previews read that commit. Empty files, binary content, and limits get explicit messages |
| History and comparison | Inspect commits, compare two selected commits, and view files as a list or folder tree. Double-click a file to expand its preview |
| Remote webpage | **원격** opens the repository webpage in the default browser. SSH/HTTPS Git URLs are converted to web URLs with credentials removed. Select a remote when several web destinations exist. Local-path remotes have no webpage |
| Remote settings | **원격 설정** views/copies fetch and push URLs, adds or edits remotes, and removes connections |
| Fetch, pull, push | Choose a remote/branch; optional prune/tags for fetch; fast-forward-only pull by default, with merge/rebase alternatives; push sets upstream |
| Branches and tags | Create/rename/delete merged local branches, track a remote branch, rebase, create/delete tags, and push a selected tag |
| Stashes and conflicts | Save changes, apply/pop/drop stashes, resolve conflicts by editing or choosing a side, and continue/abort operations |
| Terminal and Explorer | Open the selected repository's Windows/WSL terminal or folder; use a new Windows Terminal window when available, with PowerShell fallback; reuse an Explorer window for the same folder |
| Window activation feedback | Restore and activate the opened window. If Windows denies activation, flash the located window's taskbar button and show an app message to help you find it |
| External changes | Use **새로고침** (refresh) after working in another editor or terminal |

A regular branch switch lets Git carry compatible local changes and refuses conflicting ones. Clean checkout is destructive: review its file list before confirming.

File previews support UTF-8 and BOM-marked UTF-16, up to 192 KiB and 3,000 displayed lines, with a truncation message. Line staging supports UTF-8 regular text files up to 256 KiB and 5,000 lines per version. History starts with 150 commits and loads up to 5,000. Search covers loaded commits. Renames appear as delete/add entries.

### Menus, layout, and Git Flow

The app replaces browser right-click menus with desktop-style menus for commits, branches, tags, files, tabs, and editable text. Submenus support hover and arrow keys; Shift+F10 opens a menu, Enter activates, and Esc closes it. Text fields support copy/cut/paste/select-all/undo; use Ctrl+V if browser clipboard permission is unavailable. F5 refreshes the repository instead of reloading the page.

Drag pane separators or focus them and use arrow keys to resize. Window position, size, and maximized state are stored outside the temporary Edge profile and restored on restart and app updates. Closing while minimized restores the previous normal/maximized state on the next launch. Windows adjusts off-screen placement after monitor changes.

Commit menus include detached checkout, merge/rebase onto a selected commit, branch/tag creation, revert/cherry-pick with mainline selection, reset, archive/patch export, SHA copy, and external diff. Hard reset requires typing `HARD`. Reordering supports pick/squash/fixup/drop for a clean, linear local history with up to 100 commits after the selected base. Archives/patches are limited to 12 MiB; merge commits cannot be exported as a single format-patch. External comparison uses that environment's configured `diff.tool` (Ctrl+D).

For Git Flow, configure production/development branches in **Git Flow**, then start `feature`, `release`, or `hotfix` work. Features start from and finish into development. Releases/hotfixes finish into both branches and create a version tag. Finishing prepares merges in a temporary worktree and publishes refs in one Git transaction; conflicts stop before destination refs are updated. Push branches/tags separately.

## App updates

Use **앱 업데이트 → 새 버전 받기 → 적용 후 재시작**. If your old EXE predates the updater, close it, `git pull` once, and run the new EXE first.

The updater compares the current EXE with `Branchdesk.exe` on this repository's `main`, downloads a commit-pinned blob in the background, verifies its Git blob hash and Windows executable format, then checks SHA-256 when caching it in Windows. Applying saves tabs and commit-message drafts, closes the current app, and launches the new EXE. Resume data is shared across Windows/WSL host changes.

New versions live under `%LOCALAPPDATA%\Branchdesk\versions\<hash>\Branchdesk.exe`. A pointer redirects a recognized older launcher to the cached version on later launches. A newly pulled, unrecognized EXE takes priority. Download/helper verification failures leave the current app available.

**App update does not run `git pull`.** It updates the runnable app, leaving your checkout, README, local edits, and original EXE in place. Run `git pull` separately to update source files. Tool installations are managed separately. Automatic application requires the Windows EXE; source-mode launches do not apply executable updates.

## Run from source and build

```bash
python3 branchdesk.py
python3 branchdesk.py ~/projects/project-a ~/projects/project-b
python3 branchdesk.py --no-browser
```

On Windows, use `python` instead of `python3` as appropriate. Open the complete local URL printed in the terminal if the browser does not open automatically. Ctrl+C stops the source server. The Python runtime uses only the standard library plus your Git executable.

To make a WSL/Linux command available from other folders, adapt this alias in `~/.bashrc`:

```bash
alias branchdesk='python3 "$HOME/tools/branchdesk/branchdesk.py"'
```

Build in a Visual Studio **x64 Native Tools Command Prompt** with C++ desktop build tools and Windows Python installed:

```bat
py -3 windows/build.py
```

Output: `dist/Branchdesk.exe`. On Linux with MinGW-w64 GCC and windres installed, run `python3 windows/build.py`. Commit the rebuilt root `Branchdesk.exe` when distributing a source change through app updates.

## Local state and transport

| Data | Location |
| --- | --- |
| Windows profiles/tabs | `%LOCALAPPDATA%\Branchdesk\state` |
| WSL/Linux profiles/tabs | `~/.local/state/branchdesk`, or the `XDG_STATE_HOME` equivalent |
| Window position/size/maximized state | `%LOCALAPPDATA%\Branchdesk\window.bin` |
| EXE versions and update pointer | `%LOCALAPPDATA%\Branchdesk\versions` and `current.json` |
| Desktop update resume data | `%LOCALAPPDATA%\Branchdesk\resume-ui.json` |

The EXE listens only on Windows loopback. Authenticated HTTP requests travel over private binary pipes to the selected Python environment; WSL localhost forwarding is not required. Each window has an isolated temporary Edge profile. Closing the app allows accepted Git work to finish before backend shutdown.

## Validation

```bash
python3 -m unittest discover -s tests -v
# Optional: requires Playwright for Python and Chromium, only for testing
python3 tests/browser_smoke.py
BRANCHDESK_EXE=./Branchdesk.exe python3 tests/browser_smoke.py
```

Tests use temporary repositories and local bare remotes. They cover Git workflows, profile/worker transport, SSH key safety, selected-version file previews, branch cleanup safeguards and graph lookup, remote URL conversion, and updater error paths. Browser tests exercise menus, file previews, branch click/double-click behavior, remote choice, open-window messages, and updates; actual Windows process launching is mocked on Linux.

In a prepared Windows 11 desktop session:

```powershell
.\windows\test-launch.ps1
.\windows\test-window-state.ps1
```

Close other Branchdesk windows before the placement test. It checks normal position/size, maximized restart, and closing while minimized, then restores the previous placement file. Actual Windows installation, foreground activation, multi-monitor placement, and update restart need Windows testing; they are not executed by the Linux tests.
