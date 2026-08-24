import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Pages serves the site from a repo subpath (https://user.github.io/mcpcheckup/), so the
// build needs to know that prefix or every asset URL 404s. It is an env var rather than a
// constant so the same bundle can be served from a domain root (VITE_BASE=/) when it lives
// on its own host -- which is exactly what the self-hosted deployment does.
export default defineConfig({
  base: process.env.VITE_BASE ?? "/",
  plugins: [react()],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
