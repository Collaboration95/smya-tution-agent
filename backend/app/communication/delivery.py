from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.orm import Session

from backend.app.auth.context import CallerContext
from backend.app.auth.permissions import PermissionDenied, can_approve_student
from backend.app.db.models import (
    AgentJob,
    AuditEvent,
    GuardianLink,
    ParentReportDelivery,
    ParentReportDraft,
)


STAFF_ROLES = {"admin", "tutor"}


class DeliveryBlocked(ValueError):
    """A deterministic recipient or consent gate stopped the workflow."""

    def __init__(self, reason: str, entity_id: str):
        self.reason = reason
        self.entity_id = entity_id
        super().__init__(f"parent report delivery blocked: {reason}")


class DeliveryAdapter(Protocol):
    def send(self, delivery: ParentReportDelivery) -> str:
        """Return a provider message identifier for one delivery key."""


class SimulatedDeliveryAdapter:
    """A deterministic, in-process adapter with idempotent send semantics."""

    def __init__(self) -> None:
        self.sent: dict[str, str] = {}
        self.send_count = 0

    def send(self, delivery: ParentReportDelivery) -> str:
        existing = self.sent.get(delivery.idempotency_key)
        if existing is not None:
            return existing
        provider_message_id = f"sim-{hashlib.sha256(delivery.idempotency_key.encode()).hexdigest()[:16]}"
        self.sent[delivery.idempotency_key] = provider_message_id
        self.send_count += 1
        return provider_message_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _content_hash(content_json: str) -> str:
    return hashlib.sha256(content_json.encode("utf-8")).hexdigest()


def delivery_idempotency_key(draft: ParentReportDraft, guardian_link: GuardianLink) -> str:
    basis = f"parent-report:{draft.id}:{draft.artifact_id}:{guardian_link.id}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:64]


def _audit(
    db: Session,
    caller: CallerContext,
    event: str,
    entity_type: str,
    entity_id: str,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            id=f"aud-{uuid.uuid4().hex[:8]}",
            centre_id=caller.centre_id,
            actor_id=caller.user_id,
            actor_role=caller.role,
            event=event,
            entity_type=entity_type,
            entity_id=entity_id,
            before_json=json.dumps(before, sort_keys=True) if before is not None else None,
            after_json=json.dumps(after, sort_keys=True) if after is not None else None,
            created_at=_now(),
        )
    )


def _draft(db: Session, draft_id: str, *, for_update: bool = False) -> ParentReportDraft:
    query = db.query(ParentReportDraft).filter(ParentReportDraft.id == draft_id)
    if for_update:
        query = query.with_for_update()
    record = query.first()
    if record is None:
        raise ValueError("parent report draft not found")
    return record


def _delivery(db: Session, delivery_id: str, *, for_update: bool = False) -> ParentReportDelivery:
    query = db.query(ParentReportDelivery).filter(ParentReportDelivery.id == delivery_id)
    if for_update:
        query = query.with_for_update()
    record = query.first()
    if record is None:
        raise ValueError("parent report delivery not found")
    return record


def _require_draft_actor(
    db: Session,
    caller: CallerContext,
    draft: ParentReportDraft,
    *,
    allow_worker: bool,
) -> None:
    if caller.role in STAFF_ROLES:
        if not can_approve_student(db, caller, draft.student_id):
            raise PermissionDenied("parent report access denied")
        return
    if allow_worker and caller.role == "worker":
        job = (
            db.query(AgentJob)
            .filter(
                AgentJob.id == draft.job_id,
                AgentJob.centre_id == draft.centre_id,
                AgentJob.student_id == draft.student_id,
            )
            .first()
        )
        if (
            job is None
            or caller.job_id != job.id
            or caller.centre_id != draft.centre_id
            or caller.student_id != draft.student_id
        ):
            raise PermissionDenied("worker is not bound to this parent report")
        return
    raise PermissionDenied("parent report access denied")


def _guardian_link(
    db: Session,
    draft: ParentReportDraft,
    guardian_link_id: str | None,
) -> tuple[GuardianLink | None, str | None]:
    if not guardian_link_id:
        return None, "guardian_link_required"
    link = (
        db.query(GuardianLink)
        .filter(
            GuardianLink.id == guardian_link_id,
            GuardianLink.centre_id == draft.centre_id,
            GuardianLink.student_id == draft.student_id,
        )
        .first()
    )
    if link is None:
        return None, "guardian_link_not_found"
    if link.verification_status != "verified":
        return link, "guardian_link_not_verified"
    if not link.reporting_consent:
        return link, "reporting_consent_missing"
    return link, None


