export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").replace(/\/$/, "");
export function apiUrl(path: string) {
  return `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function getHealth() {
  const r = await fetch(apiUrl("/health"), { cache: "no-store" });
  if (!r.ok) throw new Error(`health ${r.status}`);
  return r.json();
}
