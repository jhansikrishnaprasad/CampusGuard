"""Evaluate the uniform colour baseline (and ID-card detector) on LABELLED person crops.

crops.csv columns: image,shirt,trouser[,id]     (image path relative to --root; each image is ONE full-body person crop)
  shirt / trouser truth: ok | inconsistent      id truth (optional): visible | hidden
  python scripts/evaluate_uniform.py --root crops --csv crops.csv --dataset-name CollegeCrops --dataset-version v1 [--save-db]
Crops must come from a test set that was NOT used to tune the colour ranges. Abstentions (uncertain / unable to
verify) are reported separately and count as misses for recall."""
import argparse, json, sys
from pathlib import Path
import cv2, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config
from app.ml import metrics, uniform
from app.ml.idcard import IdCardDetector

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True); ap.add_argument("--csv", required=True)
ap.add_argument("--dataset-name", default="unnamed"); ap.add_argument("--dataset-version", default="unversioned")
ap.add_argument("--save-db", action="store_true")
a = ap.parse_args()
df = pd.read_csv(a.csv)
if df.empty:
    sys.exit("No labelled rows - refusing to produce numbers.")
S = config.DEFAULT_SETTINGS
rows = {"shirt": [], "trouser": []}; idrows = []
idc = IdCardDetector(S["idcard"])
for r in df.itertuples():
    im = cv2.imread(str(Path(a.root) / r.image))
    if im is None:
        sys.exit(f"Cannot read image {r.image}")
    im = cv2.copyMakeBorder(im, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=(128, 128, 128))  # keep the person box off the frame edge
    h, w = im.shape[0] - 20, im.shape[1] - 20
    cfg = {**S["uniform"], "min_person_height_px": 0}
    res = uniform.assess_person(im, (10, 10, 10 + w, 10 + h), cfg)
    rows["shirt"].append((r.shirt, res["shirt"]["status"])); rows["trouser"].append((r.trouser, res["trouser"]["status"]))
    if hasattr(r, "id") and isinstance(r.id, str):
        idrows.append((r.id, idc.detect(im, (10, 10, 10 + w, 10 + h))["status"]))
out = {k: metrics.crop_metrics(v) for k, v in rows.items()}
for k, m in out.items():
    print(f"{k}: n={m['n']} P={m['precision']} R={m['recall']} F1={m['f1']} abstain={m['abstention_rate']} confusion={m['confusion']}")
if idrows:
    vis = sum(1 for t, p in idrows if t == "visible"); hit = sum(1 for t, p in idrows if t == "visible" and p == "detected")
    print(f"ID card: {len(idrows)} crops, visible-in-truth={vis}, detected={hit} (recall {hit / vis if vis else None})")
if a.save_db:
    from app.database import SessionLocal, get_engine, init_db
    from app.models import ModelEvaluation
    get_engine(); init_db()
    pooled = metrics.crop_metrics(rows["shirt"] + rows["trouser"])
    with SessionLocal() as db:
        db.add(ModelEvaluation(model_name="uniform_baseline", model_version="hsv-v2", dataset_name=a.dataset_name,
                               dataset_version=a.dataset_version, precision=pooled["precision"], recall=pooled["recall"],
                               f1=pooled["f1"], sample_count=len(df), positive_count=pooled["tp"] + pooled["fn"],
                               thresholds=json.dumps({k: S["uniform"][k] for k in ("beige", "navy", "ok_fraction", "bad_fraction")}),
                               status="completed", notes=f"pooled shirt+trouser, positive='inconsistent'; abstention={pooled['abstention_rate']}"))
        if idrows:
            vis = [x for x in idrows if x[0] == "visible"]; hit = sum(1 for t, p in vis if p == "detected")
            db.add(ModelEvaluation(model_name="id_card_detector", model_version=idc.method, dataset_name=a.dataset_name,
                                   dataset_version=a.dataset_version, recall=hit / len(vis) if vis else None,
                                   sample_count=len(idrows), positive_count=len(vis), status="completed",
                                   notes="recall only on cards visible in ground truth"))
        db.commit()
    print("Saved to database.")
