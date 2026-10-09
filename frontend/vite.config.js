import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // MapLibre 6 loads its worker relative to its own module; pre-bundling breaks that path.
  optimizeDeps: { exclude: ["maplibre-gl"] },
  worker: { format: "es" },
});
