"use client";
import { useEffect, useState } from "react";

type JobBrief = { id: string; type: string; status: string; student_id: string; input: any; created_at: string };

export default function TutorJobsPage() {
  const [jobs, setJobs] = useState<JobBrief[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [userId, setUserId] = useState("TUT-SYNTH-ALPHA");

  useEffect(() => {
    fetch(`http://localhost:8000/api/tutor/jobs`, { headers: { "X-User-Id": userId } })
      .then(r => r.json().then(j => ({ ok: r.ok, j })))
      .then(({ ok, j }) => {
        if (!ok) throw new Error(JSON.stringify(j));
        setJobs(j);
      })
      .catch(e => setErr(String(e)));
  }, [userId]);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Tutor — Diagnostic Jobs</h1>
      <div className="flex items-center gap-2 text-sm">
        <label>Tutor ID</label>
        <select value={userId} onChange={e => setUserId(e.target.value)} className="border rounded px-2 py-1">
          <option value="TUT-SYNTH-ALPHA">TUT-SYNTH-ALPHA (assigned)</option>
          <option value="TUT-SYNTH-BRAVO">TUT-SYNTH-BRAVO (unassigned)</option>
        </select>
        <span className="text-gray-500">Header X-User-Id is server-derived; centre/role not client-trusted.</span>
      </div>
      {err ? <p className="text-sm text-red-600">Error: {err}</p> : null}
      <div className="grid gap-3">
        {jobs.map(j => (
          <a key={j.id} href={`/tutor/jobs/${j.id}`} className="block border rounded bg-white p-3 hover:bg-gray-50">
            <div className="flex justify-between">
              <span className="font-medium">{j.id}</span>
              <span className={`text-sm px-2 py-0.5 rounded ${j.status === "succeeded" ? "bg-green-100" : j.status === "needs_tutor_review" ? "bg-yellow-100" : "bg-gray-100"}`}>{j.status}</span>
            </div>
            <div className="text-sm text-gray-600">Student: {j.student_id} • Subskill: {j.input?.subskill_id} • {new Date(j.created_at).toLocaleString()}</div>
          </a>
        ))}
        {jobs.length === 0 && !err ? <p className="text-sm text-gray-500">No jobs — trigger a diagnostic via API: POST /api/diagnostic/jobs?student_id=STU-SYNTH-A&subskill_id=FRC-ADD-SUB-UNLIKE</p> : null}
      </div>
      <details className="text-sm border rounded bg-white p-3">
        <summary className="font-medium cursor-pointer">How to demo</summary>
        <ol className="list-decimal pl-5 mt-2 space-y-1">
          <li>Ensure API is running and seeded: <code>python3 backend/scripts/seed.py</code></li>
          <li>Create a job: <code>curl -X POST "http://localhost:8000/api/diagnostic/jobs?student_id=STU-SYNTH-A&amp;subskill_id=FRC-ADD-SUB-UNLIKE" -H "X-User-Id: TUT-SYNTH-ALPHA"</code></li>
          <li>Run it: <code>curl -X POST http://localhost:8000/api/diagnostic/jobs/&#123;id&#125;/run -H "X-User-Id: TUT-SYNTH-ALPHA"</code></li>
          <li>Open its trace below — you will see job, runs, tool calls, artifact, and decision buttons.</li>
        </ol>
      </details>
    </div>
  );
}
