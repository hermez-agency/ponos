import { existsSync } from "node:fs"
import { createServer } from "node:net"
import { defineConfig } from "@playwright/test"

/* The console in a browser, against a real `ponos serve`.
 *
 * `e2e/console.py` starts it on a board of Markdown files it writes itself, so
 * the tests need python3 with what the runner imports (`requirements.txt`) and
 * nothing of yours: the repository's `.venv` when `uv sync` has made one, the
 * `python3` on the PATH otherwise — the CI installs the requirements there. The browser is the Chrome
 * already on the machine — GitHub's runners have one too — rather than one
 * Playwright downloads: `npm ci` stays an install of packages, not of browsers.
 *
 * Three servers, not one. A console holds a single conversation with the
 * workspace, so a turn `chat.spec.ts` leaves running is a turn every other test
 * that opens the console walks into: Escape there stops it instead of closing
 * the drawer, and the chat test then reads "stopped by you" where its answer
 * should be. The chat gets a server of its own, its tests one after another;
 * the rest share the other one and run in parallel. The ideas share the chat's: what
 * they keep is written onto its board, and the others count the tickets of theirs.
 * The page of the ideas has one too: it turns an idea into a ticket of Website, which
 * the statistics of Website then count, and it counts the ideas the chat's batch adds. The sessions' tests have one as well: they hold the console's one open conversation, and a turn running there is a turn the ideas' scoring waits behind. And the first connection
 * gets a console nobody has claimed, which its test claims — once. And the tests that
delete projects get one of their own, with two projects to spare: the others count them —
 * and so do the tests that create some. And the series, which goes through a whole column
 * and so counts every card of it, gets one with a board of its own, its tests one after another.
 *
 * The ports are free ones unless `PONOS_E2E_PORT` names the first (the
 * chat takes the next, the first connection the one after, deleting the one after that, then the ideas, the sessions, and the series last): two worktrees running these tests at once must not both
 * ask for 8790. They are kept in the environment because Playwright reads this
 * file again in every worker, and a worker that drew its own would knock on a
 * port nobody serves.
 */
async function free(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer()
    server.once("error", reject)
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address() as { port: number }
      server.close(() => resolve(port))
    })
  })
}

if (!process.env.PONOS_E2E_CHAT_PORT) {
  const given = Number(process.env.PONOS_E2E_PORT) || 0
  process.env.PONOS_E2E_PORT = String(given || (await free()))
  process.env.PONOS_E2E_CHAT_PORT = String(given ? given + 1 : await free())
  process.env.PONOS_E2E_SETUP_PORT = String(given ? given + 2 : await free())
  process.env.PONOS_E2E_DELETE_PORT = String(given ? given + 3 : await free())
  process.env.PONOS_E2E_IDEAS_PORT = String(given ? given + 4 : await free())
  process.env.PONOS_E2E_SESSIONS_PORT = String(given ? given + 5 : await free())
  process.env.PONOS_E2E_SERIES_PORT = String(given ? given + 6 : await free())
}
const PORT = Number(process.env.PONOS_E2E_PORT)
const CHAT_PORT = Number(process.env.PONOS_E2E_CHAT_PORT)
const SETUP_PORT = Number(process.env.PONOS_E2E_SETUP_PORT)
const DELETE_PORT = Number(process.env.PONOS_E2E_DELETE_PORT)
const IDEAS_PORT = Number(process.env.PONOS_E2E_IDEAS_PORT)
const SESSIONS_PORT = Number(process.env.PONOS_E2E_SESSIONS_PORT)
const SERIES_PORT = Number(process.env.PONOS_E2E_SERIES_PORT)

const PYTHON = existsSync("../.venv/bin/python") ? "../.venv/bin/python" : "python3"

const serve = (port: number, mode = "") => ({
  command: `${PYTHON} e2e/console.py ${port} ${mode}`.trim(),
  url: `http://127.0.0.1:${port}/?token=e2e`,
  reuseExistingServer: false,
})

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  // One second chance on GitHub's runners, none here. Two cores share the
  // browsers, both servers and their outbox threads there, and a gesture that
  // waits on the stream (gestures.spec.ts, set aside then made ready again)
  // has missed its five seconds on a main that passed as a pull request the
  // minute before — never on a machine that could be watched doing it. A test
  // that fails twice still fails the job, and the list says which one needed
  // its second run.
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    channel: "chrome",
  },
  projects: [
    {
      name: "console",
      testIgnore: ["chat.spec.ts", "ideas.spec.ts", "ideas-page.spec.ts", "ideas-schedule.spec.ts", "sessions.spec.ts", "setup.spec.ts", "project-delete.spec.ts", "project-new.spec.ts", "goals.spec.ts", "series.spec.ts"],
      use: { baseURL: `http://127.0.0.1:${PORT}` },
    },
    {
      name: "chat",
      testMatch: ["chat.spec.ts", "ideas.spec.ts"],
      use: { baseURL: `http://127.0.0.1:${CHAT_PORT}` },
    },
    {
      name: "delete",
      testMatch: ["project-delete.spec.ts", "project-new.spec.ts", "goals.spec.ts"],
      // One board for files that delete projects and count them: side by side,
      // a deletion lands between the count before and the count after.
      workers: 1,
      use: { baseURL: `http://127.0.0.1:${DELETE_PORT}` },
    },
    {
      name: "ideas-page",
      testMatch: ["ideas-page.spec.ts", "ideas-schedule.spec.ts"],
      use: { baseURL: `http://127.0.0.1:${IDEAS_PORT}` },
    },
    {
      name: "sessions",
      testMatch: "sessions.spec.ts",
      use: { baseURL: `http://127.0.0.1:${SESSIONS_PORT}` },
    },
    {
      name: "series",
      testMatch: "series.spec.ts",
      fullyParallel: false,
      use: { baseURL: `http://127.0.0.1:${SERIES_PORT}` },
    },
    {
      name: "setup",
      testMatch: "setup.spec.ts",
      use: { baseURL: `http://127.0.0.1:${SETUP_PORT}` },
    },
  ],
  webServer: [serve(PORT), serve(CHAT_PORT), serve(SETUP_PORT, "unclaimed"), serve(DELETE_PORT, "doomed"), serve(IDEAS_PORT), serve(SESSIONS_PORT), serve(SERIES_PORT, "series")],
})
