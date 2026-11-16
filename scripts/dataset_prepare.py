"""Dataset manifest validation and leakage-safe splitting.

Manifest CSV columns:  path,label,group,source,license
  path   - video/image path relative to --root
  label  - class name
  group  - SOURCE VIDEO / camera / subject id. All rows with the same group stay in ONE split
           (prevents near-duplicate clips/frames of the same video leaking into train and test).
Commands:
  python scripts/dataset_prepare.py validate --manifest m.csv --root datasets/rwf2000
  python scripts/dataset_prepare.py split    --manifest m.csv --out splits.csv [--val 0.15 --test 0.15 --seed 42]
"""
import argparse, hashlib, random, sys
from collections import defaultdict
from pathlib import Path
import cv2, pandas as pd

REQ = ["path", "label", "group", "source", "license"]


def validate(a):
    df = pd.read_csv(a.manifest)
    miss = [c for c in REQ if c not in df.columns]
    if miss: sys.exit(f"Manifest missing columns: {miss}")
    bad = []
    for r in df.itertuples():
        p = Path(a.root) / r.path
        if not p.exists(): bad.append((r.path, "missing")); continue
        if p.suffix.lower() in (".mp4", ".avi", ".mov"):
            cap = cv2.VideoCapture(str(p)); ok, _ = cap.read(); cap.release()
            if not ok: bad.append((r.path, "unreadable/corrupt"))
    dup = df[df.duplicated("path", keep=False)]
    print(f"{len(df)} rows | classes: {df.label.value_counts().to_dict()} | licences: {df.license.unique().tolist()}")
    print(f"missing/corrupt: {len(bad)} | duplicate paths: {len(dup)}")
    for b in bad[:30]: print("  ", *b)
    Path(a.manifest).with_suffix(".version.txt").write_text(
        f"sha256={hashlib.sha256(Path(a.manifest).read_bytes()).hexdigest()}\nrows={len(df)}\n")
    sys.exit(1 if bad or len(dup) else 0)


def split(a):
    df = pd.read_csv(a.manifest)
    groups = defaultdict(list)
    for g in df.group.unique(): groups[g] = []
    keys = sorted(groups); random.Random(a.seed).shuffle(keys)
    n = len(keys); nt, nv = int(n * a.test), int(n * a.val)
    where = {g: ("test" if i < nt else "val" if i < nt + nv else "train") for i, g in enumerate(keys)}
    df["split"] = df.group.map(where)
    df.to_csv(a.out, index=False)
    print(df.groupby(["split", "label"]).size().unstack(fill_value=0))
    assert not (set(df[df.split == "train"].group) & set(df[df.split == "test"].group)), "leakage!"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    v = sp.add_parser("validate"); v.add_argument("--manifest", required=True); v.add_argument("--root", default=".")
    s = sp.add_parser("split"); s.add_argument("--manifest", required=True); s.add_argument("--out", required=True)
    s.add_argument("--val", type=float, default=0.15); s.add_argument("--test", type=float, default=0.15); s.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(); (validate if a.cmd == "validate" else split)(a)
