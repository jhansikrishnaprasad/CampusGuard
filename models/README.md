# Model files (not shipped)

No model weights are included. Everything below is optional; the app runs without them and
shows each missing capability as **not configured**.

| Capability | File(s) | Notes |
|---|---|---|
| YOLO person detection + ByteTrack | `models/yolov8n.pt` | Download from the Ultralytics release page yourself; `pip install -r requirements-ml.txt`. AGPL-3.0. Without it OpenCV HOG is used (weaker). |
| Fighting recognition | `models/fight_model.pt` + `models/fight_model.json` | TorchScript video classifier (e.g. R3D/X3D/VideoMAE exported with `torch.jit.trace`) trained/fine-tuned on RWF-2000 etc. |
| Smoking recognition | `models/smoking_model.pt` + `models/smoking_model.json` | Needs a smoking-labelled dataset you are licensed to use. |
| ID-card detector (optional) | any YOLO `.pt`, set path in Settings -> idcard.custom_model_path | Train on your own labelled ID/lanyard photos (hundreds+). |

Sidecar JSON example (`fight_model.json`):
```json
{"name":"r3d18-rwf2000","version":"2026-01","classes":["non_violent","violent"],
 "positive_class":"violent","clip_len":16,"size":112,"layout":"BCTHW",
 "mean":[0.43,0.40,0.38],"std":[0.23,0.22,0.22]}
```
The file is the *only* source of predictions: no file -> no predictions (never random output).
