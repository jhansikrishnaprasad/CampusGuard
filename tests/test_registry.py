"""Model registry honesty + sidecar validation + metrics. No torch/ultralytics needed (their absence is tested)."""
import json
from app import config
from app.ml import metrics
from app.ml.activity import ActivityRecognizer, validate_sidecar
from app.ml.registry import ModelRegistry

S = config.DEFAULT_SETTINGS
GOOD = {"classes": ["non_violent", "violent"], "positive_class": "violent", "clip_len": 16, "size": 112}


def entry(snap, key):
    return next(e for e in snap if e["key"] == key)


def test_default_registry_reports_missing_models_truthfully():
    snap = ModelRegistry().snapshot(S)
    assert entry(snap, "fight")["state"] in ("FILE_MISSING",) and entry(snap, "smoking")["state"] == "FILE_MISSING"
    assert entry(snap, "person_yolo")["state"] in ("DEPENDENCY_MISSING", "FILE_MISSING")
    assert entry(snap, "person_yolo")["active"] is False and entry(snap, "person_hog")["active"] is True
    assert entry(snap, "id_card")["state"] == "LOADED" and "heuristic" in entry(snap, "id_card")["detail"].lower()
    assert all(e["evaluation"]["state"] == "NOT_EVALUATED" for e in snap)          # nothing evaluated -> say so


def test_present_but_unusable_model_file_is_not_reported_as_loaded(tmp_path):
    f = tmp_path / "fight_model.pt"; f.write_bytes(b"this is not a torchscript file")
    cfg = {**S["activity"]["fight"], "model_path": str(f)}
    r = ActivityRecognizer("fight", config.CATEGORY_FIGHT, cfg)
    assert not r.ready and r.status in ("DEPENDENCY_MISSING", "NOT_CONFIGURED", "LOAD_FAILED")
    assert r.model is None


def test_disabled_and_unconfigured_states():
    assert ActivityRecognizer("f", "c", {**S["activity"]["fight"], "enabled": False}).status == "DISABLED"
    assert ActivityRecognizer("f", "c", {**S["activity"]["fight"], "model_path": ""}).status == "NOT_CONFIGURED"


def test_evaluation_state_only_when_metrics_recorded():
    ev = [{"model_name": config.CATEGORY_FIGHT, "status": "completed", "dataset_name": "T", "precision": .8, "recall": .7, "f1": .75}]
    snap = ModelRegistry().snapshot(S, ev)
    assert entry(snap, "fight")["evaluation"]["state"] == "EVALUATED" and entry(snap, "fight")["evaluation"]["f1"] == .75
    assert entry(snap, "smoking")["evaluation"]["state"] == "NOT_EVALUATED"
    failed = [{"model_name": config.CATEGORY_FIGHT, "status": "failed"}]
    assert entry(ModelRegistry().snapshot(S, failed), "fight")["evaluation"]["state"] == "NOT_EVALUATED"


def test_registry_reloads_only_when_config_changes():
    r = ModelRegistry(); r.ensure(S); d1 = r.detector
    r.ensure(S); assert r.detector is d1
    r.ensure(config.deep_merge(S, {"activity": {"fight": {"enabled": False}}})); assert r.detector is not d1
    det, idc, rec = r.for_job(S); assert det is r.detector and set(rec) == {"fight", "smoking"}


def test_sidecar_validation():
    assert validate_sidecar(GOOD) is None
    assert "positive_class" in validate_sidecar({**GOOD, "positive_class": "x"})
    assert "classes" in validate_sidecar({**GOOD, "classes": ["only_one"]})
    assert "clip_len" in validate_sidecar({**GOOD, "clip_len": 0})
    assert "layout" in validate_sidecar({**GOOD, "layout": "NHWC"})
    assert "std" in validate_sidecar({**GOOD, "std": [0, 1, 1]})
    assert validate_sidecar([1, 2]) is not None


def test_event_matching_is_one_to_one_so_duplicates_are_false_positives():
    m = metrics.match_events([(0, 10), (1, 9), (50, 60)], [(0, 10), (100, 110)], 0.3)
    assert (m["tp"], m["fp"], m["fn"]) == (1, 2, 1)
    assert metrics.match_events([], [], 0.3)["precision"] is None                 # undefined, not invented


def test_bin_metrics_and_confusion():
    t = metrics.to_bins(10, [(2, 6)]); p = metrics.to_bins(10, [(4, 8)])
    m = metrics.bin_metrics(t, p)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (2, 2, 2, 4) and m["confusion"] == [[4, 2], [2, 2]]
    assert abs(m["false_positive_rate"] - 2 / 6) < 1e-9


def test_crop_metrics_counts_abstentions_as_misses():
    rows = [("inconsistent", "inconsistent"), ("inconsistent", "uncertain"), ("ok", "ok"), ("ok", "inconsistent")]
    m = metrics.crop_metrics(rows)
    assert (m["tp"], m["fp"], m["fn"]) == (1, 1, 1) and m["abstention_rate"] == 0.25


def test_error_messages_never_leak_local_paths():
    from app.services.errors import sanitize_error
    msg = f"cannot open {config.DATA_DIR}\\videos\\abc.mp4 and {config.BASE_DIR}/models/x.pt\nTraceback..."
    out = sanitize_error(msg)
    assert str(config.DATA_DIR) not in out and str(config.BASE_DIR) not in out and "\n" not in out and "<app>" in out
    assert len(sanitize_error("x" * 5000)) <= 400


def test_registry_reports_trained_uniform_classifier_and_falls_back_when_broken(tmp_path):
    import json
    from app.ml.uniform_clf import FEATURE_NAMES
    good = {"type": "logistic", "part": "shirt", "version": "t9", "feature_names": FEATURE_NAMES, "mean": [0.0] * len(FEATURE_NAMES),
            "std": [1.0] * len(FEATURE_NAMES), "coef": [0.0] * len(FEATURE_NAMES), "intercept": 0.0}
    g = tmp_path / "shirt.json"; g.write_text(json.dumps(good))
    b = tmp_path / "trouser.json"; b.write_text("{not json")
    cfg = config.deep_merge(S, {"uniform": {"shirt_classifier_path": str(g), "trouser_classifier_path": str(b)}})
    r = ModelRegistry(); snap = r.snapshot(cfg)
    u = entry(snap, "uniform")
    assert set(r.uniform_clfs) == {"shirt"} and u["name"] == "linear-colour-classifier" and "t9" in u["version"]
    assert "LOAD_FAILED" in u["detail"] and "HSV baseline" in u["detail"]      # broken file reported, baseline used
    assert u["evaluation"]["state"] == "NOT_EVALUATED"                          # a freshly dropped-in model is unevaluated
