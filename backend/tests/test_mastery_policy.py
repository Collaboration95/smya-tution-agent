import json
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.db.base import Base
from backend.app.db.models import Centre, User, Student, Question, Attempt, MasteryEvidence
from backend.app.services.mastery import compute_mastery, upsert_mastery_state, get_history

POLICY = json.loads((Path(__file__).parents[2] / "domain/mastery_policy/mastery_policy_v1.json").read_text())

def make_mem_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, future=True)

def test_policy_thresholds():
    # insufficient_evidence <3
    r = compute_mastery(0, 0, POLICY)
    assert r["label"] == "insufficient_evidence"
    r = compute_mastery(1, 1, POLICY)
    assert r["label"] == "insufficient_evidence"
    assert r["confidence"] == 0.35  # 0.2+0.15*1
    r = compute_mastery(4, 1, POLICY)  # 25% -> requires_support
    assert r["label"] == "requires_support"
    r = compute_mastery(4, 3, POLICY)  # 75% -> developing
    assert r["label"] == "developing"
    r = compute_mastery(4, 4, POLICY)  # 100% -> secure
    assert r["label"] == "secure"

def test_confidence_caps():
    r = compute_mastery(10, 10, POLICY)
    assert r["confidence"] == 0.9

def test_history_and_period_comparison():
    Session = make_mem_db()
    with Session() as db:
        db.add(Centre(id="CTR-1", display_name="Synthetic CTR-1", is_synthetic=True))
        db.add(User(id="TUT-1", centre_id="CTR-1", role="tutor", display_name="Synthetic TUT-1", is_synthetic=True))
        db.add(Student(id="STU-1", centre_id="CTR-1", level_id="PRIMARY_5", display_name="Synthetic STU-1", is_synthetic=True))
        db.add(Question(id="Q1", source_id="SRC-SYNTH-FRACTIONS-V1", subskill_id="FRC-ADD-SUB-UNLIKE", template_id="TPL-FRC-ADD-SUB-01", difficulty="foundation", prompt="p", expected_answer="3/4", answer_type="objective_exact", status="approved", selection_rank=10))
        db.add(Question(id="Q2", source_id="SRC-SYNTH-FRACTIONS-V1", subskill_id="FRC-ADD-SUB-UNLIKE", template_id="TPL-FRC-ADD-SUB-01", difficulty="foundation", prompt="p2", expected_answer="1/2", answer_type="objective_exact", status="approved", selection_rank=11))
        db.add(Question(id="Q3", source_id="SRC-SYNTH-FRACTIONS-V1", subskill_id="FRC-ADD-SUB-UNLIKE", template_id="TPL-FRC-ADD-SUB-01", difficulty="foundation", prompt="p3", expected_answer="5/8", answer_type="objective_exact", status="approved", selection_rank=12))
        db.commit()
        # 1 attempt -> insufficient
        db.add(Attempt(id="ATT1", student_id="STU-1", question_id="Q1", submitted_answer="3/4", grading_status="graded", is_correct=True))
        db.add(MasteryEvidence(id="EV1", attempt_id="ATT1", student_id="STU-1", subskill_id="FRC-ADD-SUB-UNLIKE", is_correct=True, policy_id="mastery_policy_v1", policy_version="1.0.0"))
        db.commit()
        s1 = upsert_mastery_state(db, "STU-1", "FRC-ADD-SUB-UNLIKE")
        db.commit()
        assert s1.label == "insufficient_evidence"
        assert s1.version == 1
        # add 2 more -> developing/secure etc
        db.add(Attempt(id="ATT2", student_id="STU-1", question_id="Q2", submitted_answer="1/2", grading_status="graded", is_correct=True))
        db.add(MasteryEvidence(id="EV2", attempt_id="ATT2", student_id="STU-1", subskill_id="FRC-ADD-SUB-UNLIKE", is_correct=True, policy_id="mastery_policy_v1", policy_version="1.0.0"))
        db.add(Attempt(id="ATT3", student_id="STU-1", question_id="Q3", submitted_answer="wrong", grading_status="graded", is_correct=False))
        db.add(MasteryEvidence(id="EV3", attempt_id="ATT3", student_id="STU-1", subskill_id="FRC-ADD-SUB-UNLIKE", is_correct=False, policy_id="mastery_policy_v1", policy_version="1.0.0"))
        db.commit()
        s2 = upsert_mastery_state(db, "STU-1", "FRC-ADD-SUB-UNLIKE")
        db.commit()
        assert s2.version == 2
        assert s2.eligible_attempts == 3
        hist = get_history(db, "STU-1", "FRC-ADD-SUB-UNLIKE")
        assert len(hist) == 2
        assert hist[0].version == 1 and hist[1].version == 2
        # Period comparison: hist[0] vs hist[1] should show change
        assert hist[0].label != hist[1].label or hist[0].confidence != hist[1].confidence

