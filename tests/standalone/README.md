# Standalone checks (no FastAPI / SQLAlchemy / pytest needed)
These ran in the release-build environment, which had no internet and therefore could not install the web stack. They import the **real** project code
(only the database-layer imports are stubbed). They complement, and do not replace, the full pytest suite (`run_tests.ps1`).

| Script | Needs | What it proves |
|---|---|---|
| `check_compliance_logic.py` | Python | Counting rules, exclusivity of the six groups, "uncertain is never not-detected", alert/warning texts |
| `check_reports.py` | Python + reportlab | Compliance PDF section renders; people-CSV content and formula-injection protection |
| `check_launcher.py` | Python | Launcher home folder, `.env`, port fallback, error exits (2 = no writable folder, 3 = missing component) |
| `check_notifications.js` | Node.js | Real `detectTransitions()` from `app.js`: no duplicate toasts, none after refresh, one per reprocess |
Run: `python tests/standalone/check_compliance_logic.py` (etc.), `node tests/standalone/check_notifications.js`.
The browser UI tests (Playwright + a mock backend) are described in `TESTING_REPORT.md`; their sources are in `ui_mock/`.
