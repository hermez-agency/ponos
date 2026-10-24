// First, before any resource is declared: the views need their router and
// their dialect in place by the time `createViewResource` runs.
import "./lib/resource-view"

import { StrictMode, Suspense, lazy } from "react"
import { createRoot } from "react-dom/client"

import App from "./App"
// The headings' face, bundled with the console (see `tokens.css`): no request
// to a font service. The text keeps the system's face.
import "@fontsource-variable/bricolage-grotesque/index.css"
import "./index.css"
import { startServiceWorker } from "./lib/service-worker"

startServiceWorker()

/* The server marks the page `data-setup` when what it serves is the first
 * connection rather than the console — see `web/server.py` and `setup.tsx`. */
const setup = Boolean(document.documentElement.dataset.setup)
/* And `data-missing` when the address is one the console does not have — see
 * `web/app.py` and `not-found.tsx`. */
const missing = document.documentElement.dataset.missing !== undefined

const NotFound = lazy(() =>
  import("./components/console/not-found").then((module) => ({ default: module.NotFound }))
)

/* A page seen once, kept out of the console's first load, which has a budget. */
const SetupApp = lazy(() =>
  import("./components/console/setup").then((module) => ({ default: module.SetupApp }))
)

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {missing ? (
      <Suspense fallback={null}>
        <NotFound />
      </Suspense>
    ) : setup ? (
      <Suspense fallback={null}>
        <SetupApp />
      </Suspense>
    ) : (
      <App />
    )}
  </StrictMode>
)
