"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { apiUrl } from "../../../../lib/api";

type Assignment = {
  id: string;
  status: "assigned" | "active" | "closed";
  draft_status: string;
  subskill_id: string;
  difficulty: string;
  question_count: number;
  policy_version: string;
};

type Question = {
  id: string;
  prompt: string;
  difficulty: string;
  subskill_id: string;
  template_id: string;
  source_id: string;
  answer_type: string;
};

type Hint = { question_id: string; level: number; text: string; source_id: string };
type Answer = { question_id: string; is_correct: boolean; hint_level: number; feedback: string };
type PracticeSession = {
  id: string;
  assignment_id: string;
  status: "active" | "completed" | "abandoned";
  current_index: number;
  total_questions: number;
  answered_count: number;
  current_question: Question | null;
  answers: Answer[];
  hints: Hint[];
};

type Props = { params: { assignmentId: string } };

async function requestJson<T>(url: string, options: RequestInit, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { ...options, signal });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail ?? `Request failed (${response.status})`);
  return payload as T;
}

export default function PracticePage({ params }: Props) {
  const [userId, setUserId] = useState("USER-STU-SYNTH-A");
  const [identityReady, setIdentityReady] = useState(false);
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [session, setSession] = useState<PracticeSession | null>(null);
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ text: string; correct: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const [hintLoading, setHintLoading] = useState(false);
  const [answerLoading, setAnswerLoading] = useState(false);
  const feedbackRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const candidate = new URLSearchParams(window.location.search).get("user");
    if (candidate === "USER-STU-SYNTH-A" || candidate === "USER-STU-SYNTH-B") setUserId(candidate);
    setIdentityReady(true);
  }, []);

  useEffect(() => {
    if (!identityReady) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setFeedback(null);
    document.title = "Practice — SMYA Co-Tutor";
    const headers = { "X-User-Id": userId };
    requestJson<Assignment>(apiUrl(`/api/practice/assignments/${params.assignmentId}`), { headers }, controller.signal)
      .then((loadedAssignment) => {
        setAssignment(loadedAssignment);
        return requestJson<PracticeSession>(apiUrl(`/api/practice/assignments/${params.assignmentId}/start`), { method: "POST", headers }, controller.signal);
      })
      .then((startedSession) => setSession(startedSession))
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "This practice session is unavailable");
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [identityReady, params.assignmentId, userId]);

  useEffect(() => {
    if (feedback) feedbackRef.current?.focus();
  }, [feedback]);

  const currentQuestion = session?.current_question ?? null;
  const currentHints = currentQuestion ? session?.hints.filter((hint) => hint.question_id === currentQuestion.id) ?? [] : [];
  const latestHint = currentHints[currentHints.length - 1] ?? null;
  const backHref = `/student?user=${encodeURIComponent(userId)}`;

  async function handleHint() {
    if (!session || !currentQuestion || hintLoading) return;
    const controller = new AbortController();
    setHintLoading(true);
    setError(null);
    try {
      const hint = await requestJson<Hint>(apiUrl(`/api/practice/sessions/${session.id}/hint`), {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-Id": userId },
        body: JSON.stringify({ question_id: currentQuestion.id }),
      }, controller.signal);
      setSession((current) => current ? { ...current, hints: [...current.hints.filter((item) => !(item.question_id === hint.question_id && item.level === hint.level)), hint] } : current);
    } catch (reason: unknown) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(reason instanceof Error ? reason.message : "The hint could not be loaded");
    } finally {
      setHintLoading(false);
    }
  }

  async function handleAnswer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !currentQuestion || answerLoading) return;
    if (!answer.trim()) {
      setValidationError("Enter an answer before checking it.");
      return;
    }
    setValidationError(null);
    setError(null);
    setAnswerLoading(true);
    const controller = new AbortController();
    try {
      const result = await requestJson<{ is_correct: boolean; feedback: string; session: PracticeSession }>(apiUrl(`/api/practice/sessions/${session.id}/answers`), {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-Id": userId },
        body: JSON.stringify({ question_id: currentQuestion.id, answer }),
      }, controller.signal);
      setFeedback({ text: result.feedback, correct: result.is_correct });
      setSession(result.session);
      setAnswer("");
    } catch (reason: unknown) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(reason instanceof Error ? reason.message : "The answer could not be checked");
    } finally {
      setAnswerLoading(false);
    }
  }

  return (
    <div className="practice-shell">
      <a href={backHref} className="button button--quiet" style={{ marginBottom: "1.5rem" }}>← Back to assignments</a>
      {loading ? <div className="empty-state" role="status">Loading the approved practice set…</div> : error && !session ? (
        <div className="error-panel" role="alert">
          <strong>This practice set is unavailable.</strong>
          <p style={{ margin: "0.35rem 0 0" }}>{error}</p>
          <a href={backHref} className="button button--secondary" style={{ marginTop: "0.9rem" }}>Return to assignments</a>
        </div>
      ) : assignment && session ? (
        <>
          <div className="practice-kicker"><span className="eyebrow">Assigned practice</span></div>
          <h1 className="display-title">A short set, one clear next step.</h1>
          <p className="muted" style={{ marginTop: "0.7rem" }}>{assignment.subskill_id} · {assignment.difficulty} practice · policy <span className="mono">{assignment.policy_version}</span></p>

          <section className="surface-card practice-card" aria-labelledby="question-heading">
            <ol className="practice-progress" aria-label={`Question ${Math.min(session.current_index + 1, session.total_questions)} of ${session.total_questions}`}>
              {Array.from({ length: session.total_questions }).map((_, index) => (
                <li key={index} className={`progress-step ${index < session.current_index ? "progress-step--done" : index === session.current_index && session.status === "active" ? "progress-step--current" : ""}`}>
                  <span className="progress-step__dot" aria-hidden="true" />
                  <span className="sr-only">Question {index + 1}</span>
                </li>
              ))}
            </ol>

            {session.status === "completed" || !currentQuestion ? (
              <div className="empty-state" role="status">
                <div className="eyebrow">Set complete</div>
                <h2 className="display-title" style={{ fontSize: "2rem", marginTop: "0.55rem" }}>Good work. Your evidence is recorded.</h2>
                <p className="muted">Your tutor can now see the objective results and the next diagnostic job can use this new evidence.</p>
                {feedback ? <div ref={feedbackRef} tabIndex={-1} className={`feedback ${feedback.correct ? "feedback--correct" : ""}`} role={feedback.correct ? "status" : "alert"}><strong>{feedback.correct ? "Correct." : "Keep going."}</strong> {feedback.text}</div> : null}
                <a href={backHref} className="button button--primary" style={{ marginTop: "0.7rem" }}>Back to assignments</a>
              </div>
            ) : (
              <>
                <div className="eyebrow">Question {session.current_index + 1} of {session.total_questions}</div>
                <h2 id="question-heading" className="display-title display-title--question" style={{ marginTop: "0.7rem" }}>{currentQuestion.prompt}</h2>
                <div className="question-meta">
                  <span>Objective answer</span>
                  <span>Source <span className="mono">{currentQuestion.source_id}</span></span>
                </div>

                {latestHint ? <div className="hint-card" role="status"><strong>Hint {latestHint.level}</strong><div>{latestHint.text}</div></div> : null}
                <form className="answer-form" noValidate onSubmit={handleAnswer}>
                  <label className="answer-label" htmlFor="answer">Your answer</label>
                  <input id="answer" className="answer-input" value={answer} onChange={(event) => { setAnswer(event.target.value); if (validationError) setValidationError(null); }} aria-invalid={validationError ? "true" : "false"} aria-describedby={validationError ? "answer-error answer-help" : "answer-help"} autoComplete="off" />
                  <span id="answer-help" className="answer-help">Use the exact form you think is correct, such as 3/4.</span>
                  {validationError ? <span id="answer-error" className="inline-status inline-status--error" role="alert">{validationError}</span> : null}
                  <div className="question-actions">
                    <button type="submit" className="button button--primary" disabled={answerLoading} aria-busy={answerLoading}>{answerLoading ? "Checking…" : "Check answer"}</button>
                    <button type="button" className="button button--secondary" onClick={handleHint} disabled={hintLoading} aria-busy={hintLoading}>{hintLoading ? "Loading hint…" : latestHint?.level === 2 ? "Use hint again" : "Show a hint"}</button>
                  </div>
                </form>
                {feedback ? <div ref={feedbackRef} tabIndex={-1} className={`feedback ${feedback.correct ? "feedback--correct" : ""}`} role={feedback.correct ? "status" : "alert"}><strong>{feedback.correct ? "Correct." : "Keep going."}</strong> {feedback.text}</div> : null}
                {error ? <div className="inline-status inline-status--error" role="alert">{error}</div> : null}
              </>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
