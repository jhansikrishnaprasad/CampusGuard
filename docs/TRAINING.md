# Training and evaluation guide (reproducible, honest)

No accuracy number exists for any module until you run the evaluation steps below on **labelled data you are allowed to use**.
Nothing in this repository claims or fakes accuracy. "Perfect" accuracy is not achievable for any vision model; what you can
do is measure it, tune thresholds on a validation set, and report the held-out result with its limits.

## Rules that apply to every module
1. **Split by recording session / source video, never by frame.** Adjacent frames of one clip are near-duplicates; putting some in
   train and some in test inflates results. `scripts/dataset_prepare.py split` and every training script enforce this.
2. Three splits: *train* (fit), *validation* (choose thresholds / epochs), *test* (report once, never tune on it).
3. Include **hard negatives** (see each section). A model that has never seen them will fire on them.
4. Get permission to use the footage; blur/avoid faces; do not store names, roll numbers or barcodes. Crops of clothing regions contain no faces.
5. Record dataset name/version/licence and thresholds with the result (`--save-db` does this) so the Settings page shows
   *Evaluated* only when a real held-out evaluation exists.

## 1. Uniform (beige shirt, navy trousers)
**Collect** 5+ different recordings/days (different cameras, lighting, distances). Aim for a few hundred shirt crops and a few hundred
trouser crops per class, with many *non-uniform* examples (white/grey/black/coloured shirts, jeans, black trousers, shorts, uniform in shadow).
```powershell
.\.venv\Scripts\python scripts\extract_person_crops.py --videos D:\footage --out crops      # writes crops + labels_todo.csv
# label: open crops\labels_todo.csv, fill the label column with  ok  or  inconsistent  (look at the crop; skip unclear ones)
.\.venv\Scripts\python scripts\train_uniform_classifier.py --root crops --csv crops\labels.csv --out models --version v1 --save-db --dataset-name CollegeCrops --dataset-version v1
```
*Labelling guideline:* `ok` = clearly beige/cream (shirt) or navy/dark blue (trousers) under the lighting in the crop; `inconsistent` = clearly another colour.
Unsure, hidden, blurry or too dark -> leave out (the app reports those as UNCERTAIN/NOT_ASSESSED anyway).
The script splits by session, prints held-out precision/recall/F1 for the **baseline and the trained model side by side**, writes
`models/uniform_shirt_clf.json` / `uniform_trouser_clf.json` (safe JSON, no pickle) and refuses to train with < 5 sessions or < 30 crops per part.
Restart the app: Settings -> Model registry shows the trained classifier (Evaluated if `--save-db` was used). Evaluate the final model once more with
`scripts/evaluate_uniform.py` on a separate test set. Delete the JSON files to go back to the baseline.

## 2. ID card / lanyard
Two reference photos cannot train a detector, and simple colour/shape rules were tested on them without success (see ML_METHODOLOGY.md).
1. Collect frames with people at CCTV distance, with and without cards (cards hidden by bags/hands, turned around, tiny, motion-blurred).
2. Label boxes (CVAT or LabelImg, YOLO format): `0 id_card`, optional `1 lanyard`. Add hard negatives: phones, papers, white shirt buttons/pockets, badges of other kinds.
3. Place official Ultralytics base weights (e.g. `yolov8n.pt`) in `models/` yourself; then:
```powershell
.\.venv\Scripts\python scripts\train_idcard_yolo.py --dataset D:\data\idcards --base models\yolov8n.pt --epochs 80 --save-db
```
It trains, evaluates on the **test split** and saves `models/idcard_yolo.pt`. Set Settings -> `idcard.custom_model_path` to it. Only then does CARD_NOT_DETECTED become
meaningful (and still never proof of absence).

## 3. Fighting and 4. Smoking
**Data:** public sets (RWF-2000 and UCF-Crime for violence; a smoking-labelled dataset you are licensed to use) plus **your own campus footage as negatives**
(conversations, hugging, playful pushing, sports, crowds, walking past each other, people eating/drinking/using phones for smoking). Check each licence.
```powershell
.\.venv\Scripts\python scripts\dataset_prepare.py validate --manifest m.csv --root D:\data\rwf2000
.\.venv\Scripts\python scripts\dataset_prepare.py split --manifest m.csv --out splits.csv
.\.venv\Scripts\python scripts\train_action_model.py --manifest splits.csv --root D:\data\rwf2000 --target fight --pretrained models\r3d18_kinetics.pth
```
(Obtain the official Kinetics-pretrained `r3d_18` weights once via torchvision on a machine with internet, save the state_dict, copy it as shown.)
The script reports **clip-level** test metrics and writes `models/<target>_model.pt` + `.json`. Clip metrics are not enough: now measure **event-level**
performance on held-out *continuous* footage (labels.csv: `video,category,start_s,end_s`):
```powershell
.\.venv\Scripts\python scripts\evaluate.py --videos test_videos --labels labels.csv --category possible_physical_fighting --dataset-name CampusTest --dataset-version v1 --save-db
```
Tune `threshold` / `uncertain_low` / `min_duration_s` / `merge_gap_s` on the validation videos, then evaluate the test videos once.
Public datasets are staged clips from different cameras: expect lower numbers on your campus. A model is "operational" only when its event-level false-alarm rate on **your** footage is acceptable to you.

## 5. Person detection / tracking
YOLO weights: place an official Ultralytics `yolov8n.pt` (or larger) in `models/` and `pip install -r requirements-ml.txt` (AGPL-3.0, see ML_METHODOLOGY.md).
Tracking uses ByteTrack then. Measure tracking on a few annotated clips (MOT17 format: MOTA/IDF1 with `motmetrics`) before trusting track continuity.

## Where results appear
`model_evaluations` table -> Settings -> Model registry ("Evaluated" + F1), PDF report, job module table. Until then everything reads **Not evaluated**.
