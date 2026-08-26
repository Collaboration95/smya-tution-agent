"use client";

import { useEffect, useState } from "react";
import { apiUrl } from "../../lib/api";

type Assignment = {
  id: string;
  student_id: string;
  status: "assigned" | "active" | "closed";
  draft_status: string;
  subskill_id: string;
  difficulty: string;
  question_count: number;
  policy_version: string;
};

const STUDENTS = [
  { id: "USER-STU-SYNTH-A", label: "Student A · needs support" },
  { id: "USER-STU-SYNTH-B", label: "Student B · secure" },
];

function statusClass(status: Assignment["status"]) {
  return status === "closed" ? "status-pill status-pill--closed" : status === "active" ? "status-pill status-pill--active" : "status-pill status-pill--ready";
}

export default function StudentAssignmentsPage() {
  const [userId, setUserId] = useState(STUDENTS[0].id);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    const candidate = new URLSearchParams(window.location.search).get("user");
    if (STUDENTS.some((student) => student.id === candidate)) setUserId(candidate as string);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetch(apiUrl("/api/practice/assignments"), {
      headers: { "X-User-Id": userId },
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail ?? `Unable to load assignments (${response.status})`);
        return payload as Assignment[];
      })
      .then(setAssignments)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "Unable to load assignments");
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [retryToken, userId]);

  return (
    <div className="page-shell">
      <div className="eyebrow">Student workspace</div>
      <h1 className="display-title" style={{ marginTop: "0.65rem" }}>Your next practice set.</h1>
      <p className="muted" style={{ maxWidth: "38rem", marginTop: "0.8rem" }}>
        Choose a seeded student to preview the same approved workflow from the learner&apos;s point of view. The server still owns identity and assignment scope.
      </p>

      <div className="surface-card surface-card--flat identity-panel">
        <label htmlFor="student-user">Preview student</label>
        <select id="student-user" value={userId} onChange={(event) => setUserId(event.target.value)}>
          {STUDENTS.map((student) => <option key={student.id} value={student.id}>{student.label}</option>)}
        </select>
        <span className="muted mono" style={{ fontSize: "0.74rem" }}>{userId}</span>
      </div>

      <div aria-live="polite" className="inline-status">{loading ? "Loading assigned practice…" : error ? "The assignment list could not be loaded." : `${assignments.length} assignment${assignments.length === 1 ? "" : "s"} available`}</div>
      {error ? (
        <div className="error-panel" role="alert">
          <strong>Practice is unavailable right now.</strong>
          <p style={{ margin: "0.35rem 0 0" }}>{error}</p>
          <button type="button" className="button button--secondary" style={{ marginTop: "0.9rem" }} onClick={() => setRetryToken((current) => current + 1)}>Retry</button>
        </div>
      ) : loading ? (
        <div className="empty-state">Reserving space for your assignments…</div>
      ) : assignments.length === 0 ? (
        <div className="empty-state">
          <strong>No approved practice is assigned yet.</strong>
          <p style={{ margin: "0.35rem 0 0" }}>A tutor-approved draft will appear here when it is ready.</p>
        </div>
      ) : (
        <div className="assignment-list">
          {assignments.map((assignment) => (
            <a key={assignment.id} className="surface-card assignment-row" href={`/student/practice/${assignment.id}?user=${encodeURIComponent(userId)}`}>
              <div>
                <div className="assignment-row__title">Fraction practice</div>
                <div className="assignment-row__meta">{assignment.subskill_id} · {assignment.question_count} questions · {assignment.difficulty} · policy {assignment.policy_version}</div>
              </div>
              <span className={statusClass(assignment.status)}>{assignment.status}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
