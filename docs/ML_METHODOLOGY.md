# ML methodology, datasets and licences

## Components
| Component | Method | Licence / source | Status |
|---|---|---|---|
| Person detection | Ultralytics YOLO (e.g. `yolov8n.pt`, COCO class 0) | **AGPL-3.0** (Ultralytics) – a networked/distributed derivative must offer source under AGPL, or buy an enterprise licence. Check before any deployment beyond coursework | optional, not bundled |
| Fallback detection | OpenCV HOG+SVM pedestrian detector | Apache-2.0 (OpenCV) | bundled |
| Tracking | ByteTrack (Ultralytics) or built-in greedy IoU tracker | – | fallback IoU: IDs fragment on occlusion |
| Fighting | Any TorchScript video classifier (R3D/X3D/VideoMAE…) fine-tuned on e.g. RWF-2000, UCF-Crime | datasets have research-only terms – read each licence | **no model shipped** |
| Smoking | Same adapter; needs a smoking-labelled video dataset you may use | – | **no model shipped** |
| Uniform | HSV colour-range fractions in shirt/trouser regions of the person box | own code | working baseline |
| ID card | Heuristic (low reliability) or custom YOLO | own code | see below |

Binary violent/non-violent models are mapped only to `possible_physical_fighting`; the app never claims finer classes (pushing etc.) unless a model with those classes is wired in.

## Status vocabularies
Uniform: COMPLIANT, POSSIBLE_SHIRT_MISMATCH, POSSIBLE_TROUSER_MISMATCH, POSSIBLE_UNIFORM_MISMATCH, UNCERTAIN, NOT_ASSESSED (a mismatch needs positive evidence of an out-of-range colour; hidden/dark/small/cut-off items are never mismatches). ID card: CARD_VISIBLE, CARD_NOT_DETECTED (never proof of absence), UNCERTAIN, NOT_ASSESSED. Models: LOADED, FILE_MISSING, DEPENDENCY_MISSING, LOAD_FAILED, NOT_CONFIGURED, DISABLED, each with NOT_EVALUATED / EVALUATED.

## Uniform baseline (hsv-v2)
Region boxes (fraction of person box): shirt x15–85 %, y20–48 %; trousers x15–85 %, y56–90 %. The fraction of pixels inside each configurable HSV range is compared to `ok_fraction` (default 0.25) and `bad_fraction` (0.08): ≥ ok → in range; ≤ bad → inconsistent; between → uncertain. v2 adds shade tolerance for the light shirt only (if the region is uniformly under-exposed its brightness is rescaled up to x2 before the colour test; very dark regions are never rescaled) and an over-exposure gate. Too dark (mean V<45), too small (<140 px), legs cut off by the frame, or near-white shirts → uncertain / unable to verify. Defaults come from sampling the supplied group photo; they are a starting point to be tuned with real campus footage.

## Measured on the only reference data (1 photo, 4 people, boxes drawn by hand) – NOT an accuracy estimate
* Uniform baseline v2: 4 of 4 hand-boxed people judged COMPLIANT (v1 gave 2 compliant / 2 uncertain; lanyards and backpack straps reduce the in-range fraction). The 4 people are also the data the default ranges were derived from, so this is a sanity check, not validation.
* HOG person detector on this close-up photo: found 1 of 4 people with correct box (poor – expected; it is a weak fallback).
* ID heuristic: 0 of 4 cards found → misses are therefore reported as *uncertain*, never *not detected*.
* Pipeline speed, one synthetic 60 s 1280×720 clip, HOG, sandbox CPU: ≈14 s of processing per footage-minute (≈14 min for a 1-hour video). Your hardware will differ; measure with `scripts/evaluate.py`.
No other figures exist. Four people cannot validate anything; real evaluation needs labelled footage.

## Why two photos cannot train an ID or uniform classifier
A reliable detector needs hundreds to thousands of labelled examples across lighting, angles, distances, occlusion and non-uniform negatives. The photos are used as visual references only.

## Training / dataset workflow
1. Build a manifest CSV (`path,label,group,source,license`) – `group` = source video/camera/subject.
2. `python scripts/dataset_prepare.py validate --manifest m.csv --root <dir>` (missing/corrupt files, duplicates, writes a hash/version note).
3. `python scripts/dataset_prepare.py split --manifest m.csv --out splits.csv` – splits by **group**, asserts no train/test overlap.
4. Train outside this repo (PyTorch/Ultralytics), export TorchScript (+ sidecar JSON), place in `models/`.
5. `python scripts/evaluate.py --videos <held-out dir> --labels labels.csv --category possible_physical_fighting --save-db` → per-second P/R/F1/FPR/confusion, event-level IoU≥0.3 TP/FP/FN, seconds per footage-minute; stored in `model_evaluations` and shown in Settings.
Datasets to consider (verify licence, access, labels yourself): RWF-2000, UCF-Crime, UCF101, MOT17 (tracking), own college-uniform set (needs consent/approval), a licensed smoking dataset. Smoking evaluation must include confusers: drinking, eating, phone calls, face touching. Nothing is downloaded automatically.

## Ethics
Predictions need human confirmation before any action; clothing, ID visibility or model confidence is never evidence of misconduct; no face recognition; tracking IDs are not identities; keep footage only as long as needed.


## v1.2 findings
* **ID heuristic re-test:** a white-blob detector (card brighter and less saturated than the garment, rectangle size/aspect filters) was tried on the 4 cards in the reference photo.
  It found 0 of 4: cream/white shirts, card holders over navy trousers, and highlight pixels defeat simple rules, so no heuristic change was made. Use a trained detector (docs/TRAINING.md).
* **Tracker:** constant-velocity prediction + centre-distance matching with a size check (unit-tested on synthetic motion/occlusion gaps; not evaluated on real footage).
* **Trained uniform classifier:** logistic regression on colour statistics (JSON). Only as good as the labelled crops; evaluate with `scripts/train_uniform_classifier.py` (held-out sessions) before trusting it.
* No accuracy is claimed for any module.
