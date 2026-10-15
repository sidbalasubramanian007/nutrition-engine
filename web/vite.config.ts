import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server on http://localhost:5173, the API's default ALLOWED_ORIGINS entry
export default defineConfig({
  plugins: [react()],
  server: { host: "localhost", port: 5173, strictPort: true },
});
