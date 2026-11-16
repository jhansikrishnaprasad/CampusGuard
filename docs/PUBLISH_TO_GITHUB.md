# Publishing CampusGuard to GitHub (step by step)

You sign in to GitHub yourself, in your own browser. Never paste your password, a one-time code or an access token into a chat, a script or a file.
(If you ever did, change the password and revoke tokens at https://github.com/settings/security.)

## Option 1 - one command (recommended)
1. Install the tools once (PowerShell): `winget install Git.Git` and `winget install GitHub.cli`, then **open a new PowerShell window**.
2. Extract `CampusGuard_Source_Code.zip`, open PowerShell inside the `CampusGuard` folder.
3. Run: `powershell -ExecutionPolicy Bypass -File .\scripts\publish_to_github.ps1 -RepoName CampusGuard -Release`
4. A browser window opens: sign in to GitHub and approve the GitHub CLI. Back in PowerShell type `YES` when it shows the repository it will create.
5. The script creates the repository, pushes the code, writes your real URL into `README.md`, tags the version and starts the cloud builds.
   It prints your repository address: `https://github.com/<your-username>/CampusGuard`.

## Option 2 - GitHub website + Git (no GitHub CLI)
1. In your browser: https://github.com/new -> Repository name `CampusGuard` -> **Public** -> do **not** tick "Add a README" -> *Create repository*.
2. In PowerShell inside the extracted `CampusGuard` folder:
```powershell
git init -b main
git config user.name  "Your Name"
git config user.email "your-id+yourname@users.noreply.github.com"   # GitHub -> Settings -> Emails shows your noreply address
git add -A
git commit -m "CampusGuard v1.4.0"
git remote add origin https://github.com/<your-username>/CampusGuard.git
git push -u origin main        # Git opens a browser window to sign in
```
3. Open README.md in the folder, replace `<your-username>` with your account name, then `git add -A; git commit -m "Set repository URL"; git push`.
Prefer the prepared two-commit history? `git clone CampusGuard.bundle CampusGuard`, then use step 2 from `git remote set-url origin ...` onwards.

## Option 3 - GitHub Desktop (all clicking)
Install GitHub Desktop -> sign in -> *File -> Add local repository* (choose the extracted folder; accept "create a repository") -> commit -> *Publish repository* (untick "Keep this code private").

## After publishing: get the Windows .exe
1. Open `https://github.com/<your-username>/CampusGuard/actions`.
2. Click **Build Windows executable** -> **Run workflow** (it also runs automatically if you pushed a tag such as `v1.4.0`).
3. Wait about 5-10 minutes. A green tick means the exe was built **and its self-test passed**. Open the run -> *Artifacts* -> `CampusGuard-Windows` (a ZIP: unzip it and run `CampusGuard\CampusGuard.exe`).
   With a version tag, the same file is attached under *Releases*.
4. A **red cross** means the build or a test failed: open the run, copy the red error text and send it to be fixed. Do not share a failed build.
5. The **Tests** workflow runs the full pytest suite; its result is the first real execution of those tests. Paste the outcome into `TESTING_REPORT.md` section 6.

## Check that the repository is public and clean
* Open the repository URL in a private/incognito window: you should see the code without signing in.
* Search the repository for passwords: there must be none (`.env`, databases, videos and model files are blocked by `.gitignore`).
* Settings -> General -> *Danger zone* lets you change visibility later. Real CCTV footage, evidence images and databases must never be committed.

## Add the finishing touches
* Repository -> *About* (gear icon): add a description and topics (`fastapi`, `opencv`, `video-analytics`, `campus-safety`).
* Put the repository link in your report and submit `GITHUB_AND_DATASET_LINKS.txt` with the real address filled in.
