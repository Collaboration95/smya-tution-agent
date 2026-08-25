"use client";
import { useEffect, useState } from "react";
import { apiUrl } from "../lib/api";

type Health = { status: string; version: string; env: string; db: string; model_provider: string; model_id: string };

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fetch(apiUrl("/health")).then(r => r.json()).then(setHealth).catch(e => setError(String(e)));
  }, []);
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Website-first co-tutor — S1</h1>
      <p className="text-gray-600 max-w-2xl">
        Durable learning event → bounded diagnostic job → evidence-backed <code>MasteryProposal</code> → tutor review.
        Tailwind + Next.js frontend, FastAPI backend, Postgres (SQLite fallback), fake ModelClient.
      </p>
      <section className="rounded border bg-white p-4">
        <h2 className="font-medium mb-2">Backend health</h2>
        {health ? (
          <pre className="text-sm bg-gray-50 p-3 rounded overflow-auto">{JSON.stringify(health, null, 2)}</pre>
        ) : error ? (
          <p className="text-sm text-red-600">API is not reachable — {error} (run `uvicorn backend.app.main:app --reload`)</p>
        ) : (
          <p className="text-sm text-gray-500">Checking backend health …</p>
        )}
        <div className="mt-3 flex gap-3 text-sm">
          <a href={apiUrl("/docs")} className="text-blue-600 hover:underline">API docs</a>
          <a href={apiUrl("/health")} className="text-blue-600 hover:underline">/health JSON</a>
          <a href="/health" className="text-blue-600 hover:underline">Frontend /health page</a>
        </div>
      </section>
      <section className="rounded border bg-white p-4">
        <h2 className="font-medium mb-2">S1 scope (this branch)</h2>
        <ul className="list-disc pl-5 text-sm space-y-1 text-gray-700">
          <li>Tenant + role scope enforced server-side (S1-02/S1-03).</li>
          <li>Deterministic mastery policy separate from LLM language.</li>
          <li>AgentJob/AgentRun lifecycle with retries and fake ModelClient (S1-04).</li>
          <li>Diagnostic worker + MasteryProposal with evidence IDs (S1-05).</li>
          <li>Tutor trace & proposal review screen (S1-06).</li>
        </ul>
      </section>
    </div>
  );
}
