"use client";
import { useEffect, useState } from "react";
import { useCallback } from "react";
import { useParams } from "next/navigation";
import { apiUrl } from "../../../../lib/api";

function displayValue(value: unknown) {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export default function JobTracePage() {
  const params = useParams() as { id: string };
  const jobId = params.id;
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [userId, setUserId] = useState("TUT-SYNTH-ALPHA");
  const [reason, setReason] = useState("");
  const [correctedLabel, setCorrectedLabel] = useState("developing");
  const [alertReason, setAlertReason] = useState("");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    const r = await fetch(apiUrl(`/api/tutor/jobs/${jobId}`), {
      headers: { "X-User-Id": userId },
      cache: "no-store",
      signal,
    });
    const j = await r.json();
    if (!r.ok) throw new Error(JSON.stringify(j));
    setData(j);
    setErr(null);
  }, [jobId, userId]);

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setErr(null);
    load(controller.signal).catch(e => {
      if (e?.name !== "AbortError") setErr(String(e));
    });
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    document.title = data ? `Tutor review — ${data.job.id}` : "Tutor review — SMYA Co-Tutor";
  }, [data]);

  const decide = async (action: string) => {
    if (busyAction) return;
    if ((action === "accept" || action === "edit") && !data?.artifacts?.length) {
      setErr("No approved artifact exists; this job must remain blocked for tutor review.");
      return;
    }
    setBusyAction(action);
    setStatusMessage(null);
    const qs = new URLSearchParams({ action, reason });
    if (action === "edit") qs.set("corrected_label", correctedLabel);
    try {
      const r = await fetch(`${apiUrl(`/api/tutor/jobs/${jobId}/decision`)}?${qs.toString()}`, {
        method: "POST",
        headers: { "X-User-Id": userId },
      });
      const j = await r.json();
      if (!r.ok) throw new Error(JSON.stringify(j));
      await load();
      setStatusMessage(action === "edit" ? "Correction saved." : `Decision recorded: ${action}.`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusyAction(null);
    }
  };

  const excludeEvidence = async (evidenceId: string) => {
    if (busyAction) return;
    if (!reason.trim()) {
      setErr("Enter a reason before excluding evidence.");
      return;
    }
    setBusyAction(`exclude:${evidenceId}`);
    setStatusMessage(null);
    const qs = new URLSearchParams({ action: "exclude_evidence", evidence_id: evidenceId, reason });
    try {
      const r = await fetch(`${apiUrl(`/api/tutor/jobs/${jobId}/decision`)}?${qs.toString()}`, {
        method: "POST",
        headers: { "X-User-Id": userId },
      });
      const j = await r.json();
      if (!r.ok) throw new Error(JSON.stringify(j));
      await load();
      setStatusMessage("Evidence excluded and mastery history recomputed.");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusyAction(null);
    }
  };

  const resolveAlert = async (alertId: string, resolution: string) => {
    if (busyAction) return;
    if (!alertReason.trim()) {
      setErr("Enter a resolution reason before closing an alert.");
      return;
    }
    setBusyAction(`resolve:${alertId}`);
    setStatusMessage(null);
    try {
      const r = await fetch(apiUrl(`/api/tutor/alerts/${alertId}/resolve`), {
        method: "POST",
        headers: { "X-User-Id": userId, "Content-Type": "application/json" },
        body: JSON.stringify({ resolution, reason: alertReason }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(JSON.stringify(j));
      await load();
      setAlertReason("");
      setStatusMessage("Alert resolution recorded.");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusyAction(null);
    }
  };

  if (err && !data) return <div className="text-sm text-red-600 p-4" role="alert">Error: {err}<br/>Ensure API is running and job exists.</div>;
  if (!data) return <div className="text-sm text-gray-500 p-4" role="status">Loading {jobId}…</div>;

  return (
    <div className="space-y-4">
      <a href="/tutor" className="text-sm text-blue-600 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400">← All jobs</a>
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-gray-500">Tutor review ledger</p>
          <h1 className="text-xl font-semibold">Job {data.job.id}</h1>
        </div>
        <span className="text-sm px-3 py-1 rounded bg-white border">{data.job.status}</span>
      </div>
      <div className="flex items-center gap-2 text-sm">
        <label htmlFor="trace-tutor">Tutor</label>
        <select id="trace-tutor" value={userId} onChange={e => setUserId(e.target.value)} className="border rounded px-2 py-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400">
          <option value="TUT-SYNTH-ALPHA">TUT-SYNTH-ALPHA (assigned)</option>
          <option value="TUT-SYNTH-BRAVO">TUT-SYNTH-BRAVO (should 403)</option>
        </select>
        {err ? <span className="text-red-600" role="alert">{err}</span> : null}
      </div>
      {statusMessage ? <div className="rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800" role="status">{statusMessage}</div> : null}

      <section className="grid md:grid-cols-2 gap-4">
        <div className="border rounded bg-white p-3 space-y-2">
          <h2 className="font-medium">Job</h2>
          <dl className="text-sm space-y-1">
            <div className="flex justify-between"><dt className="text-gray-500">Type</dt><dd>{data.job.type}</dd></div>
            <div className="flex justify-between"><dt className="text-gray-500">Trigger</dt><dd>{data.job.input?.trigger ?? "—"}</dd></div>
            <div className="flex justify-between"><dt className="text-gray-500">Student</dt><dd>{data.job.student_id}</dd></div>
            <div className="flex justify-between"><dt className="text-gray-500">Subskill</dt><dd>{data.job.input?.subskill_id}</dd></div>
            <div className="flex justify-between"><dt className="text-gray-500">Centre</dt><dd>{data.job.centre_id}</dd></div>
            <div className="flex justify-between"><dt className="text-gray-500">Idempotency</dt><dd className="font-mono text-xs">{data.job.idempotency_key}</dd></div>
            <div className="flex justify-between"><dt className="text-gray-500">Retries</dt><dd>{data.job.retry_count}/{data.job.max_retries}</dd></div>
            <div className="flex justify-between"><dt className="text-gray-500">Created</dt><dd>{new Date(data.job.created_at).toLocaleString()}</dd></div>
          </dl>
          <details className="border rounded p-2">
            <summary className="text-sm font-medium cursor-pointer">Input snapshot</summary>
            <pre className="text-xs bg-gray-50 p-2 rounded mt-2 overflow-auto">{JSON.stringify(data.job.input, null, 2)}</pre>
          </details>
        </div>
        <div className="border rounded bg-white p-3 space-y-2">
          <h2 className="font-medium">Provenance</h2>
          <dl className="text-sm space-y-1">
            <div className="flex justify-between"><dt className="text-gray-500">Provider</dt><dd>{data.provenance?.provider ?? "—"}</dd></div>
            <div className="flex justify-between"><dt className="text-gray-500">Model</dt><dd>{data.provenance?.model_id ?? "—"}</dd></div>
            <div className="flex justify-between"><dt className="text-gray-500">Stop reason</dt><dd className="max-w-[200px] truncate" title={displayValue(data.provenance?.stop_reason)}>{displayValue(data.provenance?.stop_reason).slice(0,120)}</dd></div>
            <div><dt className="text-gray-500">Tools</dt><dd className="flex flex-wrap gap-1 mt-1">{(data.provenance?.tool_summary ?? []).map((t:string)=><span key={t} className="text-xs border rounded px-1.5 py-0.5 bg-gray-50">{t}</span>)}</dd></div>
          </dl>
        </div>
      </section>

      <section className="border rounded bg-white p-3">
        <h2 className="font-medium mb-2">Runs</h2>
        {data.runs.length === 0 ? <p className="text-sm text-gray-500">No runs yet — POST /run to execute.</p> : (
          <div className="space-y-2">
            {data.runs.map((r:any)=>(
              <div key={r.id} className="border rounded p-2 text-sm">
                <div className="flex justify-between"><span className="font-mono">{r.id} (attempt {r.attempt})</span><span className={`px-2 py-0.5 rounded text-xs ${r.status==="succeeded"?"bg-green-100":r.status==="needs_tutor_review"?"bg-yellow-100":"bg-gray-100"}`}>{r.status}</span></div>
                <div className="text-gray-600">{r.provider}/{r.model_id} • {r.duration_ms ?? "—"} ms {r.input_tokens!=null?`• in:${r.input_tokens} out:${r.output_tokens}`:""} {r.cost_usd!=null?`• $${r.cost_usd}`:""}</div>
                <div className="text-gray-600">Validation: {r.validation?.status ?? "not_run"}{r.validation?.reason ? ` — ${r.validation.reason}` : ""}{r.validation?.review_required ? " — review required" : ""}</div>
                {r.error ? <pre className="mt-1 bg-red-50 p-2 rounded text-xs overflow-auto">{JSON.stringify(r.error, null, 2)}</pre> : null}
                {r.output ? <pre className="mt-1 bg-green-50 p-2 rounded text-xs overflow-auto">{JSON.stringify(r.output, null, 2)}</pre> : null}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="border rounded bg-white p-3">
        <h2 className="font-medium mb-2">Tool calls (bounded, audited)</h2>
        {data.tool_calls.length === 0 ? <p className="text-sm text-gray-500">None</p> : (
          <div className="space-y-2">
            {data.tool_calls.map((tc:any,i:number)=>(
              <details key={i} className="border rounded p-2">
                <summary className="text-sm font-mono cursor-pointer">{tc.tool}</summary>
                <div className="grid md:grid-cols-2 gap-2 mt-2">
                  <div><div className="text-xs text-gray-500">Request</div><pre className="text-xs bg-gray-50 p-2 rounded overflow-auto">{JSON.stringify(tc.request, null, 2)}</pre></div>
                  <div><div className="text-xs text-gray-500">Response</div><pre className="text-xs bg-gray-50 p-2 rounded overflow-auto">{tc.response?JSON.stringify(tc.response,null,2):"—"}</pre></div>
                </div>
              </details>
            ))}
          </div>
        )}
      </section>

      <section className="border rounded bg-white p-3">
        <h2 className="font-medium mb-2">Artifacts & Evidence</h2>
        {data.artifacts.length === 0 ? <p className="text-sm text-gray-500">No artifact yet.</p> : data.artifacts.map((a:any)=>(
          <div key={a.id} className="border rounded p-2 mb-2">
            <div className="flex justify-between text-sm"><span className="font-mono">{a.id}</span><span>v{a.version} • {a.type}</span></div>
            <pre className="text-xs bg-gray-50 p-2 rounded mt-2 overflow-auto">{JSON.stringify(a.payload, null, 2)}</pre>
            {Array.isArray(a.payload?.evidence_ids) ? (
              <div className="mt-3 border-t pt-3">
                <h3 className="text-sm font-medium">Evidence decisions</h3>
                <p className="text-xs text-gray-500 mt-1">Exclude only evidence you can explain. The server will append a new mastery state; it will not rewrite the original.</p>
                <div className="mt-2 grid gap-2">
                  {a.payload.evidence_ids.map((evidenceId:string) => {
                    const excluded = (data.evidence_exclusions ?? []).some((item:any) => item.evidence_id === evidenceId);
                    const isBusy = busyAction === `exclude:${evidenceId}`;
                    return (
                      <div key={evidenceId} className="flex flex-wrap items-center justify-between gap-2 rounded border bg-gray-50 px-2 py-2 text-xs">
                        <code className="break-all">{evidenceId}</code>
                        {excluded ? <span className="rounded bg-gray-200 px-2 py-1 text-gray-600">Excluded with audit record</span> : (
                          <button
                            type="button"
                            onClick={() => excludeEvidence(evidenceId)}
                            disabled={busyAction !== null}
                            aria-busy={isBusy}
                            className="rounded border border-orange-300 px-2 py-1 text-orange-800 hover:bg-orange-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400 disabled:cursor-not-allowed disabled:opacity-50"
                          >{isBusy ? "Excluding…" : "Exclude evidence"}</button>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </div>
        ))}
        {data.alerts.length>0 ? (
          <div className="mt-4 border-t pt-3">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h3 className="text-sm font-medium">Tutor alerts</h3>
                <p className="text-xs text-gray-500 mt-1">Resolution closes the alert record only. The job remains reviewable until a safe, approved outcome exists.</p>
              </div>
              <label className="grid gap-1 text-xs text-gray-600" htmlFor="alert-reason">
                Resolution reason
                <input id="alert-reason" value={alertReason} onChange={e=>setAlertReason(e.target.value)} className="min-w-[16rem] border rounded px-2 py-1 text-sm text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400" placeholder="What did you review?" />
              </label>
            </div>
            {data.alerts.map((al:any)=> {
              const isBusy = busyAction === `resolve:${al.id}`;
              const resolution = al.type === "unsupported" ? "keep_blocked" : "collect_more_evidence";
              return (
                <div key={al.id} className={`text-sm border rounded p-3 mt-2 ${al.status === "resolved" ? "bg-gray-50" : "bg-yellow-50"}`} role={al.status === "open" ? "alert" : undefined}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">{al.type}</span>
                    <span className="rounded bg-white px-2 py-0.5 text-xs uppercase tracking-wide">{al.status}</span>
                  </div>
                  <p className="mt-1">{al.message}</p>
                  {al.status === "resolved" ? <p className="mt-1 text-xs text-gray-600">{al.resolution} — {al.resolution_reason} ({al.resolved_by})</p> : (
                    <button
                      type="button"
                      onClick={() => resolveAlert(al.id, resolution)}
                      disabled={busyAction !== null}
                      aria-busy={isBusy}
                      className="mt-2 rounded bg-teal-700 px-3 py-1.5 text-xs text-white hover:bg-teal-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400 disabled:cursor-not-allowed disabled:opacity-50"
                    >{isBusy ? "Saving…" : al.type === "unsupported" ? "Keep blocked and record review" : "Record review"}</button>
                  )}
                </div>
              );
            })}
          </div>
        ):null}
      </section>

      <section className="grid md:grid-cols-2 gap-4">
        <div className="border rounded bg-white p-3 space-y-2">
          <h2 className="font-medium">Effective mastery state</h2>
          {data.effective_mastery ? (
            <dl className="text-sm space-y-1">
              <div className="flex justify-between"><dt className="text-gray-500">Label</dt><dd>{data.effective_mastery.label}</dd></div>
              <div className="flex justify-between"><dt className="text-gray-500">Version</dt><dd>{data.effective_mastery.version}</dd></div>
              <div className="flex justify-between"><dt className="text-gray-500">Accuracy</dt><dd>{data.effective_mastery.accuracy}</dd></div>
              <div className="flex justify-between"><dt className="text-gray-500">Confidence</dt><dd>{data.effective_mastery.confidence}</dd></div>
              <div className="flex justify-between"><dt className="text-gray-500">Policy</dt><dd>{data.effective_mastery.policy_id} / {data.effective_mastery.policy_version}</dd></div>
              <div className="flex justify-between"><dt className="text-gray-500">Source</dt><dd>{data.effective_mastery.is_override ? "tutor override" : "deterministic"}</dd></div>
            </dl>
          ) : <p className="text-sm text-gray-500">No effective mastery state.</p>}
        </div>
        <div className="border rounded bg-white p-3 space-y-2">
          <h2 className="font-medium">Decision history</h2>
          {(data.decisions ?? []).length === 0 ? <p className="text-sm text-gray-500">No tutor decisions yet.</p> : (
            <div className="space-y-2">
              {data.decisions.map((decision:any) => (
                <div key={decision.id} className="border rounded p-2 text-sm">
                  <div className="flex justify-between"><span className="font-medium">{decision.action}</span><span className="text-gray-500">{new Date(decision.created_at).toLocaleString()}</span></div>
                  <div className="text-gray-600">{decision.actor_id} ({decision.actor_role}){decision.corrected_label ? ` • ${decision.corrected_label}` : ""}</div>
                  {decision.evidence_id ? <div className="text-xs text-gray-500 break-all">Evidence: {decision.evidence_id}</div> : null}
                  {decision.alert_id ? <div className="text-xs text-gray-500 break-all">Alert: {decision.alert_id}</div> : null}
                  {decision.reason ? <div className="text-gray-600">{decision.reason}</div> : null}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="grid md:grid-cols-2 gap-4">
        <div className="border rounded bg-white p-3 space-y-2">
          <h2 className="font-medium">Versioned corrections</h2>
          {(data.corrections ?? []).length === 0 ? <p className="text-sm text-gray-500">No tutor correction has been recorded.</p> : (
            <div className="space-y-2">
              {data.corrections.map((correction:any) => (
                <div key={correction.id} className="border-l-2 border-orange-400 pl-3 text-sm">
                  <div className="flex flex-wrap justify-between gap-2"><span className="font-medium">{correction.corrected_label}</span><span className="text-gray-500">v{correction.supersedes_version} → new state</span></div>
                  <p className="text-gray-600">By {correction.author_tutor_id} · {correction.reason}</p>
                  <p className="text-xs text-gray-500 break-all">Original state: {correction.original_state_id} · Proposal: {correction.artifact_id ?? "—"}</p>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="border rounded bg-white p-3 space-y-2">
          <h2 className="font-medium">Mastery history</h2>
          {(data.mastery_history ?? []).length === 0 ? <p className="text-sm text-gray-500">No mastery history is available for this job.</p> : (
            <ol className="space-y-2">
              {data.mastery_history.map((state:any) => (
                <li key={state.id} className="border rounded p-2 text-sm">
                  <div className="flex flex-wrap justify-between gap-2"><span className="font-medium">Version {state.version} · {state.label}</span><span className="text-gray-500">{state.is_override ? "tutor override" : "deterministic"}</span></div>
                  <div className="text-gray-600">{state.eligible_attempts} eligible · {state.correct_attempts} correct · {state.accuracy} accuracy · {state.confidence} confidence</div>
                </li>
              ))}
            </ol>
          )}
        </div>
      </section>

      <section className="border rounded bg-white p-3 space-y-3">
        <h2 className="font-medium">Tutor decision (persisted to effective workflow state)</h2>
        <div className="flex flex-col gap-2">
          <label className="grid gap-1 text-sm" htmlFor="decision-reason">
            Decision reason
            <input id="decision-reason" value={reason} onChange={e=>setReason(e.target.value)} placeholder="Explain the evidence review" className="border rounded px-2 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400"/>
          </label>
          <div className="flex items-center gap-2 text-sm">
            <label htmlFor="corrected-label">Corrected label (for Edit)</label>
            <select id="corrected-label" value={correctedLabel} onChange={e=>setCorrectedLabel(e.target.value)} className="border rounded px-2 py-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400">
              <option value="insufficient_evidence">insufficient_evidence</option>
              <option value="requires_support">requires_support</option>
              <option value="developing">developing</option>
              <option value="secure">secure</option>
            </select>
          </div>
          {!data.artifacts.length ? <p className="text-xs text-gray-600">No approved artifact exists for this job. Accept and Edit stay disabled; resolve the alert while keeping unsupported content blocked.</p> : null}
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={()=>decide("accept")} disabled={busyAction !== null || !data.artifacts.length} aria-busy={busyAction === "accept"} className="px-3 py-1.5 rounded bg-green-600 text-white text-sm hover:bg-green-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400 disabled:cursor-not-allowed disabled:opacity-50">{busyAction === "accept" ? "Accepting…" : "Accept"}</button>
            <button type="button" onClick={()=>decide("edit")} disabled={busyAction !== null || !data.artifacts.length} aria-busy={busyAction === "edit"} className="px-3 py-1.5 rounded bg-blue-600 text-white text-sm hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400 disabled:cursor-not-allowed disabled:opacity-50">{busyAction === "edit" ? "Saving…" : "Edit (override)"}</button>
            <button type="button" onClick={()=>decide("more_evidence")} disabled={busyAction !== null} aria-busy={busyAction === "more_evidence"} className="px-3 py-1.5 rounded bg-yellow-600 text-white text-sm hover:bg-yellow-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400 disabled:cursor-not-allowed disabled:opacity-50">{busyAction === "more_evidence" ? "Saving…" : "More evidence"}</button>
            <button type="button" onClick={()=>decide("reject")} disabled={busyAction !== null} aria-busy={busyAction === "reject"} className="px-3 py-1.5 rounded border border-red-300 text-red-700 text-sm hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-400 disabled:cursor-not-allowed disabled:opacity-50">{busyAction === "reject" ? "Rejecting…" : "Reject"}</button>
          </div>
          <p className="text-xs text-gray-500">Only the assigned tutor can act. Corrections, exclusions, alert resolutions, and approvals append audit records; raw chain-of-thought and out-of-scope student data are never exposed.</p>
        </div>
      </section>
    </div>
  );
}
