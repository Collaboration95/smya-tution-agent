"use client";
import { useEffect, useState } from "react";
import { apiUrl } from "../../lib/api";
export default function HealthPage() {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { fetch(apiUrl("/health")).then(r=>r.json()).then(setData).catch(e=>setErr(String(e))); }, []);
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Frontend → Backend health</h1>
      {data ? <pre className="text-sm bg-white border rounded p-3 overflow-auto">{JSON.stringify(data, null, 2)}</pre> : err ? <p className="text-red-600 text-sm">{err}</p> : <p className="text-sm text-gray-500">Loading…</p>}
      <p className="text-sm text-gray-600">If this fails, ensure the API is running on port 8000.</p>
    </div>
  );
}
