"""CampusGuard Windows launcher (entry point of CampusGuard.exe; also runnable with `python launcher.py`).

What it does
  1. Chooses a persistent, writable home folder OUTSIDE the program folder: %LOCALAPPDATA%\\CampusGuard
     (override with CAMPUS_HOME). Database, videos, evidence, backups, models, logs and .env live there, so
     upgrading/replacing the program never touches your data.
  2. Starts the FastAPI app with uvicorn on 127.0.0.1 only (never exposed to the network), on port 8000 or the next free one.
  3. Opens the default browser when the server is ready.
  4. Shows readable start-up errors (message box on Windows + logs\\startup_error.log).
  5. Stops cleanly on Ctrl+C, on closing the console window, or from the UI ("Quit CampusGuard").

  CampusGuard.exe --selftest   start, probe the API, stop, exit 0 on success (used by build_exe.ps1)
  CampusGuard.exe --no-browser do not open the browser
  CampusGuard.exe --port 8123  preferred port
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

APP_NAME = "CampusGuard"
FROZEN = bool(getattr(sys, "frozen", False))


def home_dir() -> Path:
    """Persistent writable folder. Never inside a PyInstaller temp extraction folder."""
    env = os.environ.get("CAMPUS_HOME")
    if env:
        return Path(env).expanduser().resolve()
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return (Path(base) / APP_NAME).resolve()


def resource_dir() -> Path:
    """Folder holding the bundled read-only files (.env.example ...)."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def prepare_home(home: Path) -> None:
    for sub in ("data", "models", "reference_images", "logs"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    env_file, example = home / ".env", resource_dir() / ".env.example"
    if not env_file.exists() and example.exists():
        env_file.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")   # editable settings; created once, never overwritten
    notes = home / "models" / "README.txt"
    if not notes.exists():
        notes.write_text("Optional model files go here (see docs/ML_STATUS.md in the project). CampusGuard runs without them and reports each "
                         "missing capability as 'not configured'.\n", encoding="utf-8")


def find_free_port(preferred: int = 8000, tries: int = 40, host: str = "127.0.0.1") -> int:
    for p in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    raise RuntimeError(f"No free TCP port found in {preferred}-{preferred + tries - 1}. Close other programs and retry.")


def report_error(title: str, message: str, home: Path | None = None) -> None:
    """Show a start-up failure to a non-technical user and keep a log for support."""
    try:
        logdir = (home or home_dir()) / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        (logdir / "startup_error.log").write_text(f"{time.ctime()}\n{title}\n{message}\n", encoding="utf-8")
    except Exception:
        pass
    print(f"\n[{APP_NAME}] {title}\n{message}\n", file=sys.stderr, flush=True)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"{message}\n\nDetails: {(home or home_dir()) / 'logs' / 'startup_error.log'}", f"{APP_NAME} - {title}", 0x10)
        except Exception:
            pass


def wait_until_up(url: str, timeout: float = 90.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status < 500:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog=f"{APP_NAME}.exe", description="Start CampusGuard on this computer.")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="start, probe the API, stop; exit code 0 = healthy")
    args = ap.parse_args(argv)

    home = home_dir()
    if args.selftest:                                       # never touch the real data folder during a self-test
        home = Path(os.environ.get("CAMPUS_SELFTEST_HOME") or (home / "selftest")).resolve()
    try:
        prepare_home(home)
    except OSError as e:
        report_error("Cannot create the data folder", f"CampusGuard needs a writable folder at:\n{home}\n\n{e}\n\nSet the CAMPUS_HOME environment variable to a folder you can write to.", None)
        return 2
    os.environ["CAMPUS_HOME"] = str(home)                   # must be set BEFORE app.config is imported
    os.environ.setdefault("CAMPUS_ALLOW_SHUTDOWN", "true")  # local launcher only; the endpoint also requires a loopback caller
    try:
        import logging
        from logging.handlers import RotatingFileHandler
        fh = RotatingFileHandler(home / "logs" / "campusguard.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(fh)
        import uvicorn
        from app.main import app                      # imports every bundled module: a missing dependency fails here, clearly
        from app.routers import system
    except Exception:
        report_error("A required component is missing or damaged", "CampusGuard could not load its program files.\nReinstall/extract the full CampusGuard folder and try again.\n\n" + traceback.format_exc(), home)
        return 3

    try:
        port = find_free_port(args.port)
    except RuntimeError as e:
        report_error("No free network port", str(e), home)
        return 4
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info", log_config=None))
    system.shutdown_hook = lambda: setattr(server, "should_exit", True)
    t = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    t.start()
    url = f"http://127.0.0.1:{port}"
    print(f"{APP_NAME} starting... data folder: {home}", flush=True)
    if not wait_until_up(url + "/api/auth/me"):
        server.should_exit = True
        report_error("CampusGuard did not start", f"The local server did not answer within 90 seconds.\nSee {home / 'logs' / 'campusguard.log'} for the reason.", home)
        return 5
    print(f"{APP_NAME} is running at {url}\nClose this window, press Ctrl+C, or use 'Quit CampusGuard' in the app to stop.", flush=True)
    if args.selftest:
        ok = False
        try:
            with urllib.request.urlopen(url + "/api/auth/me", timeout=10) as r:
                ok = r.status == 200
            with urllib.request.urlopen(url + "/", timeout=10) as r:
                ok = ok and b"CampusGuard" in r.read()
        except Exception as e:
            print("SELFTEST error:", e)
        server.should_exit = True; t.join(30)
        print("SELFTEST PASSED" if ok else "SELFTEST FAILED")
        return 0 if ok else 1
    if not args.no_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            print(f"Open {url} in your browser.")
    try:
        while t.is_alive():
            t.join(0.5)
    except KeyboardInterrupt:
        print("Stopping CampusGuard...", flush=True)
        server.should_exit = True
        t.join(30)
    print("CampusGuard stopped.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
