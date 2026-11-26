# Branchdesk

**English** · [한국어](README.ko.md) · [日本語](README.ja.md)

**Manage Windows and WSL2 Git projects in one app.** Review changed files, commit your work, switch branches, and pull or push through a graphical interface. Choose English, Korean, or Japanese.

New to the app? Follow [Launch](#1-launch-the-app) → [Open a project](#2-open-the-project-you-want-to-work-on) → [Commit and push](#3-edit-files-then-commit-and-push). Advanced options and source builds are in the [detailed reference](docs/reference.md).

## 1. Launch the app

1. [Download Branchdesk.exe](https://github.com/antam2010/branchdesk/raw/refs/heads/main/Branchdesk.exe) and save it in a folder of your choice. If you have already cloned this repository, use its `Branchdesk.exe`.
2. Double-click `Branchdesk.exe` on Windows 11 x64.
3. If setup appears, connect Git and Python. You can use Windows alone, or an existing WSL environment.
4. Choose **English** from the language selector at the top right. The app remembers your choice.

You need Git 2.28 or later and Python 3.9 or later. Connect existing executables, or use **Install in app tools folder** in setup if they are missing. Microsoft Edge on Windows displays the app window. Using the EXE requires no source build or Python package installation.

## 2. Open the project you want to work on

The folder you open here is **your development project's Git repository**. It is separate from the folder where you keep Branchdesk itself.

### If the project is already on your PC

1. Choose **Open repository → Open existing repository**.
2. Select the environment to use for this repository, then enter the project folder's path.
3. Confirm to open its tab and commit history.

An environment tells the app **where to run Git for this project**.

| Where the project lives | Environment to select | Example path |
| --- | --- | --- |
| A Windows folder | Windows | `C:\projects\my-app` |
| A Linux folder in WSL, such as Ubuntu | The matching WSL2 distribution | `/home/user/projects/my-app` or `~/projects/my-app` |

If the environment is missing, use **＋ Add environment**, choose Windows or WSL2, and click **Connect this environment**. The app detects Git and Python. Expand **Set executable paths (optional)** only if detection fails or you need a specific installation.

Windows and WSL projects can stay open in separate tabs in the same app. For a WSL project, choose its WSL environment and use a `/home/...` path so its own Git handles the files.

### If the project is only on GitHub or GitLab

1. Copy the project's Git clone URL from the service, for example `https://github.com/your-account/my-app.git`.
2. Choose **Open repository → Clone remote repository**.
3. Enter the URL, select an environment, and enter a **new local folder path** to create. Then run the operation.

Cloning downloads a project to your PC for the first time. Use **Open existing repository** for a project you have already downloaded. To start a completely new project, choose **Create empty repository**.

## 3. Edit files, then commit and push

For example, after editing a login screen on your `feature/login` branch:

1. Save your changes in an editor such as VS Code or IntelliJ.
2. In Branchdesk, click **Refresh**, then open **File status** on the left.
3. Click a changed file to review its changes. New text files show their full contents.
4. Click **＋** beside each file to include it in this commit. This is called staging. Use **−** to unstage a file you selected by mistake.
5. Write a message such as `Add validation to the login form`, then click **Commit**.
6. To share the work, choose **Push**, check the remote (usually `origin`) and destination branch, and confirm.

**Commit saves a record on your PC. Push sends those commits to GitHub, GitLab, or another remote.** Staging selects what goes into this commit; other changes remain available for a later commit.

To request a code review, open the repository webpage with **Remote** and create a PR/MR in your Git service.

If Commit is disabled, check that you have staged changes and entered a message. For a missing author name/email, see [Troubleshooting](#troubleshooting).

## 4. Get your team's latest changes

Before starting work, check your current branch and use **Pull** to bring it up to date. Commit unfinished changes or temporarily save them with **Stash** first.

| Button | What it does | When to use it |
| --- | --- | --- |
| Fetch | Gets the latest remote commit/branch information without changing your working files | Inspect your team's changes first |
| Pull | Integrates remote changes into your current local branch | Bring your project up to date |
| Push | Sends local commits to the selected remote branch | Share completed work |
| Remote | Opens the connected repository's webpage | View PRs/MRs on GitHub or GitLab |
| Remote settings | Shows, adds, or edits remote URLs | Manage connections such as `origin` |

Pull defaults to **Fast-forward only**, which proceeds when the histories have not diverged. A refused pull does not erase your work. If merging or rebasing is needed, follow your team's branch workflow.

## 5. Inspect, switch, or create a branch

In the left branch list, **single-click to reveal the branch's commit in the graph; double-click to open the switch confirmation**. A single click does not change your working branch.

Check the destination name before confirming a switch. **Clean checkout (discard modified, staged, and new files)** is off by default. Turning it on discards the listed uncommitted changes, so leave it off when you want to keep your work.

For new work, choose **Branch → Create branch**, enter a name such as `feature/login`, and select its starting point. **Check out after creation** switches to the new branch immediately. For a branch that exists only on the remote, use **Track remote branch** to create a local working branch.

See the [feature reference](docs/reference.md#everyday-work) for merging, resolving conflicts, reverting commits, tags, and Git Flow.

## 6. Use Home and saved projects

- Click **Home** at the top left to see recent project names and paths. Click an entry to reopen it or return to its existing tab.
- Home keeps your open tabs and commit-message drafts available.
- A tab's **×** closes just that tab. You can reopen it from the recent list.
- **Remove from list** removes the tab and saved entry without deleting the actual project folder. It also works for paths that have been moved or deleted.

In **History**, click a commit to inspect it. Double-click a file to enlarge its preview. Right-click a commit, file, branch, or tab for actions on that item. Use **Terminal** or **Explorer** to open the current project folder.

## 7. Update the app

Choose **App update → Download new version → Apply and restart** at the top right. You can keep working during the download; applying the update restarts the app. Open repositories and commit-message drafts are restored.

**Updating the app and pulling a project are separate actions.** App update refreshes the runnable Branchdesk app. It does not run `git pull` in your development project. Branchdesk's source and README files also need a separate `git pull` to refresh your checkout.

## Troubleshooting

| Situation | What to check |
| --- | --- |
| Git or Python cannot be found | Check the selected environment in **Environments**. Set executable paths if detection fails, or use **Install required programs**. |
| Clone, fetch, pull, or push authentication fails | Authentication belongs to the project's selected Windows/WSL environment. For SSH, see below; for HTTPS, check your Git service's authentication setup. |
| A commit asks for your name/email | Set your Git identity in that project's **Terminal**, as shown below. |
| Pull is refused or reports conflicts | Commit or stash local changes first. If both sides have separate commits, merge or rebase according to your team's workflow. See the reference for conflict resolution. |
| Pull, Push, or Remote is disabled | Check the connection in **Remote settings**. For an empty repository, make its first commit before sharing work. |
| A deleted project folder cannot be opened | Use **Remove from list** in the error dialog or recent list. |
| Terminal or Explorer does not appear in front | Check the app's result message and the Windows taskbar for the opened window. |
| App update reports a `Replace` / invalid-path error | An older update helper has a bug. Close the app, run `git pull` **in the Branchdesk repository folder**, then launch that folder's new `Branchdesk.exe` once. |
| `git pull` stops because README or other local files have changed | Commit your edits or stash them before pulling. You do not need to delete your edits or force-reset the repository. |

To set your identity **only for the current project**, run these commands in its terminal, replacing the example name and email:

```bash
git config user.name "Your Name"
git config user.email "you@example.com"
```

### Connect an SSH key

If SSH already works in the selected environment, you can keep using its existing setup. To connect another key, open **Environments → SSH keys (optional)**, select an existing key, and click **Save SSH settings**. You can also generate a new key if needed. Register **only the public key** in your GitHub/GitLab account; keep the private key to yourself. See [SSH details](docs/reference.md#ssh-keys) for passphrases and private Git servers.

## Learn more

The [detailed reference](docs/reference.md) covers executable paths, SSH, feature options, running from source, building the EXE, and testing. You can use the app without going through the build or test steps.
