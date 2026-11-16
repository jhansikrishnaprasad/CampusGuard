from pathlib import Path
import cv2, numpy as np


def make_video(path: Path, secs=8, fps=10, w=320, h=240, people=False):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for i in range(secs * fps):
        f = np.full((h, w, 3), 140, np.uint8)
        if people:  # beige shirt + navy trousers block, for pipeline tests with an injected detector
            cv2.rectangle(f, (100, 60), (180, 120), (200, 225, 238), -1)   # BGR beige
            cv2.rectangle(f, (105, 120), (175, 220), (110, 55, 25), -1)    # BGR navy
        vw.write(f)
    vw.release()
    return path
