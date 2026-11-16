# Dataset and pretrained-model references

> **Verification status (November 2026).** Seven of the sources below were checked against their official or primary pages through a web search in this release pass
> (marked **Checked**). The rest are marked **Not checked** and must be confirmed by you. **Nothing was downloaded and nothing is redistributed with CampusGuard.**
> Licences and availability change: the terms on the official page always win, and datasets made from CCTV/YouTube/film footage contain people, so respect the access
> terms, your institution's ethics rules and privacy law. Where no verifiable public source exists the table says so instead of inventing a link.

Legend: **Verify** = confirm URL/licence yourself · **Request** = access needs registration, an e-mail request or a signed agreement.

## 1. Summary table

| # | Dataset | Used for in CampusGuard | Official page | Licence / terms found | Access | Verification |
|---|---|---|---|---|---|---|
| 1 | **COCO 2017** | Person detector pre-training/evaluation | https://cocodataset.org/#download (terms: https://cocodataset.org/#termsofuse) | Annotations: CC BY 4.0. **Images are not owned by COCO: use must follow the Flickr Terms of Use** | Open download | **Checked** |
| 2 | **CrowdHuman** | Occluded / crowded person detection evaluation | https://www.crowdhuman.org/ | Read the terms on the site | See site | Not checked |
| 3 | **MOTChallenge (MOT17 / MOT20)** | Evaluating the tracker | https://motchallenge.net/ | Read the terms on the site (believed non-commercial) | Open download | Not checked |
| 4 | **UCF101** | Pre-training; sports hard-negatives for fighting (boxing/punching-bag classes) and face-touching negatives | https://www.crcv.ucf.edu/data/UCF101.php | 101 action classes, 13,320 YouTube clips confirmed. **No licence text was found**; third-party summaries say "research use only". Treat as research-only until you read the page | Open download | **Checked** (existence, size); licence unconfirmed; class names (`Punch`, `BoxingPunchingBag`, ...) are from memory - check the class list |
| 5 | **HMDB51** | Smoking (`smoke`), fighting positives (`punch`, `kick someone`) and the **hard negatives** `hug`, `kiss`, `shake hands`, `fencing`, `sword fight`, `talk`, `eat`, `drink`, `smile`, `laugh` | https://serre-lab.clps.brown.edu/resource/hmdb-a-large-human-motion-database/ (also https://serre.lab.brown.edu/hmdb51.html) | **CC BY 4.0** stated on the official pages (6,849 clips, 51 classes). The clips come from films and web videos, so their underlying rights remain with the originators; the 2011 ICCV paper PDF is CC BY-NC-SA 3.0 - cite it | Open download | **Checked** |
| 6 | **Kinetics-400 / 600 / 700-2020** | Pre-training (`smoking`, boxing, slapping, wrestling, hugging, drinking, eating classes) and the origin of the Kinetics weights used by torchvision R3D-18 | Hosting + download scripts: https://github.com/cvdfoundation/kinetics-dataset | **Not confirmed in this pass** - read the licence on the Kinetics/DeepMind page. The videos are YouTube items; some disappear | Open scripts (very large) | **Checked** (hosting repo exists); licence unconfirmed |
| 7 | **RWF-2000** | **Fighting** (`Fight` / `NonFight`, 2,000 five-second surveillance clips) | https://github.com/mchengny/RWF2000-Video-Database-for-Violence-Detection | Per the official page: **may not be modified or redistributed and may not be used commercially without the SMIIP Lab's approval; must not be used in ways that harm privacy or mental health**; cite Cheng, Cai, Li, ICPR 2020/21 | **The page states that, for privacy reasons, the video files are currently NOT available on the website.** Contact the SMIIP Lab (Duke Kunshan University) to ask for access; a Hugging Face entry (SMIIP-lab/RWF-2000) only points back to the same page | **Checked** |
| 8 | **UCF-Crime** | Fighting / assault / abuse on **real surveillance** video; long normal videos for false-positive-rate measurement | https://www.crcv.ucf.edu/projects/real-world/ | 1,900 untrimmed surveillance videos, 13 anomaly classes including Fighting, Assault, Abuse (confirmed). **The page states no licence**; a third-party mirror labels it CC0 - do not rely on that. Cite Sultani, Chen, Shah, CVPR 2018. Videos were collected from YouTube/LiveLeak | Direct download links on the page | **Checked** (page, classes, download); licence unconfirmed |
| 9 | **Violent-Flows** (crowd violence) | Small extra fighting/crowd data | https://www.openu.ac.il/home/hassner/data/violentflows/ | Read the page | See page | Not checked |
| 10 | **Hockey Fights / Movies Fights** (Nievas et al., 2011) | Fighting vs. sports (ice hockey) | *No URL verified - search the dataset title and the CAIP 2011 paper* (the RWF-2000 paper describes both: Movies Fight has 200 clips) | Unknown | Unknown | Not checked |
| 11 | **Uniform classification** | Shirt/trouser colour-uniformity | **No suitable public dataset is known.** Collect your own, with consent, using `scripts/extract_person_crops.py` + `scripts/dataset_prepare.py` | Your own data: you set the licence and must obey privacy rules | n/a | n/a |
| 12 | **ID-card / lanyard detection** | Custom YOLO ID detector (needed for reliable "card not detected") | **No standard public dataset is known.** Community datasets exist on https://universe.roboflow.com/ (search "ID card", "lanyard"); **each has its own licence - check it individually** | Varies | Varies | Not checked |

