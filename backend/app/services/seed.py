from __future__ import annotations
import json
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy.orm import Session
from backend.app.db.models import Centre, User, Student, Class, Enrolment, GuardianLink, CurriculumChunk, Question, Attempt, MasteryEvidence
from backend.app.services.mastery import normalise_answer, upsert_mastery_state, load_policy

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "fixtures" / "fractions_contract_v1.json"
SEED = ROOT / "fixtures" / "seed" / "synthetic_centre_v1.json"

def _is_correct(submitted: str, expected: str) -> bool:
    return normalise_answer(submitted) == normalise_answer(expected)

def seed_db(db: Session) -> dict:
    contract = json.loads(CONTRACT.read_text())
    seed = json.loads(SEED.read_text())
    policy = load_policy()
    # Clear existing (for idempotent test runs)
    # For Postgres we need to delete in FK order
    for tbl in [MasteryEvidence, Attempt, Question, CurriculumChunk, GuardianLink, Enrolment, Class, Student, User, Centre]:
        db.query(tbl).delete()
    db.flush()

    # Centres
    for c in seed["entities"]["centres"]:
        db.add(Centre(id=c["id"], display_name=c["display_name"], is_synthetic=c.get("is_synthetic", True)))
    # Tutors as users
    for t in seed["entities"]["tutors"]:
        db.add(User(id=t["id"], centre_id=t["centre_id"], role=t.get("role", "tutor"), display_name=t["display_name"], is_synthetic=t.get("is_synthetic", True)))
    # Students
    for s in seed["entities"]["students"]:
        db.add(Student(id=s["id"], centre_id=s["centre_id"], level_id=s["level_id"], display_name=s["display_name"], is_synthetic=s.get("is_synthetic", True)))
        # Also create a user row for the student for RBAC tests (student role)
        db.add(User(id=f"USER-{s['id']}", centre_id=s["centre_id"], role="student", display_name=s["display_name"] + " (user)", is_synthetic=True))
    # Guardian users
    for g in seed["entities"]["guardian_links"]:
        # guardian_links are separate; also create a user for guardian role where verified
        # Use deterministic guardian user ids
        pass
    # Classes
    for cl in seed["entities"]["classes"]:
        db.add(Class(id=cl["id"], centre_id=cl["centre_id"], tutor_id=cl["tutor_id"], subject_id=cl["subject_id"], level_id=cl["level_id"], topic_id=cl["topic_id"]))
    # Enrolments
    for e in seed["entities"]["enrolments"]:
        db.add(Enrolment(id=e["id"], class_id=e["class_id"], student_id=e["student_id"], status=e["status"]))
    # Guardian links
    for g in seed["entities"]["guardian_links"]:
        db.add(GuardianLink(id=g["id"], student_id=g["student_id"], display_name=g["display_name"], verification_status=g["verification_status"], reporting_consent=g["reporting_consent"], is_synthetic=g.get("is_synthetic", True)))
    # Curriculum chunks
    for ch in seed["entities"]["curriculum_chunks"]:
        db.add(CurriculumChunk(id=ch["id"], source_id=ch["source_id"], subskill_id=ch["subskill_id"], approval_status=ch["approval_status"], text=ch["text"]))
    # Questions
    q_index = {q["id"]: q for q in contract["questions"]}
    for q in contract["questions"]:
        db.add(Question(id=q["id"], source_id=q["source_id"], subskill_id=q["subskill_id"], template_id=q["template_id"], difficulty=q["difficulty"], prompt=q["prompt"], expected_answer=q["expected_answer"], answer_type=q["answer_type"], status=q["status"], selection_rank=q["selection_rank"]))
    db.flush()
    # Attempts — compute is_correct deterministically
    for a in seed["attempts"]:
        q = q_index[a["question_id"]]
        is_corr = _is_correct(a["submitted_answer"], q["expected_answer"])
        db.add(Attempt(id=a["id"], student_id=a["student_id"], question_id=a["question_id"], submitted_answer=a["submitted_answer"], grading_status=a["grading_status"], is_correct=is_corr))
    db.flush()
    # Evidence
    for ev in seed["evidence"]:
        att = next(x for x in seed["attempts"] if x["id"] == ev["attempt_id"])
        q = q_index[att["question_id"]]
        is_corr = _is_correct(att["submitted_answer"], q["expected_answer"])
        db.add(MasteryEvidence(id=ev["id"], attempt_id=ev["attempt_id"], student_id=att["student_id"], subskill_id=q["subskill_id"], is_correct=is_corr, policy_id=policy["policy_id"], policy_version=policy["version"]))
    db.flush()
    # Compute mastery states for each (student, subskill) that has eligible evidence
    seen = set()
    for ev in seed["evidence"]:
        att = next(x for x in seed["attempts"] if x["id"] == ev["attempt_id"])
        q = q_index[att["question_id"]]
        key = (att["student_id"], q["subskill_id"])
        if key not in seen:
            seen.add(key)
            upsert_mastery_state(db, key[0], key[1])
    db.commit()
    # Also ensure insufficient_evidence case: STU-SYNTH-A / FRC-MULTIPLY-WHOLE already covered (1 attempt)
    return {"contract": contract["contract_id"], "seed": seed["seed_id"]}

