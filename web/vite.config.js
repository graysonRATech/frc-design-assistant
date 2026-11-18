import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The same Content-Security-Policy CloudFront serves (infra/student_access.py), so `npm run preview`
// catches anything the policy would block in production.
const CSP =
  "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; " +
  "connect-src 'self' http://localhost:* https://*.execute-api.us-east-1.amazonaws.com https://*.lambda-url.us-east-1.on.aws https://*.amazoncognito.com; " +
  "frame-ancestors 'none'; base-uri 'none'; form-action 'self'";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, modulePreload: { polyfill: false }, chunkSizeWarningLimit: 2000 },
  preview: { headers: { "Content-Security-Policy": CSP } },
});
