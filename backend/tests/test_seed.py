from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.db.base import Base
from backend.app.services.seed import seed_db
from backend.app.db.models import Centre, Student, Question, Attempt, MasteryState

def test_seed_loads_synthetic_fixtures_and_computes_mastery():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as db:
        seed_db(db)
        assert db.query(Centre).count() == 1
        assert db.query(Student).count() == 2
        assert db.query(Question).count() == 15
        assert db.query(Attempt).count() == 9
        # Mastery states should have been computed for each (student, subskill) with evidence
        # STU-A / FRC-ADD-SUB-UNLIKE -> requires_support, STU-B -> secure, STU-A/MULT -> insufficient
        m_a_add = db.query(MasteryState).filter_by(student_id="STU-SYNTH-A", subskill_id="FRC-ADD-SUB-UNLIKE").first()
        assert m_a_add is not None
        assert m_a_add.label == "requires_support" and m_a_add.eligible_attempts == 4 and m_a_add.accuracy == 0.25
        m_b_add = db.query(MasteryState).filter_by(student_id="STU-SYNTH-B", subskill_id="FRC-ADD-SUB-UNLIKE").first()
        assert m_b_add.label == "secure" and m_b_add.accuracy == 1.0
        m_a_mult = db.query(MasteryState).filter_by(student_id="STU-SYNTH-A", subskill_id="FRC-MULTIPLY-WHOLE").first()
        assert m_a_mult.label == "insufficient_evidence" and m_a_mult.eligible_attempts == 1

def test_seed_is_idempotent():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as db:
        seed_db(db)
        seed_db(db)
        assert db.query(Attempt).count() == 9
