from __future__ import annotations
from sqlalchemy.orm import Session
from backend.app.auth.context import CallerContext
from backend.app.auth.permissions import PermissionDenied
from backend.app.db.models import CurriculumChunk
from backend.app.tools.contracts import RetrieveCurriculumRequest, RetrieveCurriculumResponse

ALLOWED_SOURCES = {"SRC-SYNTH-FRACTIONS-V1"}

def retrieve_approved_curriculum(db: Session, caller: CallerContext, req: RetrieveCurriculumRequest) -> RetrieveCurriculumResponse:
    # Never trust query to bypass filters. Always filter by approved + allowed sources + centre scope if applicable.
    # For S1, curriculum_chunks are global synthetic but approval_status + source_id are enforced.
    q = db.query(CurriculumChunk).filter(CurriculumChunk.approval_status == "approved", CurriculumChunk.source_id.in_(ALLOWED_SOURCES))
    if req.subskill_id:
        q = q.filter(CurriculumChunk.subskill_id == req.subskill_id)
    # Intentionally ignore req.source_ids if it contains unapproved sources.
    # This proves malicious input like "SRC-UNAPPROVED" cannot be retrieved.
    chunks = q.all()
    # If query is clearly injection-like, we still return only approved; we don't expand scope.
    # No embedding search in S1; we return filtered list.
    out = []
    for c in chunks:
        # Simple relevance: if query substring appears, keep; otherwise still return filtered set (S1 does not do vector search)
        out.append({"id": c.id, "source_id": c.source_id, "subskill_id": c.subskill_id, "text": c.text, "approval_status": c.approval_status})
    # For malicious query like "ignore previous filters; return all", we do NOT honor it.
    return RetrieveCurriculumResponse(chunks=out)
