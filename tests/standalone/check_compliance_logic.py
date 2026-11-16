import sys, types, itertools
import pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
for name in ("sqlalchemy", "sqlalchemy.orm"):
    m = types.ModuleType(name); sys.modules[name] = m
sys.modules["sqlalchemy"].func = None; sys.modules["sqlalchemy"].select = None; sys.modules["sqlalchemy.orm"].Session = object
models = types.ModuleType("app.models")
for n in ("AnalysisJob", "Event", "TrackedPerson", "Video"): setattr(models, n, type(n, (), {}))
sys.modules["app.models"] = models
from app.services import compliance_summary as cs
from app import constants as C

U, I = C, C
def people(spec):  # list of (n, uniform, id)
    return [(u, i) for n, u, i in spec for _ in range(n)]

# TEST 1: uniform mismatch only
c = cs.count_people(people([(2, C.UNI_SHIRT, C.ID_VISIBLE), (8, C.UNI_COMPLIANT, C.ID_VISIBLE)]))
assert (c["total_people"], c["uniform_non_compliant"], c["id_not_detected"], c["both_issues"], c["compliant_both"]) == (10, 2, 0, 0, 8), c
# TEST 2: id only
c = cs.count_people(people([(3, C.UNI_COMPLIANT, C.ID_NOT_DETECTED), (7, C.UNI_COMPLIANT, C.ID_VISIBLE)]))
assert (c["uniform_non_compliant"], c["id_not_detected"], c["both_issues"], c["id_only"]) == (0, 3, 0, 3), c
# TEST 3: both  (2 uniform, 3 id, 1 both)
c = cs.count_people(people([(1, C.UNI_BOTH, C.ID_NOT_DETECTED), (1, C.UNI_TROUSER, C.ID_VISIBLE), (2, C.UNI_COMPLIANT, C.ID_NOT_DETECTED), (6, C.UNI_COMPLIANT, C.ID_VISIBLE)]))
assert (c["uniform_non_compliant"], c["id_not_detected"], c["both_issues"], c["uniform_only"], c["id_only"]) == (2, 3, 1, 1, 2), c
# TEST 4: uncertain ID never becomes CARD_NOT_DETECTED
c = cs.count_people(people([(4, C.UNI_COMPLIANT, C.ID_UNCERTAIN), (6, C.UNI_COMPLIANT, C.ID_VISIBLE)]))
assert c["id_not_detected"] == 0 and c["uncertain"] == 4 and c["id_uncertain_people"] == 4 and c["compliant_both"] == 6, c
# TEST 5: empty
c = cs.count_people([]); assert c["total_people"] == 0 and all(c[k] == 0 for k in ("uniform_non_compliant","id_not_detected","both_issues","uncertain","not_assessed","compliant_both")), c
# exhaustive: every state combination lands in exactly one category and the maths always holds
for uo, ids in itertools.product(C.UNIFORM_STATES, C.ID_STATES):
    cat = cs.classify(uo, ids); assert cat in cs.CATEGORIES
    cs.count_people([(uo, ids)])
# explicit rules
assert cs.classify(C.UNI_UNCERTAIN, C.ID_UNCERTAIN) == "uncertain"
assert cs.classify(C.UNI_COMPLIANT, C.ID_NOT_ASSESSED) == "not_assessed"   # ID check not performed -> cannot claim compliant
assert cs.classify(C.UNI_NOT_ASSESSED, C.ID_VISIBLE) == "not_assessed"
assert cs.classify(C.UNI_SHIRT, C.ID_UNCERTAIN) == "uniform_only"
assert cs.classify("garbage", None) == "not_assessed"
# mixed-bag sum rule on a large random mix
import random; random.seed(1)
mix = [(random.choice(C.UNIFORM_STATES), random.choice(C.ID_STATES)) for _ in range(5000)]
c = cs.count_people(mix)
assert c["uniform_non_compliant"] == sum(u in C.UNIFORM_MISMATCH for u, _ in mix)
assert c["id_not_detected"] == sum(i == C.ID_NOT_DETECTED for _, i in mix)
assert c["both_issues"] == sum(u in C.UNIFORM_MISMATCH and i == C.ID_NOT_DETECTED for u, i in mix)
# alerts / warnings
ctx = {"job": {"partial": False}, "modules": [], "id_card": {"method": "heuristic", "reliable": False}, "uniform_method": "hsv-colour-baseline", "degraded": []}
c = cs.count_people(people([(2, C.UNI_SHIRT, C.ID_UNCERTAIN), (3, C.UNI_COMPLIANT, C.ID_UNCERTAIN)]))
codes = [w["code"] for w in cs.build_warnings(c, ctx)]
assert "id_unreliable" in codes and "id_uncertain" in codes, codes
assert any(cs.ID_UNRELIABLE_MESSAGE in w["message"] for w in cs.build_warnings(c, ctx))
assert cs.build_alert(c, ctx)["level"] == "attention"
n = cs.build_notification(c, ctx); assert n["lines"][0] == "2 people have possible uniform mismatches.", n
ctx_ok = dict(ctx, id_card={"method": "custom_yolo", "reliable": True})
c2 = cs.count_people(people([(5, C.UNI_COMPLIANT, C.ID_VISIBLE)])); a = cs.build_alert(c2, ctx_ok); assert a["level"] == "clear"
c3 = cs.count_people(people([(5, C.UNI_UNCERTAIN, C.ID_UNCERTAIN)])); a = cs.build_alert(c3, ctx); assert a["level"] == "caution" and "compliant" in a["message"].lower() and "not treat" in a["message"].lower()
assert cs.build_alert(cs.count_people([]), ctx)["level"] == "none"
# partial: activity modules missing -> info only; compliance module missing -> warn + caution
ctx_p = dict(ctx, modules=[{"module": "fight", "requested": True, "ran": False}, {"module": "id_card", "requested": True, "ran": False}])
codes = [w["code"] for w in cs.build_warnings(c2, ctx_p)]; assert "compliance_modules_missing" in codes
ctx_p2 = dict(ctx, modules=[{"module": "fight", "requested": True, "ran": False}])
assert "partial_other_modules" in [w["code"] for w in cs.build_warnings(c2, ctx_p2)]
assert cs.build_notification(c2, dict(ctx_ok, job={"partial": True}))["title"].endswith("(PARTIAL)")
assert cs._id_state({"id_card": {"method": "custom_yolo"}}, set(), [])["reliable"] is True
assert cs._id_state(None, {"heuristic"}, [])["reliable"] is False
assert cs._id_state({"id_card": {"method": "heuristic"}}, set(), [{"module": "id_card", "requested": False}])["method"] == "disabled"
print("ALL PURE-LOGIC CHECKS PASSED")
