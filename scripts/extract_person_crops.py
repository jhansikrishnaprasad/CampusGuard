"""Step 1 of building a uniform dataset: cut shirt / trouser region crops out of YOUR campus videos for labelling.

  python scripts/extract_person_crops.py --videos <folder with videos> --out crops
Writes crops/<video>_T<track>_<time>_<shirt|trouser>.jpg and crops/labels_todo.csv with columns
  image,part,session,label        (label is EMPTY: fill with  ok  or  inconsistent  by looking at the crop)
`session` = the source video, used later to split train/test by recording session (no leakage).
Crops contain clothing regions only (no faces). Only use footage you are authorised to use."""
import argparse, csv, sys
from pathlib import Path
import cv2
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config
from app.ml import uniform
from app.ml.registry import registry

ap = argparse.ArgumentParser()
ap.add_argument("--videos", required=True); ap.add_argument("--out", default="crops")
ap.add_argument("--every", type=float, default=2.0, help="seconds between sampled frames")
ap.add_argument("--max-per-track", type=int, default=4); ap.add_argument("--min-height", type=int, default=140)
a = ap.parse_args()
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
det, _, _ = registry.for_job(config.DEFAULT_SETTINGS)
print("Person detector:", det.describe()["model"], "| tracker:", det.describe()["tracker"])
rows = []
for vp in sorted(p for p in Path(a.videos).iterdir() if p.suffix.lower() in config.ALLOWED_EXTENSIONS):
    det.reset(); cap = cv2.VideoCapture(str(vp)); fps = cap.get(cv2.CAP_PROP_FPS) or 25; step = max(1, int(round(fps * a.every)))
    idx, taken = -1, {}
    while True:
        if not cap.grab(): break
        idx += 1
        if idx % step: continue
        ok, fr = cap.retrieve()
        if not ok: continue
        t = idx / fps
        for d in det.process(fr, t):
            x1, y1, x2, y2 = d.box
            if y2 - y1 < a.min_height or taken.get(d.track_id, 0) >= a.max_per_track: continue
            taken[d.track_id] = taken.get(d.track_id, 0) + 1
            for part, frac in (("shirt", uniform.SHIRT_BOX), ("trouser", uniform.TROUSER_BOX)):
                crop = uniform._region(fr, d.box, frac)
                if crop is None: continue
                name = f"{vp.stem}_T{d.track_id}_{int(t)}s_{part}.jpg"
                cv2.imwrite(str(out / name), crop); rows.append((name, part, vp.stem, ""))
    cap.release(); print(vp.name, "->", sum(taken.values()), "person samples")
with open(out / "labels_todo.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["image", "part", "session", "label"]); w.writerows(rows)
print(f"{len(rows)} crops written. Now label them (ok / inconsistent) in {out / 'labels_todo.csv'}")
