import { defineConfig, mergeConfig } from "vitest/config"

import vite from "./vite.config.ts"

/* The components, drawn and clicked one at a time, without a server.
 *
 * `npm test` is `node --test` over `src/lib/*.test.ts` and stays so: that logic
 * imports nothing and needs no DOM, and Node reads it as it is. What it cannot
 * reach is what a component draws from that logic — which file the bar
 * refuses, when its arrow lights up, which tab a ticket opens on. That is this
 * runner's: Vite's own resolution (`@/`, the CSS imports) in jsdom, with the
 * Testing Library's queries asking for what a reader sees — a role and the
 * English sentence that is its key, never the French it may be shown in.
 *
 * The suffix keeps the two apart: `.test.ts` is Node's, `.test.tsx` is this
 * one's. The end-to-end specs stay where they were, over a real `serve`.
 */
export default mergeConfig(
  vite,
  defineConfig({
    test: {
      environment: "jsdom",
      include: ["src/**/*.test.tsx"],
      setupFiles: ["src/test/setup.ts"],
      css: false,
    },
  })
)
