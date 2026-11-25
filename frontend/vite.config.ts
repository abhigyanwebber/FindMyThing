import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Tests must never run against React's production build (it has no `act`) or with production `import.meta.env`
// semantics. Some shells export NODE_ENV=production globally, and Vitest keeps an inherited value, so force it here.
if (process.env["VITEST"] !== undefined) {
  process.env["NODE_ENV"] = "test";
}

// The dev server origin must equal the backend's FRONTEND_ORIGIN (backend/.env.example: http://localhost:5173),
// because CORS and the CSRF/Origin check accept exactly one origin. strictPort fails loudly instead of drifting.
export default defineConfig({
  plugins: [react()],
  server: { host: "localhost", port: 5173, strictPort: true },
  preview: { host: "localhost", port: 4173, strictPort: true },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
