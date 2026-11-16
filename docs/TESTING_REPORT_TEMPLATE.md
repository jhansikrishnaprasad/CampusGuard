# Testing report (fill with measured values only)

## 1. Environment
OS / CPU / RAM / GPU: ___  Python: ___  App commit/date: ___  Models (name+version+file hash): ___

## 2. Automated tests (`run_tests.ps1`)
Date: ___  Passed/failed: ___ / ___  Failures and cause: ___

## 2b. Test files and what they need
`test_ml.py`, `test_registry.py`, `test_migrations.py`: OpenCV/NumPy only. `test_db.py`, `test_api.py`: full requirements.txt.

## 3. Dataset used for evaluation
Name / version / licence: ___  Held-out from training? (yes/no, how): ___  Videos: ___  Total minutes: ___  Positive events per class: ___

## 4. Detection metrics (`scripts/evaluate.py`)
| Category | Threshold | P | R | F1 | FPR | Event TP/FP/FN |
|---|---|---|---|---|---|---|
Confusion matrix(es): ___   Notable false positives (drinking, phone, etc.): ___   False negatives: ___

## 5. Uniform / ID evaluation
Labelled person crops: ___  Per-class P/R, % uncertain, % unable to verify: ___

## 6. Tracking (MOT17 or own): MOTA / IDF1 / ID switches: ___

## 7. Performance
| Video length | Resolution | Hardware | Total time | s per footage-minute | Peak RAM |
|---|---|---|---|---|---|

## 8. Acceptance checklist (tick only what you verified)
[ ] app starts [ ] login [ ] upload [ ] job + DB rows [ ] evidence shown [ ] review persists [ ] dashboard matches DB [ ] PDF/CSV real data [ ] restart recovery [ ] backup/restore

## 9. Limitations observed: ___