def _block(
    db: Session,
    caller: CallerContext,
    draft: ParentReportDraft,
    reason: str,
    delivery: ParentReportDelivery | None = None,
) -> None:
    now = _now()
    draft_before = {"status": draft.status, "blocked_reason": draft.blocked_reason}
    if draft.status != "blocked" or draft.blocked_reason != reason:
        draft.status = "blocked"
        draft.blocked_reason = reason
        draft.updated_at = now
        _audit(
            db,
            caller,
            "parent_report.blocked",
            "parent_report_draft",
            draft.id,
            before=draft_before,
            after={"status": draft.status, "blocked_reason": reason},
        )
    if delivery is not None and (
        delivery.status != "blocked" or delivery.blocked_reason != reason
    ):
        delivery_before = {"status": delivery.status, "blocked_reason": delivery.blocked_reason}
        delivery.status = "blocked"
        delivery.blocked_reason = reason
        delivery.updated_at = now
        _audit(
            db,
            caller,
            "parent_report_delivery.blocked",
            "parent_report_delivery",
            delivery.id,
            before=delivery_before,
            after={"status": delivery.status, "blocked_reason": reason},
        )
    db.flush()
    raise DeliveryBlocked(reason, delivery.id if delivery is not None else draft.id)


def approve_parent_report(
    db: Session,
    caller: CallerContext,
    draft_id: str,
    guardian_link_id: str,
    reason: str | None = None,
) -> ParentReportDraft:
    draft = _draft(db, draft_id, for_update=True)
    _require_draft_actor(db, caller, draft, allow_worker=False)
    if draft.status in {"approved", "queued_for_delivery", "delivered"}:
        if draft.approved_guardian_link_id != guardian_link_id:
            raise ValueError("parent report has already been approved for another guardian")
        return draft
    if draft.status == "rejected":
        raise ValueError("rejected parent report cannot be approved")
    if draft.status not in {"pending_tutor_review", "blocked"}:
        raise ValueError(f"parent report cannot be approved from {draft.status}")

    link, gate_reason = _guardian_link(db, draft, guardian_link_id)
    if gate_reason:
        _block(db, caller, draft, gate_reason)
    assert link is not None
    now = _now()
    before = {"status": draft.status, "approved_guardian_link_id": draft.approved_guardian_link_id}
    draft.status = "approved"
    draft.approved_guardian_link_id = link.id
    draft.reviewed_by = caller.user_id
    review_reason = (reason or "").strip() or "Tutor approved parent report"
    if len(review_reason) > 1000:
        raise ValueError("approval reason is too long")
    draft.review_reason = review_reason
    draft.approved_by = caller.user_id
    draft.approved_at = now
    draft.rejected_at = None
    draft.blocked_reason = None
    draft.updated_at = now
    _audit(
        db,
        caller,
        "parent_report.approved",
        "parent_report_draft",
        draft.id,
        before=before,
        after={
            "status": draft.status,
            "approved_guardian_link_id": link.id,
            "approved_by": caller.user_id,
            "content_sha256": _content_hash(draft.content_json),
        },
    )
    db.flush()
    return draft


def reject_parent_report(
    db: Session,
    caller: CallerContext,
    draft_id: str,
    reason: str,
) -> ParentReportDraft:
    draft = _draft(db, draft_id, for_update=True)
    _require_draft_actor(db, caller, draft, allow_worker=False)
    reason = reason.strip()
    if not reason:
        raise ValueError("rejection reason is required")
    if len(reason) > 1000:
        raise ValueError("rejection reason is too long")
    if draft.status == "rejected":
        return draft
    if draft.status != "pending_tutor_review":
        raise ValueError(f"parent report cannot be rejected from {draft.status}")
    now = _now()
    before = {"status": draft.status}
    draft.status = "rejected"
    draft.reviewed_by = caller.user_id
    draft.review_reason = reason
    draft.rejected_at = now
    draft.updated_at = now
    _audit(
        db,
        caller,
        "parent_report.rejected",
        "parent_report_draft",
        draft.id,
        before=before,
        after={"status": draft.status, "reviewed_by": caller.user_id, "reason": reason},
    )
    db.flush()
    return draft


