import { defineConfig, type Plugin } from "vite";

const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "connect-src 'self'",
  "font-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join("; ");

/** Inject the CSP only into the production page; the dev server needs inline styles and HMR. */
function cspPlugin(): Plugin {
  return {
    name: "cpf-csp",
    apply: "build",
    transformIndexHtml(html) {
      return html.replace("<!-- CSP -->", `<meta http-equiv="Content-Security-Policy" content="${CSP}" />`);
    },
  };
}

export default defineConfig({
  base: "./",
  plugins: [cspPlugin()],
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
  server: { port: 5173, strictPort: true },
});
