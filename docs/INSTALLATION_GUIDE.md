# Installation guide (three ways)

## A. Run the Windows executable (no Python needed) - *after it has been built*
`CampusGuard.exe` has to be **built on Windows** (see C below); it is not included in this archive unless the release notes say it was built and self-tested.
1. Copy the whole `CampusGuard` folder (folder build) anywhere, e.g. `C:\CampusGuard\`.
2. Double-click `CampusGuard.exe`. A console window opens, the browser opens http://127.0.0.1:8000 and you land on the dashboard.
3. Your data is stored in `%LOCALAPPDATA%\CampusGuard` (database `data\campus_safety.db`, videos, evidence, backups, `models\`, `logs\`, editable `.env`).
   Replacing the program folder with a newer build never touches it.
4. Stop: click **Quit CampusGuard** in the sidebar, press Ctrl+C, or close the console window.
5. Windows SmartScreen may warn about an unsigned program: choose *More info -> Run anyway* only if you built/received it from a source you trust.
6. Problems: read `%LOCALAPPDATA%\CampusGuard\logs\campusguard.log` and `startup_error.log`.

## B. Run from source (Windows PowerShell)
```powershell
# Python 3.10-3.12 (64-bit) from python.org, "Add to PATH" ticked
cd CampusGuard
powershell -ExecutionPolicy Bypass -File .\setup.ps1          # creates .venv, installs requirements.txt, copies .env.example -> .env
powershell -ExecutionPolicy Bypass -File .\run.ps1            # http://127.0.0.1:8000
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1      # runs the automated tests
# optional: .\setup.ps1 -WithML (PyTorch + Ultralytics, large; AGPL note in THIRD_PARTY_NOTICES.md)
# optional: winget install Gyan.FFmpeg  (AVI/MOV preview and playable evidence clips)
```
Login is off by default (local single-user mode). To require a password add `CAMPUS_REQUIRE_LOGIN=true` to `.env`; the admin password is printed once on first start
(or set `ADMIN_PASSWORD` in `.env` before first start). No credentials are shipped in this project.

## C. Build the .exe yourself (Windows 10/11, 64-bit)
```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1            # -> dist\CampusGuard\CampusGuard.exe, then runs its own --selftest
# single-file variant:  .\build_exe.ps1 -OneFile                    # -> dist\CampusGuard.exe
```
The script fails (non-zero exit) if the packaged exe cannot start, answer its API and serve the interface. **Only distribute a build whose self-test says
`SELF-TEST PASSED`.** To test on a "clean" machine: copy `dist\CampusGuard` to a PC/VM that has no Python and double-click the exe.

## D. Hosted deployment
See [DEPLOYMENT.md](DEPLOYMENT.md).
