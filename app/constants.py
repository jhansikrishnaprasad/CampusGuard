"""Single source of truth for status vocabularies (used by models, pipeline, API, UI labels)."""
# Uniform (overall, per tracked person)
UNI_COMPLIANT = "COMPLIANT"
UNI_SHIRT = "POSSIBLE_SHIRT_MISMATCH"
UNI_TROUSER = "POSSIBLE_TROUSER_MISMATCH"
UNI_BOTH = "POSSIBLE_UNIFORM_MISMATCH"
UNI_UNCERTAIN = "UNCERTAIN"
UNI_NOT_ASSESSED = "NOT_ASSESSED"
UNIFORM_STATES = (UNI_COMPLIANT, UNI_SHIRT, UNI_TROUSER, UNI_BOTH, UNI_UNCERTAIN, UNI_NOT_ASSESSED)
UNIFORM_MISMATCH = (UNI_SHIRT, UNI_TROUSER, UNI_BOTH)
# Per clothing item
PART_STATES = ("ok", "inconsistent", "uncertain", "unable_to_verify")
# ID card
ID_VISIBLE = "CARD_VISIBLE"
ID_NOT_DETECTED = "CARD_NOT_DETECTED"   # NEVER proof that no card is worn
ID_UNCERTAIN = "UNCERTAIN"
ID_NOT_ASSESSED = "NOT_ASSESSED"
ID_STATES = (ID_VISIBLE, ID_NOT_DETECTED, ID_UNCERTAIN, ID_NOT_ASSESSED)
# Jobs / videos
JOB_STATES = ("queued", "running", "completed", "completed_partial", "failed", "cancelled")
VIDEO_STATES = ("uploaded", "queued", "processing", "completed", "completed_partial", "failed", "cancelled")
DONE_STATES = ("completed", "completed_partial")
# Review
REVIEW_STATES = ("pending_review", "confirmed", "dismissed", "inconclusive")
AUTOMATED_STATES = ("predicted", "uncertain")
# Model registry states
M_LOADED = "LOADED"
M_FILE_MISSING = "FILE_MISSING"
M_DEP_MISSING = "DEPENDENCY_MISSING"
M_LOAD_FAILED = "LOAD_FAILED"
M_NOT_CONFIGURED = "NOT_CONFIGURED"
M_DISABLED = "DISABLED"


def in_clause(col: str, values) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"

# Simple uniform result exposed alongside the detailed one (documented mapping)
UNIFORM_SIMPLE = {UNI_COMPLIANT: "COMPLIANT", UNI_SHIRT: "POSSIBLE_VIOLATION", UNI_TROUSER: "POSSIBLE_VIOLATION",
                  UNI_BOTH: "POSSIBLE_VIOLATION", UNI_UNCERTAIN: "UNCERTAIN", UNI_NOT_ASSESSED: "NOT_ASSESSED"}
# Per-module outcome of one processing run
R_NOT_ASSESSED = "NOT_ASSESSED"      # module did not run: says NOTHING about whether events occurred
R_NOT_DETECTED = "NOT_DETECTED"      # module ran and found nothing
R_UNCERTAIN = "UNCERTAIN"            # module ran, only low-confidence candidates
R_POSSIBLE = {"fight": "POSSIBLE_FIGHTING", "smoking": "POSSIBLE_SMOKING"}
