"""Measured evaluation of event recognition on LABELLED, HELD-OUT test videos.

labels.csv columns: video,category,start_s,end_s    (one row per TRUE event; videos without rows = negatives)
  python scripts/evaluate.py --videos <dir> --labels labels.csv --category possible_physical_fighting \\
         --dataset-name MyTest --dataset-version v1 [--save-db]
Reports 1-second-bin P/R/F1/FPR/confusion AND event-level (one-to-one IoU>=0.3) TP/FP/FN, plus seconds of
processing per footage-minute. Refuses to run without ground truth; the module under test must be LOADED."""
import argparse, json, sys, time
from pathlib import Path
import cv2, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config
from app.ml import metrics, pipeline
from app.ml.registry import registry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", required=True); ap.add_argument("--labels", required=True)
    ap.add_argument("--category", required=True, choices=[config.CATEGORY_FIGHT, config.CATEGORY_SMOKING])
    ap.add_argument("--dataset-name", default="unnamed"); ap.add_argument("--dataset-version", default="unversioned")
    ap.add_argument("--iou", type=float, default=0.3); ap.add_argument("--save-db", action="store_true")
    ap.add_argument("--workdir", default="data/eval_tmp")
    a = ap.parse_args()
    lab = pd.read_csv(a.labels)
    if lab.empty:
        sys.exit("labels.csv is empty - refusing to produce numbers without ground truth.")
    settings = config.DEFAULT_SETTINGS
    key = "fight" if a.category == config.CATEGORY_FIGHT else "smoking"
    det, idc, rec = registry.for_job(settings)
    if not rec[key].ready:
        sys.exit(f"Module '{key}' is not usable ({rec[key].status}): {rec[key].detail}\nNo evaluation was run.")
    lab = lab[lab.category == a.category]
    y_true, y_pred, pred_all, truth_all, tot_sec, tot_proc = [], [], [], [], 0.0, 0.0
    vids = sorted(p for p in Path(a.videos).iterdir() if p.suffix.lower() in config.ALLOWED_EXTENSIONS)
    if not vids:
        sys.exit("No videos found.")
    for vp in vids:
        cap = cv2.VideoCapture(str(vp)); dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 25); cap.release()
        t0 = time.time()
        res = pipeline.analyze(vp, Path(a.workdir) / vp.stem, f"eval/{vp.stem}", settings, detector=det, idc=idc,
                               recognizers={key: rec[key]})
        tot_proc += time.time() - t0; tot_sec += dur
        pred = [(e["start_s"], e["end_s"]) for e in res.events if e["category"] == a.category]
        truth = [(r.start_s, r.end_s) for r in lab[lab.video == vp.name].itertuples()]
        y_true += metrics.to_bins(dur, truth).tolist(); y_pred += metrics.to_bins(dur, pred).tolist()
        pred_all += [(vp.name, *p) for p in pred]; truth_all += [(vp.name, *t) for t in truth]
    # event matching is done per video (events of different videos can never match)
    tp = fp = fn = 0
    for v in {x[0] for x in pred_all + truth_all}:
        m = metrics.match_events([x[1:] for x in pred_all if x[0] == v], [x[1:] for x in truth_all if x[0] == v], a.iou)
        tp += m["tp"]; fp += m["fp"]; fn += m["fn"]
    ev = metrics.prf(tp, fp, fn); b = metrics.bin_metrics(y_true, y_pred)
    spm = tot_proc / (tot_sec / 60)
    thr = {k: settings["activity"][key][k] for k in ("threshold", "uncertain_low", "min_duration_s", "merge_gap_s", "min_hits")}
    print(f"Category: {a.category}\nModel: {rec[key].name} {rec[key].version}\nThresholds: {thr}")
    print(f"Videos: {len(vids)} | footage: {tot_sec/60:.1f} min | true events: {len(truth_all)} | predicted events: {len(pred_all)}")
    print(f"Per-second  P={b['precision']} R={b['recall']} F1={b['f1']} FPR={b['false_positive_rate']}\nConfusion [[TN FP],[FN TP]]: {b['confusion']}")
    print(f"Event-level (one-to-one IoU>={a.iou}): TP={tp} FP={fp} FN={fn} P={ev['precision']} R={ev['recall']} F1={ev['f1']}")
    print(f"Processing: {spm:.2f} s per footage-minute on this machine")
    if a.save_db:
        from app.database import SessionLocal, get_engine, init_db
        from app.models import ModelEvaluation
        get_engine(); init_db()
        with SessionLocal() as db:
            db.add(ModelEvaluation(model_name=a.category, model_version=f"{rec[key].name} {rec[key].version}",
                                   dataset_name=a.dataset_name, dataset_version=a.dataset_version, precision=ev["precision"],
                                   recall=ev["recall"], f1=ev["f1"], false_positive_rate=b["false_positive_rate"],
                                   seconds_per_minute_footage=spm, sample_count=len(vids), positive_count=len(truth_all),
                                   thresholds=json.dumps({**thr, "iou": a.iou}), status="completed",
                                   notes=f"event-level metrics; per-second confusion={b['confusion']}; events TP/FP/FN={tp}/{fp}/{fn}"))
            db.commit()
        print("Saved to database.")


if __name__ == "__main__":
    main()
