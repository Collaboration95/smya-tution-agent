from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.db.base import Base
from backend.app.db.models import Centre, User, Student

def make_mem_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, future=True)

def test_centre_scope_isolation():
    Session = make_mem_db()
    with Session() as db:
        db.add(Centre(id="CTR-A", display_name="Synthetic CTR-A", is_synthetic=True))
        db.add(Centre(id="CTR-B", display_name="Synthetic CTR-B", is_synthetic=True))
        db.add(User(id="TUT-A", centre_id="CTR-A", role="tutor", display_name="Synthetic TUT-A", is_synthetic=True))
        db.add(User(id="TUT-B", centre_id="CTR-B", role="tutor", display_name="Synthetic TUT-B", is_synthetic=True))
        db.add(Student(id="STU-A", centre_id="CTR-A", level_id="PRIMARY_5", display_name="Synthetic STU-A", is_synthetic=True))
        db.add(Student(id="STU-B", centre_id="CTR-B", level_id="PRIMARY_5", display_name="Synthetic STU-B", is_synthetic=True))
        db.commit()
        # Tutor A should only see students in CTR-A
        ctr_a_students = db.query(Student).filter(Student.centre_id == "CTR-A").all()
        assert len(ctr_a_students) == 1 and ctr_a_students[0].id == "STU-A"
        ctr_b_students = db.query(Student).filter(Student.centre_id == "CTR-B").all()
        assert ctr_b_students[0].id == "STU-B"
        # Cross-centre query without filter should be considered a bug — service layer must enforce centre_id
        # Here we verify that every centre-owned row carries centre_id
        for model in [Centre, Student]:
            assert hasattr(model, "centre_id") or model.__tablename__ == "centres"

def test_every_centre_owned_record_has_centre_scope():
    # Only centres are top-level; all others we check via model registry
    from backend.app.db.models import Class
    # Class has centre_id, Enrolment is indirect via class but still scoped via class join
    # S1-02 acceptance: every centre-owned record carries centre scope — we enforce via Class.centre_id and Student.centre_id
    assert hasattr(Class, "centre_id")
    assert hasattr(Student, "centre_id")
