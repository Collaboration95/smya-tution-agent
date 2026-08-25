from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.db.session import get_db
from backend.app.auth.deps import get_caller_context
from backend.app.auth.context import CallerContext
from backend.app.auth.permissions import PermissionDenied
from backend.app.db.models import Student
from backend.app.tools.registry import get_student_snapshot
from backend.app.tools.contracts import GetStudentSnapshotRequest

router = APIRouter(prefix="/api", tags=["students"])

@router.get("/students/{student_id}")
def read_student(student_id: str, caller: CallerContext = Depends(get_caller_context), db: Session = Depends(get_db)):
    from backend.app.auth.permissions import can_read_student
    if not can_read_student(db, caller, student_id):
        raise HTTPException(status_code=403, detail="forbidden")
    s = db.query(Student).filter(Student.id == student_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="not found")
    return {"id": s.id, "centre_id": s.centre_id, "level_id": s.level_id, "display_name": s.display_name}

@router.post("/tools/get_student_snapshot")
def tool_get_student_snapshot(req: GetStudentSnapshotRequest, caller: CallerContext = Depends(get_caller_context), db: Session = Depends(get_db)):
    try:
        return get_student_snapshot(db, caller, req)
    except PermissionDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
