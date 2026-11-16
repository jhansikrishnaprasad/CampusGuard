# Video-level compliance summary (v1.3)

## Data source
Nothing new is stored. The summary is computed on request from `tracked_people` (one row per tracked person per run), `analysis_jobs`, `job_modules` and `events`.
Rows are selected by `video_id` **and** `job_id` of one run. Default run = the newest job of the video whose status is `completed` or `completed_partial`;
`?job_id=` selects another run of the same video (a job of a different video returns 404). Older runs are never added together.

## Counting rules (person level)
| Group | Rule |
|---|---|
| Uniform non-compliance (headline) | `uniform_overall` in POSSIBLE_SHIRT_MISMATCH / POSSIBLE_TROUSER_MISMATCH / POSSIBLE_UNIFORM_MISMATCH |
| ID card not detected (headline) | `id_status == CARD_NOT_DETECTED` only. `UNCERTAIN` is never counted here |
| Both issues | intersection of the two groups above (an overlapping subset, not extra people) |

Mutually exclusive groups, first match wins: **both** -> **uniform only** -> **ID only** -> **apparently compliant** (uniform COMPLIANT and ID CARD_VISIBLE)
-> **not assessed** (otherwise, and a check was NOT_ASSESSED, i.e. could not be performed) -> **uncertain** (everything else).
`uniform_non_compliant = uniform_only + both_issues`, `id_not_detected = id_only + both_issues`, and the six groups sum to `total_people` (asserted on every call).
A person whose ID check is disabled/not assessed can never be "apparently compliant".

## Endpoints (all require login)
* `GET /api/videos/{id}/compliance-summary[?job_id=]` - counts, `alert` (headline panel text), `notification` (toast text), `warnings[]` ({code, level, message}), `limitations[]`, `methods`, `modules`, `requires_manual_review`, `is_current`.
  Videos without a finished run return `available:false` and a message (not analysed / queued / running / failed / cancelled).
* `GET /api/videos/{id}/compliance-people[?job_id=&filter=]` filter: `all, uniform_issue, id_issue, both, uniform_only, id_only, compliant, uncertain, not_assessed`.
* `GET /api/compliance/overview` - latest completed analysis, pending reviews, partial analyses, recent alerts (dashboard).
* `GET /api/reports/compliance.csv[?video_id=&job_id=&include_history=]` - one row per tracked person; the PDF report has a "VIDEO-LEVEL UNIFORM AND ID-CARD COMPLIANCE SUMMARY" section.

## Notifications
`app.js` polls `/api/jobs` every 4 s. The first poll after load is a silent baseline. A toast fires only when a job is *seen moving* from queued/running to completed / completed_partial / failed / cancelled
(or a job created after page load is first seen finished). Notified job ids are kept in `sessionStorage`, so refresh, navigation and polling never repeat a toast. Reprocessing creates a new job and therefore a new notification.
The toast numbers come from the summary API. Browser notifications are optional and only requested when the user clicks "Enable desktop notifications". Results stay available after a refresh because they are re-derived from the database.

## Known limits (be honest in a demo)
* The default ID-card check is a geometric heuristic: it returns `CARD_VISIBLE` or `UNCERTAIN`, never `CARD_NOT_DETECTED`. Reliable "not detected" needs a custom YOLO detector trained on labelled ID-card images, and an evaluation on held-out data.
* The uniform check is a colour-range baseline with no recorded accuracy. Lighting, shadows, occlusion and low resolution cause errors.
* The HOG fallback person detector misses people; the YOLO detector is much better. "Total people" is the number of *tracks*, one person can produce several.
* Orphan rows (`job_id` NULL after a job was deleted) cannot be attributed to a run and are excluded.
* No accuracy figure is claimed anywhere.

## How to verify with a real CCTV video
1. Start the app, sign in, upload the video with "start analysis" ticked.
2. Open the video: the compliance section shows "Analysis is running", then a notification and the cards appear when the job finishes.
3. Check the numbers: Uniform & ID page lists the same people; the filter counts equal the card numbers; open an evidence frame and use "Jump to ... in the video".
4. Download `Reports -> PDF` and `Download compliance CSV (people)`; row counts equal the total.
5. Click *Reprocess*: a new notification appears and the cards show the new run; the old run stays reachable via `?job_id=`.
