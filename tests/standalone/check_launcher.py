import os, sys, socket, tempfile, subprocess, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT)); LAUNCHER = str(ROOT / "launcher.py")
import launcher as L
tmp = Path(tempfile.mkdtemp())
# home_dir: env override, LOCALAPPDATA, never the program folder
os.environ["CAMPUS_HOME"] = str(tmp / "h1"); assert L.home_dir() == (tmp / "h1").resolve()
del os.environ["CAMPUS_HOME"]; os.environ["LOCALAPPDATA"] = str(tmp / "local")
assert L.home_dir() == (tmp / "local" / "CampusGuard").resolve() and "campus_safety" not in str(L.home_dir())
# prepare_home creates folders, copies .env once and never overwrites it
h = tmp / "home"; L.prepare_home(h)
assert all((h / d).is_dir() for d in ("data", "models", "reference_images", "logs")) and (h / ".env").exists()
(h / ".env").write_text("CUSTOM=1"); L.prepare_home(h); assert (h / ".env").read_text() == "CUSTOM=1"
# free port: skips a busy port
s = socket.socket(); s.bind(("127.0.0.1", 0)); busy = s.getsockname()[1]; s.listen(1)
assert L.find_free_port(busy) != busy; s.close()
# error report writes a log
L.report_error("T", "msg body", h); assert "msg body" in (h / "logs" / "startup_error.log").read_text()
# unwritable home -> exit code 2 and readable message (run in a subprocess so output is captured)
env = dict(os.environ, CAMPUS_HOME="/proc/forbidden/x")
r = subprocess.run([sys.executable, LAUNCHER], capture_output=True, text=True, env=env)
assert r.returncode == 2 and "writable folder" in r.stderr, (r.returncode, r.stderr)
# missing dependency (no fastapi/uvicorn in this sandbox) -> exit code 3 with a clear message and a log file, no traceback crash
env = dict(os.environ, CAMPUS_HOME=str(tmp / "h3"))
r = subprocess.run([sys.executable, LAUNCHER, "--no-browser"], capture_output=True, text=True, env=env)
assert r.returncode == 3 and "missing or damaged" in r.stderr, (r.returncode, r.stderr[-300:])
assert (tmp / "h3" / "logs" / "startup_error.log").exists()
# --help works without importing the app
r = subprocess.run([sys.executable, LAUNCHER, "--help"], capture_output=True, text=True); assert r.returncode == 0 and "--selftest" in r.stdout
# wait_until_up times out cleanly
assert L.wait_until_up("http://127.0.0.1:1/x", timeout=1.0) is False
print("LAUNCHER LOGIC CHECKS PASSED (home dir, port, .env, error paths exit 2/3, help)")
