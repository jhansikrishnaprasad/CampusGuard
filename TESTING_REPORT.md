# CampusGuard v1.4.0 - Testing report

**Rule used in this report:** a test is marked **PASS** only if it was actually executed and its output was observed. Everything else is marked
**NOT EXECUTED** or **NOT BUILT** with the reason. No result below is estimated.

## 1. Environment of this report
| Item | Value |
|---|---|
| Where the checks ran | Linux sandbox, Python 3.12, Node 22, Chromium (Playwright). **No internet access, no Windows, no GPU, no Docker** |
| Installed there | NumPy, OpenCV (cv2), ReportLab, Pillow, Playwright, Flask. **Not installed (could not be downloaded): FastAPI, SQLAlchemy, Uvicorn, pytest, httpx, PyInstaller** |
| Consequence | The FastAPI/SQLAlchemy application and the pytest suite **could not be started in this environment**. The full suite must be run on a normal machine with `run_tests.ps1` |

## 2. Executed checks (observed results)
| ID | Test case | Expected result | Actual result | Status | Reproduce |
|---|---|---|---|---|---|
| E1 | Compliance counting rules: every uniform x ID status combination (all fall in exactly one of six groups), 5,000-person random mix, spec scenarios 1-5 (uniform only; ID only; both; uncertain ID; empty video), alert/warning/notification texts, partial-module warnings, ID-method reliability | Counts exact; `UNCERTAIN` never counted as `CARD_NOT_DETECTED`; groups sum to total | `ALL PURE-LOGIC CHECKS PASSED` (one real bug was found by this check during development - wrong key name - and fixed before the final run) | **PASS** | `python tests/standalone/check_compliance_logic.py` |
| E2 | Compliance PDF section rendered with real ReportLab; person-level CSV content | PDF bytes valid; CSV rows/columns correct; filename starting with `=` neutralised | `CSV + PDF section OK` | **PASS** (the section only, not the full PDF report: that needs the database layer) | `python tests/standalone/check_reports.py` |
| E3 | Windows launcher logic: home folder outside program folder, `.env` created once and never overwritten, free-port fallback, unwritable-home error (exit 2), missing-component error (exit 3, log written), `--help` | As listed | `LAUNCHER LOGIC CHECKS PASSED` | **PASS** | `python tests/standalone/check_launcher.py` |
| E4 | Notification state machine (the real `detectTransitions()` from `app.js`): silent baseline after page load, no repeat while polling, none after refresh, one per reprocess, job finished between polls, cancelled job, empty DB | 10 scenarios as listed | `all 10 scenarios passed` | **PASS** | `node tests/standalone/check_notifications.js` |
| E5 | Browser UI in Chromium against a **mock backend** (synthetic 100-person scenario produced by the real counting code): placeholder while running; toast with 12/8/4 after completion; cards 100/12/8/4/70/14; warning panel and ID-limitation text; partial modules shown; no duplicate toast across ~10 s of polling; no replay after reload; 7 filters return 100/12/8/4/8/6/70 rows; evidence modal; dashboard overview and alert-row navigation; zero JavaScript errors | As listed | `BROWSER UI TEST PASSED`, `JS errors: []` | **PASS** (UI logic only; **not** proof that the real API returns the same data) | see `tests/standalone/ui_mock/` (needs Playwright) |
| E6 | Browser: no sign-in screen in local mode, Sign-out hidden, **Quit CampusGuard** button visible and shows the stopped page | As listed | `NO-LOGIN + QUIT BROWSER TEST PASSED` | **PASS** (mock backend) | same |
| E7 | Static: all Python compiles; `app.js` and test JS parse | No syntax errors | `COMPILE_OK`, `node --check` clean | **PASS** | `python -m compileall -q app tests launcher.py scripts` |
| E8 | `CAMPUS_HOME` redirects `BASE_DIR`, `DATA_DIR`, models path; static folder stays with the code; default (unset) unchanged | As listed | Verified by direct run | **PASS** | `python -c "from app import config"` with/without `CAMPUS_HOME` |

