"""Step 2: train + honestly evaluate the shirt / trouser colour classifier on LABELLED crops.

  python scripts/train_uniform_classifier.py --root crops --csv crops/labels.csv --out models --version v1 \\
         [--save-db --dataset-name CollegeCrops --dataset-version v1]
labels.csv: image,part,session,label   (part shirt|trouser, label ok|inconsistent, session = source video / recording)
* Train/validation/test split is by SESSION (GroupShuffleSplit): crops of one video never appear on both sides.
* Reports precision/recall/F1/confusion on the held-out sessions for the baseline AND the trained model.
* Writes models/uniform_shirt_clf.json and models/uniform_trouser_clf.json (safe JSON, no pickle). The app only
  uses them after you restart; they appear as NOT_EVALUATED until --save-db records the held-out result.
Refuses to run with too little data (needs >= 5 sessions and >= 30 crops per part, both classes present)."""
import argparse, json, sys
from pathlib import Path
import cv2, numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sklearn.model_selection import GroupShuffleSplit
from app import config
from app.ml import metrics, uniform
from app.ml.uniform_clf import LinearRegionClassifier, extract_features, fit_logistic

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True); ap.add_argument("--csv", required=True); ap.add_argument("--out", default="models")
ap.add_argument("--version", default="v1"); ap.add_argument("--test-size", type=float, default=0.3); ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--save-db", action="store_true"); ap.add_argument("--dataset-name", default="unnamed"); ap.add_argument("--dataset-version", default="unversioned")
a = ap.parse_args()
df = pd.read_csv(a.csv); df = df[df.label.isin(["ok", "inconsistent"])]
U = config.DEFAULT_SETTINGS["uniform"]
report = {}
for part in ("shirt", "trouser"):
    d = df[df.part == part].reset_index(drop=True)
    if len(d) < 30 or d.session.nunique() < 5 or d.label.nunique() < 2:
        print(f"[{part}] NOT ENOUGH DATA ({len(d)} crops, {d.session.nunique()} sessions, classes={sorted(d.label.unique())}); skipping. Nothing was trained.")
        continue
    imgs = [cv2.imread(str(Path(a.root) / n)) for n in d.image]
    if any(i is None for i in imgs): sys.exit("Unreadable crop(s) in CSV")
    X = np.stack([extract_features(i) for i in imgs]); y = (d.label == "ok").astype(int).values
    tr, te = next(GroupShuffleSplit(1, test_size=a.test_size, random_state=a.seed).split(X, y, groups=d.session))
    assert not set(d.session[tr]) & set(d.session[te]), "session leakage"
    if len(set(y[tr])) < 2 or len(set(y[te])) < 2:
        print(f"[{part}] split lacks both classes on one side; add more sessions."); continue
    model = fit_logistic(X[tr], y[tr], part, a.version, {"trained_sessions": int(d.session[tr].nunique()), "train_crops": int(len(tr))})
    clf = LinearRegionClassifier(model)
    rng = U["beige"] if part == "shirt" else U["navy"]
    rows_clf, rows_base = [], []
    for i in te:
        truth = d.label[i]; img = imgs[i]
        p = clf.prob_ok(img); rows_clf.append((truth, "ok" if p >= U["clf_ok"] else "inconsistent" if p <= U["clf_bad"] else "uncertain"))
        rows_base.append((truth, uniform.judge_region(img, rng, U, part == "shirt")["status"]))
    m_c, m_b = metrics.crop_metrics(rows_clf), metrics.crop_metrics(rows_base)
    print(f"[{part}] held-out: {len(te)} crops from {d.session[te].nunique()} unseen sessions")
    print(f"   baseline  P={m_b['precision']} R={m_b['recall']} F1={m_b['f1']} abstain={m_b['abstention_rate']}")
    print(f"   trained   P={m_c['precision']} R={m_c['recall']} F1={m_c['f1']} abstain={m_c['abstention_rate']} confusion={m_c['confusion']}")
    model["heldout_metrics"] = {"n": len(te), "precision": m_c["precision"], "recall": m_c["recall"], "f1": m_c["f1"]}
    Path(a.out).mkdir(exist_ok=True); (Path(a.out) / f"uniform_{part}_clf.json").write_text(json.dumps(model), encoding="utf-8")
    report[part] = (m_c, len(te))
if a.save_db and report:
    from app.database import SessionLocal, get_engine, init_db
    from app.models import ModelEvaluation
    get_engine(); init_db()
    with SessionLocal() as db:
        n = sum(v[1] for v in report.values())
        P = [v[0]["precision"] for v in report.values() if v[0]["precision"] is not None]; R = [v[0]["recall"] for v in report.values() if v[0]["recall"] is not None]
        f1s = [v[0]["f1"] for v in report.values() if v[0]["f1"] is not None]
        db.add(ModelEvaluation(model_name="uniform_classifier", model_version=a.version, dataset_name=a.dataset_name, dataset_version=a.dataset_version,
                               precision=float(np.mean(P)) if P else None, recall=float(np.mean(R)) if R else None, f1=float(np.mean(f1s)) if f1s else None,
                               sample_count=n, thresholds=json.dumps({"clf_ok": U["clf_ok"], "clf_bad": U["clf_bad"]}), status="completed",
                               notes="held-out sessions; macro-average of shirt and trouser classifiers"))
        db.commit(); print("Evaluation recorded in database.")
