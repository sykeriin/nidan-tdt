# Dashboard (React)

Vite + React + TypeScript. All numbers come from the FastAPI server (`server/`); nothing is computed here.

```bash
# backend, from the repo root
uvicorn server.app:app --port 8000

# dev: http://localhost:5173 (proxies /api to :8000)
cd web && npm install && npm run dev

# demo: build once, then the server serves it at http://localhost:8000/ (works offline)
npm run build

# after the API changes
python -m server.export_openapi
npx openapi-typescript ../docs/openapi.json -o src/api/schema.d.ts
```

- `src/twin3d/` is the three.js 3D transformer ported from the `powernext-pt2` branch (the model is `public/models/`).
- `src/lib/twinView.ts` places alerts on parts (port of `twin_view.py`); replay is client-side over the fetched run.
- Light theme, tokens in `src/styles/twin3d.css`. Green/yellow/red mean health state only.
