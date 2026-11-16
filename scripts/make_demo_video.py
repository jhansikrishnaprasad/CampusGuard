"""Generate a SYNTHETIC test video (moving coloured rectangles) to exercise upload/processing plumbing.
It contains no real people: it proves nothing about model accuracy.   python scripts/make_demo_video.py"""
import sys
from pathlib import Path
import cv2, numpy as np
out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/demo/synthetic_demo.mp4")
out.parent.mkdir(parents=True, exist_ok=True)
W, H, FPS, SECS = 640, 480, 15, 20
vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
for i in range(FPS * SECS):
    f = np.full((H, W, 3), (150, 150, 150), np.uint8)
    for k, (shirt, trou) in enumerate([((190, 220, 235), (110, 60, 30)), ((40, 40, 200), (40, 40, 40))]):
        x = int(60 + k * 300 + 40 * np.sin(i / 20 + k))
        cv2.circle(f, (x + 40, 120), 22, (140, 170, 210), -1)
        cv2.rectangle(f, (x, 145), (x + 80, 270), shirt, -1)
        cv2.rectangle(f, (x + 5, 270), (x + 75, 420), trou, -1)
    cv2.putText(f, "SYNTHETIC TEST VIDEO", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    vw.write(f)
vw.release(); print("Wrote", out)
