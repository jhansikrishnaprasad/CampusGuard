# Third-party software, licences and what they mean for you

CampusGuard's own source code is released under the **MIT licence** (see `LICENSE`). Replace the copyright line with your name/institution if
your college requires it. The table lists what the project depends on. Licence names are from the authors' knowledge of each project at the time
of writing - **verify against each package's own LICENSE file** (`pip show <pkg>` / the package page) before you formally redistribute.

| Component | Used for | Licence (verify) | In the .exe? | In the source ZIP? |
|---|---|---|---|---|
| FastAPI | Web API | MIT | yes | no (pip) |
| Starlette | ASGI toolkit used by FastAPI | BSD-3-Clause | yes | no |
| Uvicorn | Server | BSD-3-Clause | yes | no |
| SQLAlchemy | Database layer | MIT | yes | no |
| Pydantic | Validation | MIT | yes | no |
| python-multipart | File upload parsing | Apache-2.0 | yes | no |
| NumPy | Arrays | BSD-3-Clause | yes | no |
| opencv-python | Video decoding, drawing, HOG detector | OpenCV: Apache-2.0; the wheel also bundles FFmpeg (LGPL) and other libraries with their own licences - see the wheel's `LICENSE-3RD-PARTY.txt` | yes | no |
| Pandas, scikit-learn | **Training/evaluation scripts only** | BSD-3-Clause | **no** | no |
| ReportLab (open-source edition) | PDF reports | BSD-style | yes | no |
| Chart.js (CDN) | Dashboard charts | MIT | loaded from CDN at run time | no |
| pytest, httpx | Tests | MIT / BSD-3-Clause | no | no |
| PyInstaller | Building `CampusGuard.exe` | GPL-2.0-or-later **with a special exception** that allows bundling non-GPL programs | build tool only | no |
| PyTorch, torchvision (optional) | Action recognition, YOLO | BSD-3-Clause style | **no** | no |
| **Ultralytics YOLO (optional)** | YOLO person detection / ByteTrack | **AGPL-3.0** (commercial licence sold separately) | **no** | no |

## Practical implications
1. **MIT for CampusGuard is safe only because the AGPL component is optional and never bundled.** The `.exe` and the source ZIP do not contain
   Ultralytics, PyTorch or any model weights. If you install `requirements-ml.txt` yourself and *run* it privately for a project demonstration,
   AGPL obligations are generally not triggered by private use, but **if you distribute a build that contains Ultralytics, or offer it to
   other people over a network, AGPL-3.0 applies to the combined work** (you would have to offer the corresponding source under AGPL).
   For the hosted deployment, stay on the OpenCV HOG fallback or obtain a commercial Ultralytics licence / another detector, unless you are
   comfortable publishing the whole source under AGPL (it already is public on GitHub).
2. **FFmpeg inside opencv-python is LGPL**: distributing the `.exe` is fine; keep this notice and do not strip the bundled licence files.
3. **PyInstaller's exception** means the resulting `CampusGuard.exe` is not forced to be GPL.
4. **No datasets or model weights are included** in the source ZIP, the exe, or the repository (`.gitignore` blocks `*.pt`, `*.pth`, `*.onnx`, videos, databases).
   Dataset terms are summarised in `docs/DATASETS.md`; each dataset's own terms govern your use.
5. This is not legal advice. If the project leaves the academic setting (commercial use, other institutions), have the licences reviewed.
