"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl } from "../../../lib/api";

type JobBrief = {
  id: string;
  type: string;
  status: string;
  student_id: string;
  created_at: string;
};

type GuardianLink = {
  id: string;
  display_name: string;
  verification_status: string;
  reporting_consent: boolean;
};

type Delivery = {
  id: string;
  status: string;
  provider_message_id: string | null;
  blocked_reason: string | null;
};

type AuditEntry = {
  event: string;
  actor_id: string;
  actor_role: string;
  created_at: string | null;
};

type ReportContent = {
  headline?: string;
  progress_signal?: string;
  next_steps?: string[];
};

type Draft = {
  id: string;
  job_id: string;
  student_id: string;
  status: string;
  content: ReportContent;
  guardian_links: GuardianLink[];
  approved_guardian_link_id: string | null;
  review_reason: string | null;
  blocked_reason: string | null;
  delivery: Delivery | null;
  audit: AuditEntry[];
};

const USER_OPTIONS = [
  { id: "TUT-SYNTH-ALPHA", label: "TUT-SYNTH-ALPHA (assigned)" },
  { id: "TUT-SYNTH-BRAVO", label: "TUT-SYNTH-BRAVO (unassigned)" },
];

function statusLabel(status: string) {
  return status.replaceAll("_", " ");
}

function statusClass(status: string) {
  if (status === "delivered") return "report-status report-status--success";
  if (status === "blocked" || status === "rejected") return "report-status report-status--danger";
  if (status === "approved" || status === "queued_for_delivery") return "report-status report-status--active";
  return "report-status report-status--review";
}

function guardianLabel(link: GuardianLink) {
  const verification = link.verification_status === "verified" ? "verified" : "not verified";
  const consent = link.reporting_consent ? "consent on" : "consent missing";
  return `${link.display_name} · ${verification} · ${consent}`;
}

async function readResponse(response: Response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : body.detail?.reason;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return body;
}

