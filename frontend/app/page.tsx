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
    <div className="page-shell">
      <div className="hero-grid">
        <section className="surface-card hero-panel">
          <div className="eyebrow">SMYA / Slice 2</div>
          <h1 className="display-title" style={{ marginTop: "0.75rem" }}>Practice that remembers the next right step.</h1>
          <p>
            An evidence-led tuition workflow: approved questions are selected from a student&apos;s current state, reviewed by a tutor, and completed with deterministic feedback.
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", marginTop: "1.75rem" }}>
            <a href="/student" className="button button--primary">Open student practice</a>
            <a href="/tutor" className="button button--secondary">Open tutor workspace</a>
          </div>
        </section>
        <aside className="surface-card hero-note">
          <div>
            <div className="hero-note__mark" aria-hidden="true">↗</div>
            <div className="eyebrow" style={{ marginTop: "1rem" }}>The boundary</div>
            <p style={{ color: "var(--ink)", fontFamily: "Georgia, 'Times New Roman', serif", fontSize: "1.3rem", lineHeight: 1.25 }}>
              A draft can be saved. Only a tutor-approved draft can be assigned.
            </p>
          </div>
          <span className="muted" style={{ fontSize: "0.82rem" }}>Synthetic Northstar Centre · English</span>
        </aside>
      </div>

      <section className="feature-grid" aria-label="Workflow capabilities">
        <article className="surface-card surface-card--flat feature-card">
          <div className="eyebrow">01 / Select</div>
          <h2>State-specific practice</h2>
          <p>Needs-support learners receive scaffolded items; secure learners receive harder transfer work.</p>
        </article>
        <article className="surface-card surface-card--flat feature-card">
          <div className="eyebrow">02 / Review</div>
          <h2>Tutor in the loop</h2>
          <p>Source, difficulty, policy version, edits, approvals, and assignment state stay auditable.</p>
        </article>
        <article className="surface-card surface-card--flat feature-card">
          <div className="eyebrow">03 / Evidence</div>
          <h2>Feedback without a model</h2>
          <p>Objective answers are marked in code, hints are bounded, and completion records the next diagnostic event.</p>
        </article>
      </section>

      <section className="surface-card surface-card--flat" style={{ marginTop: "1.25rem", padding: "1.25rem" }} aria-live="polite">
        <div className="eyebrow">System pulse</div>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "1rem", marginTop: "0.55rem" }}>
          <strong>{health ? "Backend ready" : error ? "Backend unavailable" : "Checking backend"}</strong>
          <span className="muted" style={{ fontSize: "0.86rem" }}>{health ? `${health.env} · ${health.db} · ${health.model_provider}` : error ? "Start FastAPI to run the seeded workflow." : "Reserving a stable status region…"}</span>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem", marginTop: "0.85rem", fontSize: "0.85rem" }}>
          <a href={apiUrl("/docs")} className="button button--quiet">API docs ↗</a>
          <a href="/health" className="button button--quiet">Frontend health ↗</a>
        </div>
      </section>
    </div>
  );
}