## 3. NOT executed (written, but could not be run here)
| Area (from the project brief) | Test code | Count | Status | Reason |
|---|---|---|---|---|
| Application startup, login, roles, upload, **invalid file handling**, job status, review flow, dashboard vs DB, CSV/PDF reports, path traversal, settings, backup | `tests/test_api.py` | 25 | **NOT EXECUTED** | FastAPI/pytest unavailable |
| Database models, constraints, persistence | `tests/test_db.py`, `tests/test_schema_consistency.py` | 13 | **NOT EXECUTED** | same |
| Database migrations (v1 -> current, backup, v3 self-heal) | `tests/test_migrations.py` (plus 2 migration cases inside `test_compliance.py`, counted in its row) | 8 | **NOT EXECUTED** | same |
| Full workflow: upload -> video processing -> results -> review -> report -> reprocess -> **restart** | `tests/test_e2e.py` | 1 | **NOT EXECUTED** | same |
| ML modules (uniform logic, tracker, temporal grouping, activity adapters, cancellation, corrupt video), **model availability** | `tests/test_ml.py`, `tests/test_registry.py` | 31 | **NOT EXECUTED** | pytest unavailable |
| Compliance summary API, person rows, reports, overview, reprocessing, partial analysis, security | `tests/test_compliance.py` | 25 | **NOT EXECUTED** | same |
| Local no-login mode / strict login mode | `tests/test_nologin.py` | 2 | **NOT EXECUTED** | same |
| Launcher, shutdown endpoint (loopback only), build files, Docker files | `tests/test_packaging.py` | 10 | **NOT EXECUTED** | same |
| **Total pytest tests** | | **115** | **NOT EXECUTED** | Run `powershell -ExecutionPolicy Bypass -File .\run_tests.ps1` and append the real output below |

The original v1.2 project's own test suite was likewise **not run** by this release process, so the pre-existing failure status is unknown. Code reading found one
defect that those tests would have caught: `models.Review` lacked the `previous_status` column used by `events.py` and the v3 migration (fixed in v1.3 with a v4 migration; the fix itself is **not test-verified**).

## 4. Other requested verifications
| Item | Status | Detail |
|---|---|---|
| Windows `CampusGuard.exe` build | **NOT BUILT** | PyInstaller builds only on Windows. `build_exe.ps1` builds the exe and runs `CampusGuard.exe --selftest`; only a pass there means the exe works. Not tested on a clean Windows machine |
| Hosted public deployment | **NOT DEPLOYED** | Needs a server, domain and your approval. Config files exist (`docs/DEPLOYMENT.md`); go-live checklist unexecuted |
| GitHub publication | **NOT PUBLISHED** | No internet/credentials in the build environment. Use `scripts/publish_to_github.ps1` |
| Fighting / smoking models, precision/recall/F1/FPR | **NOT AVAILABLE** | No model, dataset or GPU; no metric exists. See `docs/ML_STATUS.md` |
| Uniform / ID-card accuracy | **NOT MEASURED** | No labelled campus data. Only a hand-labelled 4-person reference exercise exists (`docs/ML_METHODOLOGY.md`), which is not an accuracy estimate |
| Real CCTV video end-to-end | **NOT EXECUTED** | No footage; use `docs/COMPLIANCE.md` "How to verify with a real CCTV video" |

### 4a. Cloud verification prepared (not yet run)
`.github/workflows/tests.yml` (pytest on Linux) and `.github/workflows/build-windows-exe.yml` (build + `--selftest` on a GitHub Windows machine) were written and their YAML parses,
but **they have not run**: no repository exists yet. After publishing (docs/PUBLISH_TO_GITHUB.md) their results are the first real execution of the suite and of the exe; record them in section 6.
Dataset links in `docs/DATASETS.md` were partly verified by web search in a later pass (7 of 11 sources checked, 4 still marked "Not checked").

## 5. Known limitations (carried into the README)
HOG fallback misses small/seated people; the ID heuristic never reports "not detected"; the colour baseline is lighting-sensitive; whole-frame action models are not tied to a person;
hosted mode is untested; SQLite suits a single instance; the exe is unsigned (SmartScreen warning).

## 6. Results of the full suite on your machine (fill in)
```
> powershell -ExecutionPolicy Bypass -File .\run_tests.ps1
(paste the real output here; anything that fails is a defect to fix, not to hide)
```