export default function TutorReportsPage() {
  const [userId, setUserId] = useState("TUT-SYNTH-ALPHA");
  const [jobs, setJobs] = useState<JobBrief[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [selections, setSelections] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const loadController = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    loadController.current?.abort();
    const controller = new AbortController();
    loadController.current = controller;
    setLoading(true);
    setError(null);
    try {
      const jobsResponse = await fetch(apiUrl("/api/tutor/jobs"), {
        headers: { "X-User-Id": userId },
        cache: "no-store",
        signal: controller.signal,
      });
      const visibleJobs = (await readResponse(jobsResponse)) as JobBrief[];
      const reportJobs = visibleJobs.filter((job) => job.type === "parent_report");
      const draftEntries = (await Promise.all(
        reportJobs.map(async (job) => {
          const response = await fetch(apiUrl(`/api/parent-reports/jobs/${job.id}`), {
            headers: { "X-User-Id": userId },
            cache: "no-store",
            signal: controller.signal,
          });
          if (response.status === 404) return null;
          return [job.id, (await readResponse(response)) as Draft] as const;
        }),
      )).filter((entry): entry is readonly [string, Draft] => entry !== null);
      setJobs(reportJobs);
      setDrafts(Object.fromEntries(draftEntries));
      setSelections((current) => {
        const next = { ...current };
        for (const [, draft] of draftEntries) {
          const verified = draft.guardian_links.find(
            (link) => link.verification_status === "verified" && link.reporting_consent,
          );
          if (!next[draft.id] && verified) next[draft.id] = verified.id;
        }
        return next;
      });
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setError(caught instanceof Error ? caught.message : "Reports could not be loaded");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    document.title = "Parent reports — SMYA Co-Tutor";
    void load();
    return () => loadController.current?.abort();
  }, [load]);

  async function mutate(draft: Draft, action: "approve" | "reject" | "queue" | "send") {
    if (busyKey) return;
    const note = notes[draft.id]?.trim() ?? "";
    if (action === "approve" && !selections[draft.id]) {
      setError("Choose a verified guardian with reporting consent before approving.");
      return;
    }
    if (action === "reject" && !note) {
      setError("Add a short review note before rejecting this draft.");
      return;
    }
    const key = `${draft.id}:${action}`;
    setBusyKey(key);
    setError(null);
    setNotice(null);
    try {
      const body = action === "approve"
        ? { guardian_link_id: selections[draft.id], reason: note || undefined }
        : action === "reject"
          ? { reason: note }
          : undefined;
      const path = action === "send"
        ? `/api/parent-reports/deliveries/${draft.delivery?.id}/send`
        : `/api/parent-reports/drafts/${draft.id}/${action}`;
      const response = await fetch(apiUrl(path), {
        method: "POST",
        headers: {
          "X-User-Id": userId,
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      await readResponse(response);
      setNotice(action === "send" ? "Simulated delivery completed." : `Report ${action}d.`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The report action could not be completed");
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <div className="page-shell report-page">
      <div className="report-page__header">
        <div>
          <Link className="button button--quiet report-back" href="/tutor">← Tutor jobs</Link>
          <p className="eyebrow">Communication gate</p>
          <h1 className="display-title report-page__title">Parent reports, held at the last safe step.</h1>
          <p className="report-page__intro">
            Review the bounded comparison, confirm the recipient and consent, then queue a simulated copy.
            Nothing leaves this prototype.
          </p>
        </div>
        <div className="surface-card surface-card--flat report-guardrail" aria-label="Delivery guardrail">
          <span className="report-guardrail__mark" aria-hidden="true">✓</span>
          <div>
            <p className="eyebrow">Required before delivery</p>
            <p className="report-guardrail__text">Verified guardian · consent · tutor approval</p>
          </div>
        </div>
      </div>

      <section className="surface-card surface-card--flat report-toolbar" aria-label="Tutor identity">
        <label className="report-field__label" htmlFor="report-tutor">Tutor identity</label>
        <select
          id="report-tutor"
          className="report-select"
          value={userId}
          onChange={(event) => setUserId(event.target.value)}
        >
          {USER_OPTIONS.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
        </select>
        <span className="muted report-toolbar__hint">Authorization is derived on the server.</span>
      </section>

      <div className="report-status-region" aria-live="polite">
        {loading ? <p className="inline-status">Loading parent reports…</p> : null}
        {notice ? <p className="inline-status inline-status--success">{notice}</p> : null}
        {error ? (
          <div className="report-error" role="alert">
            <p className="inline-status inline-status--error">{error}</p>
            <button className="button button--secondary" type="button" onClick={() => void load()}>
              Try again
            </button>
          </div>
        ) : null}
      </div>

      {!loading && !error && jobs.length === 0 ? (
        <div className="report-empty">
          <p className="eyebrow">No assigned reports</p>
          <h2>No parent-report draft is waiting for this tutor.</h2>
          <p>Switch to the assigned synthetic tutor or create a report job through the API.</p>
        </div>
      ) : null}

      <section className="report-grid" aria-label="Parent report drafts">
        {jobs.map((job) => {
          const draft = drafts[job.id];
          if (!draft) return <div className="surface-card report-card report-card--loading" key={job.id}>Loading draft…</div>;
          const note = notes[draft.id] ?? "";
          const selection = selections[draft.id] ?? "";
          const isBusy = busyKey?.startsWith(`${draft.id}:`) ?? false;
          const approvedLinks = draft.guardian_links.filter(
            (link) => link.verification_status === "verified" && link.reporting_consent,
          );
          return (
            <article className="surface-card surface-card--flat report-card" key={draft.id}>
              <div className="report-card__topline">
                <div>
                  <p className="eyebrow">Draft review</p>
                  <h2>{draft.student_id}</h2>
                  <p className="muted report-card__meta">Job {job.id} · {new Date(job.created_at).toLocaleString()}</p>
                </div>
                <span className={statusClass(draft.status)}>{statusLabel(draft.status)}</span>
              </div>

              <div className="report-content">
                <p className="report-content__signal">{draft.content.progress_signal ?? "comparison pending"}</p>
                <p className="report-content__headline">{draft.content.headline ?? "Bounded report content is not available."}</p>
                {draft.content.next_steps?.length ? (
                  <div>
                    <p className="report-subhead">Suggested next steps</p>
                    <ul className="report-next-steps">
                      {draft.content.next_steps.map((step) => <li key={step}>{step}</li>)}
                    </ul>
                  </div>
                ) : null}
              </div>

              <div className="report-recipient">
                <div>
                  <p className="report-subhead">Recipient and consent</p>
                  <p className="muted report-recipient__hint">Only a verified, consenting guardian can be selected.</p>
                </div>
                <label className="report-field__label" htmlFor={`guardian-${draft.id}`}>Guardian link</label>
                <select
                  id={`guardian-${draft.id}`}
                  className="report-select report-select--wide"
                  value={selection}
                  onChange={(event) => setSelections((current) => ({ ...current, [draft.id]: event.target.value }))}
                  disabled={isBusy || draft.status === "delivered" || draft.status === "rejected"}
                >
                  <option value="">Choose a guardian</option>
                  {draft.guardian_links.map((link) => (
                    <option
                      key={link.id}
                      value={link.id}
                      disabled={link.verification_status !== "verified" || !link.reporting_consent}
                    >
                      {guardianLabel(link)}
                    </option>
                  ))}
                </select>
                {approvedLinks.length === 0 ? (
                  <p className="report-inline-warning">Delivery is blocked until a verified guardian with consent exists.</p>
                ) : null}
              </div>

              {draft.status !== "delivered" && draft.status !== "rejected" ? (
                <div className="report-review-field">
                  <label className="report-field__label" htmlFor={`note-${draft.id}`}>Review note</label>
                  <input
                    id={`note-${draft.id}`}
                    className="report-input"
                    value={note}
                    maxLength={1000}
                    onChange={(event) => setNotes((current) => ({ ...current, [draft.id]: event.target.value }))}
                    placeholder="Optional for approval; required for rejection"
                    disabled={isBusy}
                  />
                </div>
              ) : null}

              <div className="report-actions">
                {(draft.status === "pending_tutor_review" || draft.status === "blocked") ? (
                  <>
                    <button
                      className="button button--primary"
                      type="button"
                      disabled={isBusy || !selection || !approvedLinks.some((link) => link.id === selection)}
                      aria-busy={busyKey === `${draft.id}:approve`}
                      onClick={() => void mutate(draft, "approve")}
                    >
                      {busyKey === `${draft.id}:approve` ? "Approving…" : "Approve report"}
                    </button>
                    {draft.status === "pending_tutor_review" ? (
                      <button
                        className="button button--danger"
                        type="button"
                        disabled={isBusy || !note.trim()}
                        aria-busy={busyKey === `${draft.id}:reject`}
                        onClick={() => void mutate(draft, "reject")}
                      >
                        {busyKey === `${draft.id}:reject` ? "Rejecting…" : "Reject draft"}
                      </button>
                    ) : null}
                  </>
                ) : null}
                {draft.status === "approved" ? (
                  <button
                    className="button button--primary"
                    type="button"
                    disabled={isBusy}
                    aria-busy={busyKey === `${draft.id}:queue`}
                    onClick={() => void mutate(draft, "queue")}
                  >
                    {busyKey === `${draft.id}:queue` ? "Queueing…" : "Queue simulated delivery"}
                  </button>
                ) : null}
                {draft.status === "queued_for_delivery" && draft.delivery ? (
                  <button
                    className="button button--primary"
                    type="button"
                    disabled={isBusy}
                    aria-busy={busyKey === `${draft.id}:send`}
                    onClick={() => void mutate(draft, "send")}
                  >
                    {busyKey === `${draft.id}:send` ? "Sending…" : "Send simulated copy"}
                  </button>
                ) : null}
                {draft.status === "delivered" ? (
                  <p className="report-complete">Simulated delivery complete · {draft.delivery?.provider_message_id}</p>
                ) : null}
              </div>

              {draft.blocked_reason ? <p className="report-inline-warning">Blocked: {statusLabel(draft.blocked_reason)}</p> : null}
              {draft.review_reason && draft.status === "rejected" ? <p className="report-inline-warning">Review note: {draft.review_reason}</p> : null}
              <details className="report-audit">
                <summary>Open job trace</summary>
                <p className="muted">Draft {draft.id} · approved content remains bounded and auditable.</p>
                {draft.audit.length ? (
                  <ul className="report-audit__list">
                    {draft.audit.map((event) => (
                      <li key={`${event.event}-${event.created_at}`}>
                        <span>{statusLabel(event.event)}</span>
                        <span className="muted">{event.actor_id} ({event.actor_role}) · {event.created_at ? new Date(event.created_at).toLocaleString() : "—"}</span>
                      </li>
                    ))}
                  </ul>
                ) : <p className="muted">No workflow events yet.</p>}
                <Link className="button button--secondary" href={`/tutor/jobs/${job.id}`}>View job trace</Link>
              </details>
            </article>
          );
        })}
      </section>
    </div>
  );
}
