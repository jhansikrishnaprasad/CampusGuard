"""Train a custom ID-card / lanyard detector with Ultralytics YOLO (needs requirements-ml.txt). NOT run in the build sandbox.

1. Collect frames of people (with and without cards) from authorised footage; label boxes with a tool such as CVAT/LabelImg:
   class 0 = id_card, class 1 = lanyard (optional). Include many negatives (no card, phone, badge-like objects, papers).
2. Arrange YOLO format:  <dataset>/images/{train,val,test}/*.jpg  and  <dataset>/labels/{train,val,test}/*.txt
   Split BY RECORDING SESSION (not by frame) - see scripts/dataset_prepare.py split.
3. Put an official Ultralytics base weight (e.g. yolov8n.pt) in models/ yourself (nothing is downloaded automatically).
  python scripts/train_idcard_yolo.py --dataset D:\\data\\idcards --base models/yolov8n.pt --epochs 80 --save-db
Writes models/idcard_yolo.pt and prints held-out (test split) precision/recall/mAP50. Then set Settings -> idcard.custom_model_path."""
import argparse, shutil, sys, textwrap
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config

ap = argparse.ArgumentParser()
ap.add_argument("--dataset", required=True); ap.add_argument("--base", required=True)
ap.add_argument("--epochs", type=int, default=80); ap.add_argument("--imgsz", type=int, default=960); ap.add_argument("--save-db", action="store_true")
ap.add_argument("--dataset-name", default="idcards"); ap.add_argument("--dataset-version", default="unversioned")
a = ap.parse_args()
try:
    from ultralytics import YOLO
except Exception as e:
    sys.exit(f"Ultralytics is not installed ({e}). Run: pip install -r requirements-ml.txt")
ds, base = Path(a.dataset).resolve(), Path(a.base)
if not base.is_file(): sys.exit(f"Base weights not found: {base} (download from the official Ultralytics release and place it there)")
for sub in ("images/train", "images/val", "images/test", "labels/train", "labels/val", "labels/test"):
    if not (ds / sub).is_dir() or not any((ds / sub).iterdir()): sys.exit(f"Dataset incomplete: {sub} is missing or empty")
yaml = ds / "idcard.yaml"
yaml.write_text(textwrap.dedent(f"""\
    path: {ds.as_posix()}
    train: images/train
    val: images/val
    test: images/test
    names: {{0: id_card, 1: lanyard}}
    """))
model = YOLO(str(base))
model.train(data=str(yaml), epochs=a.epochs, imgsz=a.imgsz, project=str(ds / "runs"), name="idcard", exist_ok=True)
best = ds / "runs" / "idcard" / "weights" / "best.pt"
m = YOLO(str(best)).val(data=str(yaml), split="test", imgsz=a.imgsz)
P, R, map50 = float(m.box.mp), float(m.box.mr), float(m.box.map50)
print(f"TEST split (never used for training/selection): precision={P:.3f} recall={R:.3f} mAP50={map50:.3f}")
config.MODELS_DIR.mkdir(exist_ok=True); shutil.copy2(best, config.MODELS_DIR / "idcard_yolo.pt")
print("Saved models/idcard_yolo.pt. Set Settings -> idcard.custom_model_path = models/idcard_yolo.pt")
if a.save_db:
    from app.database import SessionLocal, get_engine, init_db
    from app.models import ModelEvaluation
    get_engine(); init_db()
    with SessionLocal() as db:
        db.add(ModelEvaluation(model_name="id_card_detector", model_version="custom_yolo idcard_yolo.pt", dataset_name=a.dataset_name,
                               dataset_version=a.dataset_version, precision=P, recall=R, status="completed",
                               notes=f"box-level on test split, mAP50={map50:.3f}")); db.commit()
    print("Evaluation recorded.")
