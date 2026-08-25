from __future__ import annotations
from fastapi import Header, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.db.session import get_db
from backend.app.db.models import User, Student, GuardianLink
from backend.app.auth.context import CallerContext

def get_caller_context(x_user_id: str = Header(..., alias="X-User-Id"), db: Session = Depends(get_db)) -> CallerContext:
    # In S1 demo we trust X-User-Id header to identify seeded users — but centre/role are derived from DB, not header.
    # No client-provided centre_id or role is trusted.
    user = db.query(User).filter(User.id == x_user_id).first()
    if user:
        student_id = None
        guardian_link_id = None
        if user.role == "student":
            # Student users are USER-{student_id}
            # Extract student_id from display or via lookup; we store student_id as USER-STU-... but simpler: if id starts with USER-, strip
            if user.id.startswith("USER-"):
                sid = user.id[len("USER-"):]
                # Verify student exists
                s = db.query(Student).filter(Student.id == sid).first()
                if s:
                    student_id = sid
        return CallerContext(user_id=user.id, centre_id=user.centre_id, role=user.role, student_id=student_id, guardian_link_id=None)
    # Try guardian link as caller identity (guardian does not have a User row in some seeds)
    gl = db.query(GuardianLink).filter(GuardianLink.id == x_user_id).first()
    if gl:
        # Centre derived from linked student
        s = db.query(Student).filter(Student.id == gl.student_id).first()
        if not s:
            raise HTTPException(status_code=401, detail="unknown guardian student")
        return CallerContext(user_id=gl.id, centre_id=s.centre_id, role="guardian", student_id=None, guardian_link_id=gl.id)
    raise HTTPException(status_code=401, detail="unknown user")
