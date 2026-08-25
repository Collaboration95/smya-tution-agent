# SMYA Frontend — S1

Next.js 14 App Router, TypeScript, Tailwind.

```sh
cd frontend
npm install
npm run dev   # http://localhost:3000
npm run build # smoke test
```

`NEXT_PUBLIC_API_BASE` defaults to `http://localhost:8000`. The health page proxies via fetch; S1-06 adds tutor job trace at `/tutor/jobs/[id]`.