def test_attempt_immutability_and_append_only():
    Session = make_mem_db()
    with Session() as db:
        db.add(Centre(id="CTR-1", display_name="Synthetic CTR-1", is_synthetic=True))
        db.add(Student(id="STU-1", centre_id="CTR-1", level_id="PRIMARY_5", display_name="Synthetic STU-1", is_synthetic=True))
        db.add(Question(id="Q1", source_id="SRC-SYNTH-FRACTIONS-V1", subskill_id="FRC-EQUIVALENCE", template_id="TPL-FRC-EQUIV-01", difficulty="foundation", prompt="p", expected_answer="2/4", answer_type="objective_exact", status="approved", selection_rank=10))
        db.commit()
        att = Attempt(id="ATT1", student_id="STU-1", question_id="Q1", submitted_answer="2/4", grading_status="graded", is_correct=True)
        db.add(att)
        db.commit()
        att.submitted_answer = "wrong"
        with pytest.raises(ValueError, match="immutable"):
            db.commit()
        db.rollback()
        # Attempt should not be updatable via normal service — we verify that evidence is append-only by checking unique constraint on attempt_id
        evidence = MasteryEvidence(id="EV1", attempt_id="ATT1", student_id="STU-1", subskill_id="FRC-EQUIVALENCE", is_correct=True, policy_id="mastery_policy_v1", policy_version="1.0.0")
        db.add(evidence)
        db.commit()
        evidence.is_correct = False
        with pytest.raises(ValueError, match="append-only"):
            db.commit()
        db.rollback()
        from sqlalchemy.exc import IntegrityError
        try:
            db.add(MasteryEvidence(id="EV1-DUP", attempt_id="ATT1", student_id="STU-1", subskill_id="FRC-EQUIVALENCE", is_correct=True, policy_id="mastery_policy_v1", policy_version="1.0.0"))
            db.commit()
            assert False, "duplicate evidence should fail"
        except IntegrityError:
            db.rollback()

def test_tutor_override_takes_precedence():
    Session = make_mem_db()
    with Session() as db:
        db.add(Centre(id="CTR-1", display_name="Synthetic CTR-1", is_synthetic=True))
        db.add(User(id="TUT-1", centre_id="CTR-1", role="tutor", display_name="Synthetic TUT-1", is_synthetic=True))
        db.add(Student(id="STU-1", centre_id="CTR-1", level_id="PRIMARY_5", display_name="Synthetic STU-1", is_synthetic=True))
        db.add(Question(id="Q1", source_id="SRC-SYNTH-FRACTIONS-V1", subskill_id="FRC-ADD-SUB-UNLIKE", template_id="TPL-FRC-ADD-SUB-01", difficulty="foundation", prompt="p", expected_answer="3/4", answer_type="objective_exact", status="approved", selection_rank=10))
        db.add(Question(id="Q2", source_id="SRC-SYNTH-FRACTIONS-V1", subskill_id="FRC-ADD-SUB-UNLIKE", template_id="TPL-FRC-ADD-SUB-01", difficulty="foundation", prompt="p2", expected_answer="1/2", answer_type="objective_exact", status="approved", selection_rank=11))
        db.add(Question(id="Q3", source_id="SRC-SYNTH-FRACTIONS-V1", subskill_id="FRC-ADD-SUB-UNLIKE", template_id="TPL-FRC-ADD-SUB-01", difficulty="foundation", prompt="p3", expected_answer="5/8", answer_type="objective_exact", status="approved", selection_rank=12))
        db.add(Question(id="Q4", source_id="SRC-SYNTH-FRACTIONS-V1", subskill_id="FRC-ADD-SUB-UNLIKE", template_id="TPL-FRC-ADD-SUB-01", difficulty="core", prompt="p4", expected_answer="7/8", answer_type="objective_exact", status="approved", selection_rank=20))
        db.commit()
        for i, qid in enumerate(["Q1","Q2","Q3","Q4"], start=1):
            db.add(Attempt(id=f"ATT{i}", student_id="STU-1", question_id=qid, submitted_answer="wrong", grading_status="graded", is_correct=False))
            db.add(MasteryEvidence(id=f"EV{i}", attempt_id=f"ATT{i}", student_id="STU-1", subskill_id="FRC-ADD-SUB-UNLIKE", is_correct=False, policy_id="mastery_policy_v1", policy_version="1.0.0"))
        db.commit()
        s = upsert_mastery_state(db, "STU-1", "FRC-ADD-SUB-UNLIKE")
        db.commit()
        assert s.label == "requires_support"
        # Tutor override: create a new state with is_override True and corrected label
        from backend.app.db.models import MasteryState, TutorCorrection
        import uuid
        latest = db.query(MasteryState).filter_by(student_id="STU-1", subskill_id="FRC-ADD-SUB-UNLIKE").order_by(MasteryState.version.desc()).first()
        override = MasteryState(id=f"mst-override-{uuid.uuid4().hex[:6]}", centre_id="CTR-1", student_id="STU-1", subskill_id="FRC-ADD-SUB-UNLIKE", version=latest.version+1, eligible_attempts=latest.eligible_attempts, correct_attempts=latest.correct_attempts, accuracy=latest.accuracy, confidence=latest.confidence, label="developing", policy_id=latest.policy_id, policy_version=latest.policy_version, is_override=True)
        db.add(override)
        db.add(TutorCorrection(id=f"corr-{uuid.uuid4().hex[:6]}", centre_id="CTR-1", student_id="STU-1", subskill_id="FRC-ADD-SUB-UNLIKE", author_tutor_id="TUT-1", original_state_id=latest.id, corrected_label="developing", reason="re-evaluated", supersedes_version=latest.version))
        db.commit()
        from backend.app.services.mastery import get_effective_mastery
        eff = get_effective_mastery(db, "STU-1", "FRC-ADD-SUB-UNLIKE")
        assert eff.is_override and eff.label == "developing"
        # History retains original
        hist = get_history(db, "STU-1", "FRC-ADD-SUB-UNLIKE")
        assert len(hist) == 2
        assert hist[0].label == "requires_support" and hist[1].is_override
