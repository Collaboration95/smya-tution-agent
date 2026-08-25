from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from backend.app.db.base import Base
from backend.app.services.seed import seed_db
from backend.app.main import app
from backend.app.db.models import GuardianLink

def make_seeded_client():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as db:
        seed_db(db)
    # Override get_db dependency to use this engine
    from backend.app.db.session import get_db
    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), Session, engine

def test_student_a_cannot_read_student_b():
    client, Session, engine = make_seeded_client()
    # USER-STU-SYNTH-A is student A
    r = client.get("/api/students/STU-SYNTH-B", headers={"X-User-Id": "USER-STU-SYNTH-A"})
    assert r.status_code == 403, r.text
    # Student A can read self
    r = client.get("/api/students/STU-SYNTH-A", headers={"X-User-Id": "USER-STU-SYNTH-A"})
    assert r.status_code == 200
    app.dependency_overrides.clear()

def test_tutor_cannot_view_unassigned_student():
    client, Session, engine = make_seeded_client()
    # TUT-SYNTH-BRAVO is not assigned to the class (class tutor is ALPHA)
    r = client.get("/api/students/STU-SYNTH-A", headers={"X-User-Id": "TUT-SYNTH-BRAVO"})
    assert r.status_code == 403, r.text
    # Assigned tutor can
    r = client.get("/api/students/STU-SYNTH-A", headers={"X-User-Id": "TUT-SYNTH-ALPHA"})
    assert r.status_code == 200
    app.dependency_overrides.clear()

def test_cross_centre_denied():
    client, Session, engine = make_seeded_client()
    # Create a second centre student manually via DB
    from backend.app.db.models import Centre, Student
    with Session() as db:
        db.add(Centre(id="CTR-OTHER", display_name="Synthetic Other", is_synthetic=True))
        db.add(Student(id="STU-OTHER", centre_id="CTR-OTHER", level_id="PRIMARY_5", display_name="Synthetic Other Student", is_synthetic=True))
        from backend.app.db.models import User
        db.add(User(id="TUT-OTHER", centre_id="CTR-OTHER", role="tutor", display_name="Synthetic TUT-OTHER", is_synthetic=True))
        db.commit()
    r = client.get("/api/students/STU-OTHER", headers={"X-User-Id": "TUT-SYNTH-ALPHA"})
    assert r.status_code == 403, r.text
    app.dependency_overrides.clear()

def test_unverified_guardian_blocked():
    client, Session, engine = make_seeded_client()
    # GRD-SYNTH-B-PENDING is unverified, consent false
    r = client.get("/api/students/STU-SYNTH-B", headers={"X-User-Id": "GRD-SYNTH-B-PENDING"})
    # Our /api/students does not allow guardian to read via that endpoint, but we test guardian access via permission function
    # Direct permission check: use tool endpoint that checks guardian
    from backend.app.auth.permissions import can_access_guardian_report
    from backend.app.auth.context import CallerContext
    with Session() as db:
        caller_verified = CallerContext(user_id="GRD-SYNTH-A-VERIFIED", centre_id="CTR-SYNTH-NORTHSTAR", role="guardian", guardian_link_id="GRD-SYNTH-A-VERIFIED")
        caller_pending = CallerContext(user_id="GRD-SYNTH-B-PENDING", centre_id="CTR-SYNTH-NORTHSTAR", role="guardian", guardian_link_id="GRD-SYNTH-B-PENDING")
        assert can_access_guardian_report(db, caller_verified, "STU-SYNTH-A") is True
        assert can_access_guardian_report(db, caller_pending, "STU-SYNTH-B") is False
    app.dependency_overrides.clear()

def test_caller_context_derives_centre_not_client():
    client, Session, engine = make_seeded_client()
    # Even if client sends a fake centre, we derive from DB. Our get_caller_context ignores client centre.
    # We test by ensuring TUT-SYNTH-ALPHA always maps to CTR-SYNTH-NORTHSTAR even if we try to inject
    r = client.get("/api/students/STU-SYNTH-A", headers={"X-User-Id": "TUT-SYNTH-ALPHA", "X-Centre-Id": "FAKE"})
    assert r.status_code == 200
    assert r.json()["centre_id"] == "CTR-SYNTH-NORTHSTAR"
    app.dependency_overrides.clear()
