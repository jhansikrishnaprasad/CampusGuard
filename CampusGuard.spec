# PyInstaller specification for CampusGuard.exe  (build on WINDOWS with build_exe.ps1; PyInstaller cannot cross-compile)
# Default: "onedir" (folder with CampusGuard.exe + _internal) - starts fast and triggers fewer antivirus false positives.
# Set CAMPUS_ONEFILE=1 for a single self-extracting CampusGuard.exe (slower start: it unpacks to a temp folder each launch).
import os
from PyInstaller.utils.hooks import collect_submodules

ONEFILE = os.environ.get("CAMPUS_ONEFILE") == "1"

hidden = (collect_submodules("uvicorn") + collect_submodules("app")
          + ["sqlalchemy.dialects.sqlite", "multipart", "python_multipart", "email.mime.multipart", "h11", "anyio._backends._asyncio"])
datas = [("app/static", "app/static"), (".env.example", "."), ("LICENSE", "."), ("THIRD_PARTY_NOTICES.md", "."),
         ("docs", "docs"), ("models/README.md", "models")]
# The runtime only needs OpenCV + NumPy. Heavy training-only libraries are excluded (they are NOT part of the .exe);
# optional YOLO/PyTorch support is available when running from source (setup.ps1 -WithML).
excludes = ["torch", "torchvision", "ultralytics", "pandas", "sklearn", "scipy", "matplotlib", "tkinter", "pytest", "IPython"]

a = Analysis(["launcher.py"], pathex=["."], datas=datas, hiddenimports=hidden, excludes=excludes, noarchive=False)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="CampusGuard", console=True, upx=False, icon=None)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="CampusGuard", console=True, upx=False, icon=None)
    coll = COLLECT(exe, a.binaries, a.datas, name="CampusGuard", upx=False)
