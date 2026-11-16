"""Fine-tune a video action model (fighting OR smoking) and export it in the format the app loads. NOT run in the build sandbox.

Needs requirements-ml.txt and a manifest CSV  path,label,group,split   (label: positive|negative; split train|val|test; group =
source recording; produce it with scripts/dataset_prepare.py so no recording is on both sides).
  python scripts/train_action_model.py --manifest splits.csv --root D:\\data\\rwf2000 --target fight --pretrained models\\r3d18_kinetics.pth
Pretrained weights: random initialisation on small data gives poor models. Obtain official Kinetics weights once yourself
(torchvision: r3d_18(weights=R3D_18_Weights.KINETICS400_V1)), save its state_dict to a .pth file and pass --pretrained.
Writes models/<target>_model.pt (TorchScript) + .json sidecar and prints CLIP-level test metrics. Event-level accuracy must
still be measured with scripts/evaluate.py on held-out continuous footage. Dataset licences (RWF-2000, UCF-Crime...) are your responsibility."""
import argparse, json, sys
from pathlib import Path
import cv2, numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    import torch, torch.nn as nn
    from torchvision.models.video import r3d_18
except Exception as e:
    sys.exit(f"PyTorch/torchvision missing ({e}). Run: pip install -r requirements-ml.txt")
from app import config
from app.ml import metrics

ap = argparse.ArgumentParser()
ap.add_argument("--manifest", required=True); ap.add_argument("--root", required=True)
ap.add_argument("--target", choices=["fight", "smoking"], required=True); ap.add_argument("--pretrained")
ap.add_argument("--epochs", type=int, default=8); ap.add_argument("--clip-len", type=int, default=16); ap.add_argument("--size", type=int, default=112)
ap.add_argument("--batch", type=int, default=4); ap.add_argument("--lr", type=float, default=1e-4); ap.add_argument("--version", default="v1")
a = ap.parse_args()
MEAN, STD = [0.43216, 0.394666, 0.37645], [0.22803, 0.22145, 0.216989]
df = pd.read_csv(a.manifest)
for need in ("train", "val", "test"):
    if (df.split == need).sum() < 10: sys.exit(f"Split '{need}' has fewer than 10 videos: not enough data to train/evaluate honestly.")
if set(df[df.split == "train"].group) & set(df[df.split == "test"].group): sys.exit("Recording appears in both train and test: fix the split.")


def clip(path):
    cap = cv2.VideoCapture(str(Path(a.root) / path)); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); fr = []
    for i in np.linspace(0, max(n - 1, 0), a.clip_len).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i)); ok, f = cap.read()
        fr.append(cv2.resize(f, (a.size, a.size)) if ok else (fr[-1] if fr else np.zeros((a.size, a.size, 3), np.uint8)))
    cap.release()
    x = (np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in fr]).astype(np.float32) / 255 - MEAN) / STD
    return torch.from_numpy(x).permute(3, 0, 1, 2)  # C,T,H,W


def batches(d, shuffle):
    idx = np.random.permutation(len(d)) if shuffle else np.arange(len(d))
    for i in range(0, len(d), a.batch):
        sub = d.iloc[idx[i:i + a.batch]]
        yield torch.stack([clip(p) for p in sub.path]), torch.tensor((sub.label == "positive").astype(int).values)


dev = "cuda" if torch.cuda.is_available() else "cpu"
net = r3d_18(weights=None)
if a.pretrained: net.load_state_dict(torch.load(a.pretrained, map_location="cpu"))
else: print("WARNING: no --pretrained weights: expect poor accuracy.")
net.fc = nn.Linear(net.fc.in_features, 2); net.to(dev)
opt = torch.optim.AdamW(net.parameters(), lr=a.lr); lossf = nn.CrossEntropyLoss()
train, val, test = (df[df.split == s].reset_index(drop=True) for s in ("train", "val", "test"))


def predict(d):
    net.eval(); ys, ps = [], []
    with torch.no_grad():
        for x, y in batches(d, False):
            ps += net(x.to(dev)).argmax(1).cpu().tolist(); ys += y.tolist()
    return ys, ps


best, best_state = -1, None
for ep in range(a.epochs):
    net.train()
    for x, y in batches(train, True):
        opt.zero_grad(); loss = lossf(net(x.to(dev)), y.to(dev)); loss.backward(); opt.step()
    ys, ps = predict(val); f1 = metrics.bin_metrics(ys, ps)["f1"] or 0
    print(f"epoch {ep + 1}: val F1={f1:.3f}")
    if f1 > best: best, best_state = f1, {k: v.cpu().clone() for k, v in net.state_dict().items()}
net.load_state_dict(best_state); ys, ps = predict(test); m = metrics.bin_metrics(ys, ps)
print(f"TEST clips (never used for training or model selection): P={m['precision']} R={m['recall']} F1={m['f1']} confusion={m['confusion']}")
net.eval().cpu()
ts = torch.jit.trace(net, torch.zeros(1, 3, a.clip_len, a.size, a.size))
config.MODELS_DIR.mkdir(exist_ok=True)
ts.save(str(config.MODELS_DIR / f"{a.target}_model.pt"))
(config.MODELS_DIR / f"{a.target}_model.json").write_text(json.dumps({
    "name": f"r3d18-{a.target}", "version": a.version, "classes": ["negative", "positive"], "positive_class": "positive",
    "clip_len": a.clip_len, "size": a.size, "layout": "BCTHW", "mean": MEAN, "std": STD,
    "test_clip_metrics": {"precision": m["precision"], "recall": m["recall"], "f1": m["f1"], "n_test": len(test)}}), encoding="utf-8")
print(f"Saved models/{a.target}_model.pt (+ .json). Now run scripts/evaluate.py on held-out continuous footage to record event-level metrics.")
