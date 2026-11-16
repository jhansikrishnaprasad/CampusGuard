import cv2, numpy as np
from app import config
from app.ml import pipeline, uniform
from app.ml.events import Pred, group_predictions
from app.ml.person import Det, SimpleTracker
from tests.helpers import make_video

U = config.DEFAULT_SETTINGS["uniform"]


def scene(shirt_bgr, trouser_bgr):
    f = np.full((600, 300, 3), 130, np.uint8)
    f[120:290, 40:260] = shirt_bgr
    f[340:540, 50:250] = trouser_bgr
    return f, (0, 40, 300, 580)


BEIGE, NAVY, RED, BLACK = (200, 225, 238), (110, 55, 25), (40, 40, 210), (8, 8, 8)


def test_uniform_compliant():
    f, b = scene(BEIGE, NAVY)
    r = uniform.assess_person(f, b, U)
    assert r["shirt"]["status"] == "ok" and r["trouser"]["status"] == "ok" and r["overall"] == "COMPLIANT"


def test_uniform_shirt_violation_is_independent_of_trousers():
    f, b = scene(RED, NAVY)
    r = uniform.assess_person(f, b, U)
    assert r["shirt"]["status"] == "inconsistent" and r["trouser"]["status"] == "ok"
    assert r["overall"] == "POSSIBLE_SHIRT_MISMATCH"


def test_dark_region_is_uncertain_not_violation():
    f, b = scene(BEIGE, BLACK)
    assert uniform.assess_person(f, b, U)["trouser"]["status"] == "uncertain"


def test_small_person_unable_to_verify():
    f, _ = scene(BEIGE, NAVY)
    r = uniform.assess_person(f, (0, 0, 40, 80), U)
    assert r["overall"] == "NOT_ASSESSED"


def test_cut_off_legs_not_judged():
    f, _ = scene(BEIGE, NAVY)
    r = uniform.assess_person(f, (0, 40, 300, 600), U)
    assert r["trouser"]["status"] == "unable_to_verify"


def test_aggregate_needs_enough_samples():
    f, b = scene(RED, NAVY)
    one = [uniform.assess_person(f, b, U)]
    assert uniform.aggregate(one, U)["shirt"] == "uncertain"
    assert uniform.aggregate(one * 4, U)["shirt"] == "inconsistent"


def test_event_grouping_merges_and_filters():
    preds = [Pred(0, 4, "a", .9), Pred(2, 6, "a", .8), Pred(4, 8, "a", .85),   # one cluster
             Pred(60, 64, "a", .95),                                           # lone window -> dropped (min_hits=2)
             Pred(20, 24, "a", .6), Pred(22, 26, "a", .55),                    # uncertain cluster
             Pred(0, 4, "b", .9), Pred(2, 6, "b", .9)]                         # other category stays separate
    out = group_predictions(preds, .7, .5, 2.0, 3.0, 2)
    assert [(i.category, i.status, i.start, i.end) for i in out] == [
        ("a", "predicted", 0, 8), ("b", "predicted", 0, 6), ("a", "uncertain", 20, 26)]
    assert len([i for i in out if i.category == "a" and i.start == 60]) == 0


def test_tracker_keeps_id_and_splits_far_objects():
    t = SimpleTracker(0.3, 2.0, 1)
    a = t.update([(0, 0, 100, 200, .9)], 0)[0].track_id
    b = t.update([(5, 0, 105, 200, .9), (400, 0, 500, 200, .9)], 0.5)
    ids = sorted(d.track_id for d in b)
    assert a in ids and len(set(ids)) == 2


class FakeDetector:
    note = ""; backend = "fake"; tracker_name = "bytetrack"
    def describe(self): return {"backend": "fake", "model": "fake-detector", "tracker": "fake-tracker"}
    def process(self, frame, t): return [Det(1, (60, 30, 260, 235), .9)]


class FakeFight:
    ready = True; name = "fake-fight"; version = "t"; category = config.CATEGORY_FIGHT; clip_len = 4; status = "LOADED"; detail = ""
    def describe(self): return {"status": "ready"}
    def prepare(self, f): return cv2.resize(f, (16, 16))
    def predict(self, frames): return self.p
    p = 0.0


class Off:
    ready = False; status = "NOT_CONFIGURED"; detail = "none"; category = "x"
    def describe(self): return {"status": self.status}


