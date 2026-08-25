from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from backend.app.auth.context import CallerContext
from backend.app.auth.permissions import PermissionDenied
from backend.app.db.models import AuditEvent, CurriculumChunk
from backend.app.tools.contracts import RetrieveCurriculumRequest, RetrieveCurriculumResponse

ALLOWED_SOURCES = {"SRC-SYNTH-FRACTIONS-V1"}

def retrieve_approved_curriculum(db: Session, caller: CallerContext, req: RetrieveCurriculumRequest) -> RetrieveCurriculumResponse:
    if caller.role not in ("admin", "tutor", "worker"):
        raise PermissionDenied("curriculum retrieval is not allowed for this role")
    requested_sources = set(req.source_ids or ALLOWED_SOURCES)
    approved_sources = requested_sources.intersection(ALLOWED_SOURCES)
    q = db.query(CurriculumChunk).filter(
        CurriculumChunk.approval_status == "approved",
        CurriculumChunk.source_id.in_(approved_sources or {"__none__"}),
        (CurriculumChunk.centre_id == caller.centre_id) | (CurriculumChunk.centre_id.is_(None)),
    )
    if req.subskill_id:
        q = q.filter(CurriculumChunk.subskill_id == req.subskill_id)
    chunks = q.order_by(CurriculumChunk.id.asc()).limit(20).all()
    out = [
        {
            "id": chunk.id,
            "source_id": chunk.source_id,
            "subskill_id": chunk.subskill_id,
            "text": chunk.text,
            "approval_status": chunk.approval_status,
        }
        for chunk in chunks
    ]
    db.add(
        AuditEvent(
            id=f"aud-{uuid.uuid4().hex[:8]}",
            centre_id=caller.centre_id,
            actor_id=caller.user_id,
            actor_role=caller.role,
            event="tool.retrieve_approved_curriculum",
            entity_type="curriculum",
            entity_id=req.subskill_id or "approved-curriculum",
            after_json=json.dumps({"source_ids": sorted(approved_sources), "count": len(out)}),
            created_at=datetime.now(timezone.utc),
        )
    )
    db.flush()
    return RetrieveCurriculumResponse(chunks=out)
