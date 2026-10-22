/* The first connection's decisions, without a DOM.
 *
 * Which steps there are, which one an address opens on, what the account step
 * refuses before it asks the server, and what the summary says line by line.
 * Imports only `numbers.ts`, which imports nothing, so `node --test` reads it
 * as it stands (see setup.test.ts).
 *
 * The sentences here are English, and they are the keys: the page hands each
 * to `t()` with its parameters, and `french.ts` holds the other language.
 */

import { count, type Counted } from "./numbers.ts"

/** The steps, in the order somebody would say them — and the first ticket
 * last, since it is the proof that every step before it holds. */
export const STEPS = [
  "language",
  "access",
  "provider",
  "notion",
  "github",
  "project",
  "channels",
  "demo",
  "summary",
] as const
export type StepKey = (typeof STEPS)[number]

/** What the server says before a step is drawn — `GET /api/setup`. */
export interface SetupState {
  /** Somebody already said how this console is opened: the account step is done. */
  claimed: boolean
  signed_in: boolean
  /** The first connection comes from outside this machine and has to give the code. */
  code: boolean
  /** The console drew a code when it started — without one, outside is refused. */
  code_drawn: boolean
  container: boolean
  version: string
  storage: string
}

export type Health = "ok" | "missing" | "error"

export const PROVIDERS = ["cli", "api_key", "openrouter"] as const
export type Provider = (typeof PROVIDERS)[number]

/** What the installation amounts to — `GET /api/setup/summary`. */
export interface Summary {
  provider: {
    state: Health
    provider: Provider
    stated: string
    account: string
    key: string
    route_sessions: boolean
    said: string
  }
  model: { state: Health; model: string; auto: boolean; said: string }
  board: {
    state: Health
    storage: string
    workspace: string
    path: string
    tickets: number | null
    said: string
  }
  github: { state: Health; account: string; via: string; said: string; command: string; create_url?: string }
  projects: { state: Health; root: string; repositories: number; configured: number }
  channels: { state: Health; active: string[] }
  environment: { state: Health; container: boolean; version: string }
  /** git, Claude Code and its sign-in, the disk — what `doctor` checks under Tools. */
  machine: { state: Health; needs: Need[] }
}

/** One thing the machine needs, and the command that installs it when it is missing. */
export interface Need {
  name: string
  ok: boolean
  required: boolean
  said: string
  fix: string
}

/** What `GET /api/setup/notion` found shared with the integration. */
export interface Shared {
  ok: boolean
  said: string
  /** Notion said the token is not one of its own: the page says it, translated. */
  refused?: boolean
  /** The integration's name, as Notion shows it in the Connections menu. */
  name: string
  pages: { id: string; title: string; url: string }[]
  boards: { id: string; url: string }[]
}

/** Where the demonstration ticket stands — `GET /api/setup/demo`. */
export interface Demo {
  id: string
  title: string
  url: string
  column: string
  status: string
  progress: string
  running: boolean
  code: number | null
  said: string
}

/** The columns a ticket's run can end in, and what the page makes of each. */
export function demoOutcome(demo: Pick<Demo, "column" | "running" | "code">): "waiting" | "done" | "stuck" | "failed" {
  if (["review", "validated", "done"].includes(demo.column)) return "done"
  if (demo.column === "blocked") return "stuck"
  if (demo.column === "failed" || (demo.code !== null && demo.code !== 0)) return "failed"
  return "waiting"
}

/** One line of the summary: an English sentence and its parameters, a state, and where it is changed. */
export interface Row {
  key: string
  label: string
  value: string
  params: Record<string, string>
  state: Health
  /** What went wrong, as the server said it — untranslated. */
  said: string
  /** The step of the first connection that changes it. */
  step: StepKey
  /** The section of the settings that changes it. */
  section: string
}

/** The steps this console still has: the account is gone once it is claimed. */
export function stepsFor(state: Pick<SetupState, "claimed">): StepKey[] {
  return STEPS.filter((step) => step !== "access" || !state.claimed)
}

/** The step an address asks for, if this console has it — else the first.
 *
 * The first is the language, the one step that needs nobody signed in: chosen
 * in this browser at once, and written with the account, or straight away
 * once there is one. */
export function stepFrom(state: Pick<SetupState, "claimed">, asked: string | null): StepKey {
  const steps = stepsFor(state)
  return steps.find((step) => step === asked) ?? steps[0]
}

/** The step after this one, or this one when it is the last. */
export function nextStep(state: Pick<SetupState, "claimed">, step: StepKey): StepKey {
  const steps = stepsFor(state)
  return steps[Math.min(steps.indexOf(step) + 1, steps.length - 1)]
}

export const SHORTEST_PASSWORD = 8