def test_pipeline_end_to_end_with_injected_models(tmp_path):
    vid = make_video(tmp_path / "v.mp4", secs=12, fps=10, people=True)
    fight = FakeFight()
    calls = {"n": 0}
    def predict(frames):
        calls["n"] += 1
        return 0.95 if calls["n"] >= 2 else 0.1
    fight.predict = predict
    s = config.deep_merge(config.DEFAULT_SETTINGS, {"uniform": {"min_person_height_px": 50},
                                                    "activity": {"fight": {"stride_s": 1.0, "window_s": 2.0, "min_duration_s": 1.0}}})
    res = pipeline.analyze(vid, tmp_path / "out", "rel", s, detector=FakeDetector(),
                           recognizers={"fight": fight, "smoking": Off()})
    assert res.frames_decoded > 0 and res.people and res.people[0]["track_ref"] == "T1"
    assert res.people[0]["uniform_overall"] in ("COMPLIANT", "UNCERTAIN")  # never 'violation' for a compliant colour scene
    fights = [e for e in res.events if e["category"] == config.CATEGORY_FIGHT]
    assert fights and fights[0]["confidence"] == 0.95 and any(x["kind"] == "clip" for x in fights[0]["evidence"])
    assert any("smoking" in w for w in res.warnings)  # unavailable model reported, not faked
    assert res.partial is True and res.coverage["fight"]["ran"] and not res.coverage["smoking"]["ran"]
    assert (tmp_path / "out" / "people" / "t1.jpg").exists()


def test_no_models_no_events(tmp_path):
    vid = make_video(tmp_path / "v.mp4", secs=6)
    res = pipeline.analyze(vid, tmp_path / "o", "rel", config.DEFAULT_SETTINGS, detector=FakeDetector(),
                           recognizers={"fight": Off(), "smoking": Off()})
    assert [e for e in res.events if e["category"] != config.CATEGORY_UNIFORM] == []


def test_cancel(tmp_path):
    import pytest
    vid = make_video(tmp_path / "v.mp4", secs=20)
    with pytest.raises(pipeline.Cancelled):
        pipeline.analyze(vid, tmp_path / "o", "r", config.DEFAULT_SETTINGS, progress_cb=lambda p: None,
                         cancel_cb=lambda: True, detector=FakeDetector(), recognizers={"fight": Off(), "smoking": Off()})


def test_corrupt_video_fails_cleanly(tmp_path):
    import pytest
    bad = tmp_path / "bad.mp4"; bad.write_bytes(b"not a video" * 100)
    with pytest.raises(RuntimeError):
        pipeline.analyze(bad, tmp_path / "o", "r", config.DEFAULT_SETTINGS, detector=FakeDetector(),
                         recognizers={"fight": Off(), "smoking": Off()})


def test_shadowed_beige_shirt_still_ok_but_gray_or_black_is_not():
    dim_beige = tuple(int(c * 0.55) for c in BEIGE)
    f, b = scene(dim_beige, NAVY)
    assert uniform.assess_person(f, b, U)["shirt"]["status"] == "ok"
    f, b = scene((120, 120, 120), NAVY)                      # mid-grey shirt must not be rescued into "beige"
    assert uniform.assess_person(f, b, U)["shirt"]["status"] != "ok"
    f, b = scene((15, 15, 15), NAVY)                         # black shirt: too dark -> uncertain, never beige
    assert uniform.assess_person(f, b, U)["shirt"]["status"] in ("uncertain", "inconsistent")


def test_both_items_wrong_gives_uniform_mismatch_and_hidden_item_is_not_a_mismatch():
    f, b = scene(RED, (40, 200, 40))
    assert uniform.assess_person(f, b, U)["overall"] == "POSSIBLE_UNIFORM_MISMATCH"
    assert uniform.overall("ok", "unable_to_verify") == "UNCERTAIN"
    assert uniform.overall("unable_to_verify", "unable_to_verify") == "NOT_ASSESSED"
    assert uniform.overall("ok", "inconsistent") == "POSSIBLE_TROUSER_MISMATCH"


def test_id_aggregate_never_claims_absence_without_enough_evidence():
    from app.ml import idcard
    assert idcard.aggregate(["uncertain"] * 10, 3) == "UNCERTAIN"
    assert idcard.aggregate(["not_detected", "not_detected"], 3) == "UNCERTAIN"
    assert idcard.aggregate(["not_detected"] * 4, 3) == "CARD_NOT_DETECTED"
    assert idcard.aggregate(["not_detected"] * 9 + ["detected"], 3) == "CARD_VISIBLE"
    assert idcard.aggregate([], 3) == "NOT_ASSESSED" and idcard.aggregate(["not_configured"], 3) == "NOT_ASSESSED"


