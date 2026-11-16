"""Processing-run history: every analysis keeps its own results; queries default to the CURRENT run per video."""
from __future__ import annotations
from sqlalchemy import or_, select
from ..models import AnalysisJob


def current_run_filter(job_id_col):
    """Rows of the latest successful run of their video (legacy rows without a job count as current)."""
    return or_(job_id_col.is_(None), job_id_col.in_(select(AnalysisJob.id).where(AnalysisJob.is_current.is_(True))))