/** What the account step refuses before asking — the server refuses the same. */
export function accessProblem(
  typed: { code: string; email: string; password: string; confirm: string },
  needsCode: boolean
): string {
  if (needsCode && typed.code.replace(/[^0-9a-z]/gi, "").length !== 8)
    return "The installation code is eight letters, printed in the console's logs."
  if (!typed.email.includes("@")) return "An email address is what the console will ask you for."
  if (typed.password.length < SHORTEST_PASSWORD) return "A password of 8 characters at the least."
  if (typed.password !== typed.confirm) return "The two passwords are not the same."
  return ""
}

const PROVIDER_NAMES: Record<Provider, string> = {
  cli: "Claude Code CLI (subscription)",
  api_key: "Anthropic API key",
  openrouter: "OpenRouter",
}

/** A row's sentence about a count, with the other things it names. */
function withCount(said: Counted, params: Record<string, string>): Pick<Row, "value" | "params"> {
  return { value: said.key, params: { ...params, ...said.params } }
}

/** The summary, one line per thing that has to work. */
export function rows(summary: Summary): Row[] {
  const { provider, model, board, github, projects, channels, environment, machine } = summary
  const name = PROVIDER_NAMES[provider.provider] ?? provider.provider
  const providerValue: Pick<Row, "value" | "params"> =
    provider.provider === "cli"
      ? provider.account
        ? { value: "{{name}} — signed in as {{account}}", params: { name, account: provider.account } }
        : { value: "{{name}} — not signed in", params: { name } }
      : provider.provider === "openrouter"
        ? {
            value: provider.route_sessions
              ? "{{name}} — {{key}}, sessions on OpenRouter"
              : "{{name}} — {{key}}, sessions still on the CLI",
            params: { name, key: provider.key || "—" },
          }
        : { value: "{{name}} — {{key}}", params: { name, key: provider.key || "—" } }

  const boardValue: Pick<Row, "value" | "params"> =
    board.storage === "markdown"
      ? { value: "Markdown board in {{path}}", params: { path: board.path } }
      : board.workspace
        ? board.tickets === null
          ? { value: "Notion workspace {{workspace}}", params: { workspace: board.workspace } }
          : withCount(
              count(
                board.tickets,
                "Notion workspace {{workspace}} — {{count}} ticket",
                "Notion workspace {{workspace}} — {{count}} tickets"
              ),
              { workspace: board.workspace }
            )
        : { value: "No board yet", params: {} }

  const lacking = machine.needs.filter((need) => !need.ok)
  return [
    {
      key: "machine",
      label: "This machine",
      value: lacking.length ? "Missing: {{names}}" : "git, Claude Code and room on the disk",
      params: { names: lacking.map((need) => need.name).join(", ") },
      state: machine.state,
      said: lacking.map((need) => (need.fix ? `${need.said} — ${need.fix}` : need.said)).join(" · "),
      step: "summary",
      section: "update",
    },
    {
      key: "provider",
      label: "Claude provider",
      ...providerValue,
      state: provider.state,
      said: provider.said,
      step: "provider",
      section: "claude",
    },
    {
      key: "model",
      label: "Default model",
      value: model.auto
        ? model.model
          ? "{{model}} by default, chosen per ticket by the rules"
          : "Chosen per ticket by the rules"
        : model.model
          ? "{{model}} for every ticket"
          : "The CLI's default model for every ticket",
      params: { model: model.model },
      state: model.state,
      said: model.said,
      step: "summary",
      section: "models",
    },
    {
      key: "board",
      label: "Board",
      ...boardValue,
      state: board.state,
      said: board.said,
      step: "notion",
      section: board.storage === "markdown" ? "storage" : "notion",
    },
    {
      key: "github",
      label: "GitHub account",
      value: github.account
        ? github.via === "GH_TOKEN"
          ? "{{account}} (GH_TOKEN)"
          : github.via === "token"
          ? "{{account}} (token)"
          : "{{account}}"
        : "Not signed in",
      params: { account: github.account },
      state: github.state,
      said: github.said,
      step: "github",
      section: "github",
    },
    {
      key: "projects",
      label: "Projects",
      ...withCount(
        count(
          projects.repositories,
          "{{root}} — {{count}} repository found",
          "{{root}} — {{count}} repositories found"
        ),
        { root: projects.root }
      ),
      state: projects.state,
      said: "",
      step: "summary",
      section: "projects",
    },
    {
      key: "channels",
      label: "Channels",
      value: channels.active.length ? "{{names}}" : "None — nothing reaches your phone",
      params: { names: channels.active.map((one) => one[0].toUpperCase() + one.slice(1)).join(", ") },
      state: channels.state,
      said: "",
      step: "channels",
      section: "notify",
    },
    {
      key: "environment",
      label: "Environment",
      value: environment.container ? "Container — Ponos {{version}}" : "Machine — Ponos {{version}}",
      params: { version: environment.version },
      state: environment.state,
      said: "",
      step: "summary",
      section: "update",
    },
  ]
}
