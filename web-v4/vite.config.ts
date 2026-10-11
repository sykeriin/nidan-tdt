import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: the FastAPI server (uvicorn server.app:app --port 8000) answers /api.
// Production: `npm run build` writes web/dist, which the same FastAPI app serves at /.
export default defineConfig({
  base: "/v4/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: { outDir: "dist", chunkSizeWarningLimit: 1600 },
});