def queue_parent_report(
    db: Session,
    caller: CallerContext,
    draft_id: str,
) -> ParentReportDelivery:
    draft = _draft(db, draft_id, for_update=True)
    _require_draft_actor(db, caller, draft, allow_worker=False)
    existing = (
        db.query(ParentReportDelivery)
        .filter(ParentReportDelivery.draft_id == draft.id)
        .with_for_update()
        .first()
    )
    if draft.status in {"queued_for_delivery", "delivered"}:
        if existing is None:
            raise ValueError("parent report delivery record is missing")
        return existing
    if draft.status != "approved":
        raise ValueError("only an approved parent report can enter the delivery queue")
    link, gate_reason = _guardian_link(db, draft, draft.approved_guardian_link_id)
    if gate_reason:
        _block(db, caller, draft, gate_reason, existing)
    assert link is not None
    now = _now()
    key = delivery_idempotency_key(draft, link)
    content_json = json.dumps(json.loads(draft.content_json), sort_keys=True)
    if existing is None:
        existing = ParentReportDelivery(
            id=f"report-delivery-{uuid.uuid4().hex[:8]}",
            draft_id=draft.id,
            centre_id=draft.centre_id,
            student_id=draft.student_id,
            guardian_link_id=link.id,
            status="queued_for_delivery",
            idempotency_key=key,
            approved_content_json=content_json,
            approved_by=draft.approved_by or caller.user_id,
            approved_at=draft.approved_at or now,
            queued_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(existing)
        db.flush()
    else:
        before = {"status": existing.status, "guardian_link_id": existing.guardian_link_id}
        existing.guardian_link_id = link.id
        existing.status = "queued_for_delivery"
        existing.idempotency_key = key
        existing.approved_content_json = content_json
        existing.approved_by = draft.approved_by or caller.user_id
        existing.approved_at = draft.approved_at or now
        existing.queued_at = now
        existing.delivered_at = None
        existing.blocked_reason = None
        existing.provider_message_id = None
        existing.updated_at = now
        _audit(
            db,
            caller,
            "parent_report_delivery.queued",
            "parent_report_delivery",
            existing.id,
            before=before,
            after={"status": existing.status, "guardian_link_id": link.id, "idempotency_key": key},
        )
    draft_before = {"status": draft.status}
    draft.status = "queued_for_delivery"
    draft.queued_at = now
    draft.blocked_reason = None
    draft.updated_at = now
    _audit(
        db,
        caller,
        "parent_report.queued_for_delivery",
        "parent_report_draft",
        draft.id,
        before=draft_before,
        after={"status": draft.status, "delivery_id": existing.id, "idempotency_key": key},
    )
    db.flush()
    return existing


def deliver_parent_report(
    db: Session,
    caller: CallerContext,
    delivery_id: str,
    adapter: DeliveryAdapter | None = None,
) -> ParentReportDelivery:
    delivery = _delivery(db, delivery_id, for_update=True)
    draft = _draft(db, delivery.draft_id, for_update=True)
    _require_draft_actor(db, caller, draft, allow_worker=True)
    if delivery.status == "delivered":
        return delivery
    if delivery.status != "queued_for_delivery" or draft.status != "queued_for_delivery":
        raise ValueError("only a queued parent report can be delivered")
    link, gate_reason = _guardian_link(db, draft, delivery.guardian_link_id)
    if gate_reason:
        _block(db, caller, draft, gate_reason, delivery)
    assert link is not None
    adapter = adapter or SimulatedDeliveryAdapter()
    provider_message_id = adapter.send(delivery)
    now = _now()
    delivery_before = {"status": delivery.status}
    delivery.status = "delivered"
    delivery.provider_message_id = provider_message_id
    delivery.delivered_at = now
    delivery.blocked_reason = None
    delivery.updated_at = now
    draft_before = {"status": draft.status}
    draft.status = "delivered"
    draft.delivered_at = now
    draft.updated_at = now
    content_details = {
        "provider_message_id": provider_message_id,
        "idempotency_key": delivery.idempotency_key,
        "content_sha256": _content_hash(delivery.approved_content_json),
        "guardian_link_id": link.id,
    }
    _audit(
        db,
        caller,
        "parent_report_delivery.delivered",
        "parent_report_delivery",
        delivery.id,
        before=delivery_before,
        after={"status": delivery.status, **content_details},
    )
    _audit(
        db,
        caller,
        "parent_report.delivered",
        "parent_report_draft",
        draft.id,
        before=draft_before,
        after={"status": draft.status, **content_details},
    )
    db.flush()
    return delivery


def get_parent_report_draft(
    db: Session,
    caller: CallerContext,
    draft_id: str,
) -> ParentReportDraft:
    draft = _draft(db, draft_id)
    _require_draft_actor(db, caller, draft, allow_worker=True)
    return draft


def get_parent_report_delivery(
    db: Session,
    caller: CallerContext,
    delivery_id: str,
) -> ParentReportDelivery:
    delivery = _delivery(db, delivery_id)
    draft = _draft(db, delivery.draft_id)
    if caller.role == "guardian":
        if caller.guardian_link_id != delivery.guardian_link_id or delivery.status != "delivered":
            raise PermissionDenied("guardian delivery access denied")
        _, gate_reason = _guardian_link(db, draft, caller.guardian_link_id)
        if gate_reason:
            raise PermissionDenied("guardian delivery access denied")
        return delivery
    _require_draft_actor(db, caller, draft, allow_worker=True)
    return delivery


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def serialize_delivery(delivery: ParentReportDelivery, *, include_content: bool = True) -> dict:
    return {
        "id": delivery.id,
        "draft_id": delivery.draft_id,
        "status": delivery.status,
        "idempotency_key": delivery.idempotency_key,
        "guardian_link_id": delivery.guardian_link_id,
        "approved_by": delivery.approved_by,
        "approved_at": _iso(delivery.approved_at),
        "queued_at": _iso(delivery.queued_at),
        "delivered_at": _iso(delivery.delivered_at),
        "provider_message_id": delivery.provider_message_id,
        "blocked_reason": delivery.blocked_reason,
        "approved_content": json.loads(delivery.approved_content_json) if include_content else None,
    }


def serialize_draft(db: Session, draft: ParentReportDraft, *, include_content: bool = True) -> dict:
    delivery = (
        db.query(ParentReportDelivery)
        .filter(ParentReportDelivery.draft_id == draft.id)
        .first()
    )
    guardians = (
        db.query(GuardianLink)
        .filter(
            GuardianLink.centre_id == draft.centre_id,
            GuardianLink.student_id == draft.student_id,
        )
        .order_by(GuardianLink.display_name.asc(), GuardianLink.id.asc())
        .all()
    )
    audit_entities = [draft.id] + ([delivery.id] if delivery is not None else [])
    audits = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.centre_id == draft.centre_id,
            AuditEvent.entity_id.in_(audit_entities),
        )
        .order_by(AuditEvent.created_at.asc())
        .all()
    )
    return {
        "id": draft.id,
        "job_id": draft.job_id,
        "artifact_id": draft.artifact_id,
        "student_id": draft.student_id,
        "status": draft.status,
        "snapshot_ids": json.loads(draft.snapshot_ids_json),
        "evidence_ids": json.loads(draft.evidence_ids_json),
        "content": json.loads(draft.content_json) if include_content else None,
        "approved_guardian_link_id": draft.approved_guardian_link_id,
        "reviewed_by": draft.reviewed_by,
        "review_reason": draft.review_reason,
        "approved_by": draft.approved_by,
        "approved_at": _iso(draft.approved_at),
        "rejected_at": _iso(draft.rejected_at),
        "blocked_reason": draft.blocked_reason,
        "queued_at": _iso(draft.queued_at),
        "delivered_at": _iso(draft.delivered_at),
        "guardian_links": [
            {
                "id": link.id,
                "display_name": link.display_name,
                "verification_status": link.verification_status,
                "reporting_consent": link.reporting_consent,
            }
            for link in guardians
        ],
        "delivery": serialize_delivery(delivery) if delivery is not None else None,
        "audit": [
            {
                "id": event.id,
                "event": event.event,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "actor_id": event.actor_id,
                "actor_role": event.actor_role,
                "before": json.loads(event.before_json) if event.before_json else None,
                "after": json.loads(event.after_json) if event.after_json else None,
                "created_at": _iso(event.created_at),
            }
            for event in audits
        ],
    }


def serialize_delivery_response(delivery: ParentReportDelivery, *, include_content: bool = True) -> dict:
    return serialize_delivery(delivery, include_content=include_content)
