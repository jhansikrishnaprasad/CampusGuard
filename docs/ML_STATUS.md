# Machine-learning status: what works, what is missing, how to finish it

**Status date:** v1.4.0 build. **No fighting or smoking model exists in this project, and none was trained during this release.** Training needs
licensed labelled data, pretrained backbone weights and (practically) a GPU; none of these were available in the build environment (no internet,
no datasets, no GPU). Nothing below is an accuracy claim, and **no evaluation numbers exist for any module** - the application itself shows
*Not evaluated* until a real row is stored in `model_evaluations`.

## Why fighting and smoking say "not configured"
`app/ml/registry.py` looks for `models/fight_model.pt` + `models/fight_model.json` and `models/smoking_model.pt` + `models/smoking_model.json`
(or `%LOCALAPPDATA%\CampusGuard\models\` for the Windows .exe). The files are not shipped, so each module reports `FILE_MISSING`/*not configured*, the job
finishes as **Completed (partial)**, and **no predictions are produced** - never random or placeholder output. This is intentional and tested
(`tests/test_ml.py`, `tests/test_e2e.py`).

## Required model architecture (what the code can load)
| Item | Requirement (see `app/ml/activity.py`, `models/README.md`) |
|---|---|
| Model type | TorchScript video classifier (`torch.jit.trace/script`), e.g. **R3D-18** (torchvision), X3D or VideoMAE-small exported to TorchScript |
| Input | `clip_len` frames (default 16), square `size` (default 112), layout `BCTHW`, RGB, per-channel mean/std from the sidecar JSON |
| Output | logits over `classes`; `positive_class` is the class that triggers an event |
| Sampling | `window_s` 4 s windows, `stride_s` 2 s, frames sampled at `activity_fps` 4 |
| Thresholds (defaults in `app/config.py`) | fight `threshold 0.70`, `uncertain_low 0.50`; smoking `threshold 0.75`, `uncertain_low 0.55` - tune on a **validation** split, never on test |
| Temporal analysis (false-positive control, `app/ml/events.py`) | a window must score >= threshold at least `min_hits` (2) times, events shorter than `min_duration_s` (2 s fight / 3 s smoking) are dropped, hits closer than `merge_gap_s` are merged into one event, scores between `uncertain_low` and `threshold` become *uncertain* findings for the reviewer |
| Whole-frame limitation | action models see the whole frame, so these events are not attributed to a tracked person (`track_ref` is empty) |

## Datasets and difficult negatives
See [DATASETS.md](DATASETS.md). Required hard negatives:
* **Smoking:** eating, drinking, using a mobile phone, touching the face, brushing teeth, hand-to-mouth gestures.
* **Fighting:** hugging, sports (boxing bag, hockey, football), playful pushing, ordinary conversation/gesturing, crowds walking.

## Reproducible steps to finish each model (all scripts already exist)
```powershell
# 0. Install the optional stack (large download) and obtain Kinetics-400 R3D-18 weights yourself (see train_action_model.py docstring)
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -WithML
# 1. Describe your data: path,label,group,source,license  -> validate, then split BY SOURCE VIDEO (no leakage)
.\.venv\Scripts\python scripts\dataset_prepare.py validate --manifest manifest.csv --root D:\datasets\rwf2000
.\.venv\Scripts\python scripts\dataset_prepare.py split    --manifest manifest.csv --out splits.csv --seed 42
# 2. Fine-tune and export  (writes models\fight_model.pt + .json and prints CLIP-level test metrics)
.\.venv\Scripts\python scripts\train_action_model.py --manifest splits.csv --root D:\datasets\rwf2000 --target fight --pretrained models\r3d18_kinetics.pth
# 3. Measure on HELD-OUT CONTINUOUS footage (precision, recall, F1, false-positive rate per minute, event-level TP/FP/FN)
.\.venv\Scripts\python scripts\evaluate.py --videos test_videos --labels labels.csv --category possible_physical_fighting --dataset-name CampusHeldOut --dataset-version v1 --save-db
```
Repeat with `--target smoking` / `--category possible_smoking`. Report **only** the held-out numbers. Clip-level accuracy on RWF-2000 does not
transfer to your cameras: always evaluate on your own held-out campus footage with the negatives above.

## Component status
| Component | State |
|---|---|
| Person detection | OpenCV HOG fallback works; YOLO optional (needs `models/yolov8n.pt`, AGPL - see THIRD_PARTY_NOTICES.md) |
| Tracking | IoU tracker works; ByteTrack with YOLO |
| Uniform | Colour-range baseline works; **unevaluated** (no labelled campus data) |
| ID card | Heuristic (never returns "not detected"); custom YOLO detector **not trained** |
| Fighting | **Blocked:** no weights, no licensed data/GPU in this environment |
| Smoking | **Blocked:** same, plus no suitable ready dataset besides HMDB51/Kinetics clips |
| Evaluation tooling | Implemented (`scripts/evaluate.py`, `evaluate_uniform.py`); **never run on real data** |