## 2. Pretrained weights (never redistributed here)

| Weights | Source (verify) | Licence note |
|---|---|---|
| YOLOv8n (`yolov8n.pt`) - optional person detection + ByteTrack | https://github.com/ultralytics/ultralytics (weights are downloaded from the Ultralytics releases) | **Checked:** Ultralytics states two licences - **AGPL-3.0** or a paid **Enterprise License** for commercial products. See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md): CampusGuard never bundles it |
| R3D-18 Kinetics-400 (video classifier backbone) | https://pytorch.org/vision/stable/models.html | torchvision code is BSD-3-Clause; the weights were trained on Kinetics - check the dataset terms |
| OpenCV HOG people detector (default fallback) | Built into OpenCV | Apache-2.0 (OpenCV); no download needed |

## 3. How each dataset maps to a CampusGuard module

| Module | Recommended data | Hard negatives to include (required by the project brief) | Script that consumes it |
|---|---|---|---|
| Person detection / tracking | COCO (person), CrowdHuman, MOT17 for the tracker | Mannequins, posters, reflections | `scripts/evaluate.py` (tracker not scored automatically) |
| **Fighting** | UCF-Crime (Fighting/Assault/Abuse) + HMDB51 (`punch`, `kick someone`) + RWF-2000 **if the lab grants access** | hugging (HMDB51 `hug`), kissing/handshakes, fencing and sword fighting (HMDB51), sports (UCF101 boxing classes, hockey fights), playful pushing (record your own), ordinary conversation (HMDB51 `talk`), crowds walking. *HMDB51 `hit` and `push` are "hit/push something" (objects), not violence - do not use them as positives* | `scripts/dataset_prepare.py` -> `scripts/train_action_model.py --target fight` -> `scripts/evaluate.py` |
| **Smoking** | HMDB51 `smoke`, Kinetics `smoking`, **plus your own campus clips** | eating, drinking (`eat`, `drink`), phone use, touching the face, brushing teeth, vaping-like gestures | same, `--target smoking` |
| Uniform | Own labelled crops | Different lighting, backpacks/lanyards covering the torso, near-white shirts | `scripts/train_uniform_classifier.py`, `scripts/evaluate_uniform.py` |
| ID card | Own labelled photos (+ Roboflow community sets after licence check) | Lanyards without cards, phones, badges on bags | `scripts/train_idcard_yolo.py`, `scripts/evaluate_uniform.py` |

## 4. Rules for using any dataset with this project
1. Put downloaded data **outside** the repository (it is git-ignored: `datasets/`, `*.mp4`, `*.avi`, `*.mov`, `*.pt`).
2. Record `path,label,group,source,license` in the manifest; `scripts/dataset_prepare.py validate` refuses rows without a licence.
3. Split **by source video/camera/person** (`dataset_prepare.py split`) so near-duplicate clips never sit on both sides of train/test.
4. Report precision, recall, F1 and false-positive rate on the **held-out** split only (`scripts/evaluate.py`); do not quote training accuracy.
5. Do not publish trained weights unless the licences of every dataset *and* the base model allow it.
