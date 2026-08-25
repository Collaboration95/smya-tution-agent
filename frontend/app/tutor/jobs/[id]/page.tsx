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

  const load = useCallback(() => {
    fetch(apiUrl(`/api/tutor/jobs/${jobId}`), { headers: { "X-User-Id": userId }, cache: "no-store" })
      .then(r => r.json().then(j => ({ ok: r.ok, j })))
      .then(({ ok, j }) => {
        if (!ok) throw new Error(JSON.stringify(j));
        setData(j);
        setErr(null);
      })
      .catch(e => setErr(String(e)));
  }, [jobId, userId]);
  useEffect(() => { load(); }, [load]);

  const decide = async (action: string) => {
    const qs = new URLSearchParams({ action, reason });
    if (action === "edit") qs.set("corrected_label", correctedLabel);
    const r = await fetch(`${apiUrl(`/api/tutor/jobs/${jobId}/decision`)}?${qs.toString()}`, { method: "POST", headers: { "X-User-Id": userId } });
    const j = await r.json();
    if (!r.ok) { setErr(JSON.stringify(j)); return; }
    load();
  };

  if (err && !data) return <div className="text-sm text-red-600 p-4">Error: {err}<br/>Ensure API is running and job exists.</div>;
  if (!data) return <div className="text-sm text-gray-500 p-4">Loading {jobId}…</div>;

  return (
    <div className="space-y-4">
      <a href="/tutor" className="text-sm text-blue-600 hover:underline">← All jobs</a>
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Job {data.job.id}</h1>
        <span className="text-sm px-3 py-1 rounded bg-white border">{data.job.status}</span>
      </div>
      <div className="flex items-center gap-2 text-sm">
        <label>Tutor</label>
        <select value={userId} onChange={e => setUserId(e.target.value)} className="border rounded px-2 py-1">
          <option value="TUT-SYNTH-ALPHA">TUT-SYNTH-ALPHA (assigned)</option>
          <option value="TUT-SYNTH-BRAVO">TUT-SYNTH-BRAVO (should 403)</option>
        </select>
        {err ? <span className="text-red-600">{err}</span> : null}
      </div>

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
          </div>
        ))}
        {data.alerts.length>0 ? (
          <div className="mt-3">
            <h3 className="text-sm font-medium">Alerts</h3>
            {data.alerts.map((al:any)=> <div key={al.id} className="text-sm border rounded p-2 bg-yellow-50 mt-1">{al.type}: {al.message}</div>)}
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
                  {decision.reason ? <div className="text-gray-600">{decision.reason}</div> : null}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="border rounded bg-white p-3 space-y-3">
        <h2 className="font-medium">Tutor decision (persisted to effective workflow state)</h2>
        <div className="flex flex-col gap-2">
          <input value={reason} onChange={e=>setReason(e.target.value)} placeholder="Reason for decision (optional)" className="border rounded px-2 py-1 text-sm"/>
          <div className="flex items-center gap-2 text-sm">
            <label>Corrected label (for Edit)</label>
            <select value={correctedLabel} onChange={e=>setCorrectedLabel(e.target.value)} className="border rounded px-2 py-1">
              <option value="insufficient_evidence">insufficient_evidence</option>
              <option value="requires_support">requires_support</option>
              <option value="developing">developing</option>
              <option value="secure">secure</option>
            </select>
          </div>
          <div className="flex flex-wrap gap-2">
            <button onClick={()=>decide("accept")} className="px-3 py-1.5 rounded bg-green-600 text-white text-sm hover:bg-green-700">Accept</button>
            <button onClick={()=>decide("edit")} className="px-3 py-1.5 rounded bg-blue-600 text-white text-sm hover:bg-blue-700">Edit (override)</button>
            <button onClick={()=>decide("more_evidence")} className="px-3 py-1.5 rounded bg-yellow-600 text-white text-sm hover:bg-yellow-700">More evidence</button>
            <button onClick={()=>decide("reject")} className="px-3 py-1.5 rounded bg-red-600 text-white text-sm hover:bg-red-700">Reject</button>
          </div>
          <p className="text-xs text-gray-500">Actions are scoped: only assigned tutor can act; decision is audited and visible in mastery history. Raw chain-of-thought and out-of-scope student data are never exposed.</p>
        </div>
      </section>
    </div>
  );
}