def test_tracker_keeps_id_for_fast_movers_and_short_gaps():
    t = SimpleTracker(0.3, 2.0, 1)
    ids = []
    for k in range(6):                      # moves 40% of its own width every 0.5 s (IoU alone would lose it)
        x = 100 + k * 40
        ids.append(t.update([(x, 50, x + 100, 350, .9)], k * 0.5)[0].track_id)
    assert len(set(ids)) == 1
    # 1.5 s without any detection (occlusion), reappears where the motion predicts
    x_next = 100 + 6 * 40 + 3 * 40
    out = t.update([(x_next, 50, x_next + 100, 350, .9)], 3 * 0.5 + 5 * 0.5 + 1.5)
    assert out and out[0].track_id == ids[0]


def test_tracker_does_not_merge_two_people_or_accept_size_jumps():
    t = SimpleTracker(0.3, 2.0, 1)
    a = t.update([(0, 0, 100, 300, .9), (500, 0, 600, 300, .9)], 0)
    b = t.update([(10, 0, 110, 300, .9), (510, 0, 610, 300, .9)], 0.5)
    assert sorted(d.track_id for d in a) == sorted(d.track_id for d in b) and len({d.track_id for d in b}) == 2
    c = t.update([(15, 0, 55, 90, .9)], 1.0)             # far smaller box nearby: must not inherit an old id
    assert c and c[0].track_id not in {d.track_id for d in b}


def test_pipeline_records_observations_scores_and_module_results(tmp_path):
    vid = make_video(tmp_path / "v.mp4", secs=12, fps=10, people=True)
    fight = FakeFight(); calls = {"n": 0}
    def predict(frames):
        calls["n"] += 1
        return 0.95 if calls["n"] >= 2 else 0.1
    fight.predict = predict
    s = config.deep_merge(config.DEFAULT_SETTINGS, {"uniform": {"min_person_height_px": 50},
                                                    "activity": {"fight": {"stride_s": 1.0, "window_s": 2.0, "min_duration_s": 1.0}}})
    res = pipeline.analyze(vid, tmp_path / "o", "rel", s, detector=FakeDetector(), recognizers={"fight": fight, "smoking": Off()})
    p = res.people[0]
    assert p["observations"] and all(len(o[1]) == 4 for o in p["observations"])
    assert p["uniform_method"] == "hsv-colour-baseline" and p["uniform_version"] == "hsv-v2" and p["uniform_score"] is not None
    assert p["id_method"] and p["id_association"] == "inside-person-torso-box"
    assert res.module_results["fight"] == "POSSIBLE_FIGHTING"
    assert res.module_results["smoking"] == "NOT_ASSESSED"          # did not run: never reported as "nothing detected"
    ev = [e for e in res.events if e["category"] == config.CATEGORY_FIGHT][0]
    assert ev["context_tracks"] == ["T1"] and "NOT attributed" in ev["summary"] and ev["track_ref"] is None


def test_uniform_classifier_roundtrip_and_validation(tmp_path):
    import json
    from app.ml.uniform_clf import FEATURE_NAMES, LinearRegionClassifier, extract_features, fit_logistic
    rng = np.random.default_rng(0)
    def img(ok):
        base = np.array([200, 225, 238]) if ok else np.array([40, 40, 210])
        return np.tile(np.clip(base + rng.integers(-10, 10, 3), 0, 255).astype(np.uint8), (40, 40, 1))
    X = np.stack([extract_features(img(i % 2 == 0)) for i in range(40)]); y = np.array([1 if i % 2 == 0 else 0 for i in range(40)])
    model = fit_logistic(X, y, "shirt", "t1")
    f = tmp_path / "m.json"; f.write_text(json.dumps(model))
    clf = LinearRegionClassifier.load(f)
    assert clf.prob_ok(img(True)) > 0.8 and clf.prob_ok(img(False)) < 0.2
    assert LinearRegionClassifier.validate({**model, "coef": [1.0]}) is not None
    assert LinearRegionClassifier.validate({**model, "feature_names": ["x"] * len(FEATURE_NAMES)}) is not None
    # classifier used by assess_person with the same visibility gates; hidden legs still unable_to_verify
    frame, box = scene(BEIGE, NAVY)
    r = uniform.assess_person(frame, box, U, {"shirt": clf})
    assert r["shirt"]["status"] == "ok" and "classifier" in r["shirt"]["reason"]
    assert uniform.assess_person(frame, (0, 40, 300, 600), U, {"shirt": clf})["trouser"]["status"] == "unable_to_verify"


def test_simple_uniform_mapping_is_documented_and_total():
    from app import constants as C
    assert set(C.UNIFORM_SIMPLE) == set(C.UNIFORM_STATES)
    assert {C.UNIFORM_SIMPLE[x] for x in C.UNIFORM_MISMATCH} == {"POSSIBLE_VIOLATION"}
