import { createHash } from "node:crypto"
import { copyFileSync, readFileSync } from "node:fs"
import path from "node:path"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { visualizer } from "rollup-plugin-visualizer"
import { defineConfig, searchForWorkspaceRoot, type Plugin } from "vite"

/* The console is served by Python, not by Node.
 *
 * `ponos serve` is `http.server` and the standard library, and that is
 * not going to change: a tool whose whole claim is "no dependency to install"
 * cannot ask for a Node runtime on the machine it runs on. So this build writes
 * straight into the package — `src/ponos/web/static` — and what it
 * writes is committed. Node is a thing *contributors* need; installing
 * ponos still needs python3 and git and nothing else.
 *
 * Everything is served under `/static/`, which is the one route the server
 * hands files from, so that is the base every asset URL is written against.
 *
 * The robot is not the console's own: it is `docs/mascot/`, the file the
 * landing page loads from a <script> tag, bundled here as it is — `@mascot` is
 * that directory, and the favicon in `index.html` is read from it too. One
 * drawing for both, and no copy to fall behind.
 */
const MASCOT = path.resolve(import.meta.dirname, "../docs/mascot")

/* The tokens go the other way: the console owns them, and the landing page
 * links a copy — `docs/` is published as it stands, with no build of its own
 * to import anything through. So every build writes that copy, and a copy
 * that no longer matches the source fails `tests/run.py`.
 */
function publishTokens(): Plugin {
  return {
    name: "publish-tokens",
    apply: "build",
    closeBundle() {
      copyFileSync(
        path.resolve(import.meta.dirname, "src/tokens.css"),
        path.resolve(import.meta.dirname, "../docs/tokens.css")
      )
    },
  }
}

/* The service worker is a template, and its version is what the build shipped.
 *
 * `pwa/sw.js` says `__BUILD__` where the deployment goes: a hash of the names
 * of the files the build wrote — which are themselves hashes of what they hold
 * — so two builds of the same sources write the same worker, and any change to
 * the console writes a different one. A worker that never changed would never
 * be reinstalled, and an installed app would stay on the build it was
 * installed with.
 */
function serviceWorker(): Plugin {
  return {
    name: "service-worker",
    apply: "build",
    generateBundle(_options, bundle) {
      const build = createHash("sha256")
        .update(Object.keys(bundle).sort().join("\n"))
        .digest("hex")
        .slice(0, 12)
      const template = readFileSync(path.resolve(import.meta.dirname, "pwa/sw.js"), "utf8")
      this.emitFile({
        type: "asset",
        fileName: "sw.js",
        source: template.replaceAll("__BUILD__", build),
      })
    },
  }
}

export default defineConfig({
  base: "/static/",
  plugins: [
    react(),
    tailwindcss(),
    publishTokens(),
    serviceWorker(),
    // `PONOS_BUNDLE_STATS=1 npm run build` draws what each chunk is made of in
    // `frontend/bundle-stats.html`: a chunk is named after its first module, and
    // the one called `i18n` turned out to be the packages every page shares.
    Boolean(process.env.PONOS_BUNDLE_STATS) && visualizer({ filename: "bundle-stats.html", gzipSize: true }),
  ],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "./src"), "@mascot": MASCOT },
  },
  build: {
    outDir: path.resolve(import.meta.dirname, "../src/ponos/web/static"),
    emptyOutDir: true,
    // Every name carries a hash of what it holds, so the server can tell a
    // browser to keep `assets/` for a year: a build that changes a file
    // changes its name, and `index.html` — the one file never cached — is what
    // points at the new one. An update is seen on the next load, nothing to
    // clear; a second load downloads nothing but that page.
    rollupOptions: {
      output: {
        // The entry is only the door: what it opens is `console`, below.
        entryFileNames: "assets/start-[hash].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/console-[hash].[ext]",
        // The libraries every page needs, apart from the console's own code:
        // one file of 800 kB became three, and a change to the console no
        // longer rewrites the part of the bundle that did not change. Only
        // what the first page loads anyway — the lazy Markdown editor stays
        // lazy, which a catch-all `node_modules` group would undo.
        //
        // The last three take what is left of the first load by its tag,
        // `$initial`, rather than by name. Since `i18n.ts` awaits the French
        // dictionary at its top, the console's own code came out in forty
        // pieces, each compressed on its own: put back together it is 13 kB
        // lighter gzipped. Stylesheets stay out of `views`, or the font's would
        // be a second `console-*.css`.
        codeSplitting: {
          groups: [
            { name: "react", test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/ },
            {
              name: "ui",
              test: /node_modules[\\/](@radix-ui|@floating-ui|lucide-react|sonner|date-fns|react-day-picker)[\\/]/,
            },
            { name: "router", tags: ["$initial"], test: /node_modules[\\/]@tanstack[\\/]/ },
            { name: "views", tags: ["$initial"], test: /node_modules[\\/].*\.[cm]?js$/ },
            { name: "console", tags: ["$initial"], test: /frontend[\\/]src[\\/]/ },
          ],
        },
      },
    },
  },
  server: {
    // The mascot sits outside this project, and the dev server serves nothing
    // outside it unless told to.
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), MASCOT] },
    // `npm run dev` gives hot reload against a console you started yourself:
    //   ponos serve      (127.0.0.1:8787, prints its token)
    //   npm run dev -- --open
    // The token rides on the cookie the real console set, so open the console
    // once on its own port first.
    proxy: {
      "/api": {
        target: process.env.PONOS_ORIGIN || "http://127.0.0.1:8787",
        changeOrigin: false,
      },
    },
  },
})
