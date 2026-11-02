/* The first connection's decisions, without a DOM.
 *
 * Which steps there are, which one an address opens on, what the account step
 * refuses before it asks the server, and what the summary says line by line.
 * Imports only `numbers.ts`, which imports nothing, and the schema's shapes
 * (`types.ts`), which `node --test` strips: it reads it as it stands (see
 * setup.test.ts).
 *
 * The sentences here are English, and they are the keys: the page hands each
 * to `t()` with its parameters, and `french.ts` holds the other language.
 */

import { count, type Counted } from "./numbers.ts"
import { explain, explainNeed, type Explained } from "./said.ts"
import type { Demo, Provider, SetupHealth, SetupState, Summary } from "./types.ts"

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
  state: SetupHealth
  /** What went wrong, as the server said it — untranslated. */
  said: string
  /** The same, recognised so that the page can say it in its own language. */
  notes: Explained[]
  /** The step of the first connection that changes it. */
  step: StepKey
  /** The section of the settings that changes it. */
  section: string
  /** The parameter drawn as a link, where it leads, and the ID it stands for. */
  link?: { param: string; url: string; title: string }
}

/** The steps this console still has: the account is gone once it is claimed. */
export function stepsFor(state: Pick<SetupState, "claimed">): StepKey[] {
  return STEPS.filter((step) => step !== "access" || !state.claimed)
}

/** The step an address asks for, if this console has it — else the first,
 * or the summary on an installation that has nothing left to do.
 *
 * The first is the language, the one step that needs nobody signed in: chosen
 * in this browser at once, and written with the account, or straight away
 * once there is one. */
export function stepFrom(
  state: Pick<SetupState, "claimed">,
  asked: string | null,
  summary: Summary | null = null
): StepKey {
  const steps = stepsFor(state)
  const found = steps.find((step) => step === asked)
  if (found) return found
  return summary && rows(summary).every((row) => row.state === "ok") ? "summary" : steps[0]
}

/** The lines of the summary each step answers for: the first ticket needs all
 * but the channels and the environment, the summary is every line. */
const STEP_ROWS: Partial<Record<StepKey, string[]>> = {
  provider: ["provider"],
  notion: ["board"],
  github: ["github"],
  project: ["projects"],
  channels: ["channels"],
  demo: ["machine", "provider", "model", "board", "github", "projects"],
}

const SEVERITY: SetupHealth[] = ["ok", "missing", "error"]

/** Where each step stands, by the worst of its lines — the language is always
 * chosen, and the account is no step any more once there is a summary. */
export function stepStates(summary: Summary): Partial<Record<StepKey, SetupHealth>> {
  const lines = rows(summary)
  const worst = (keys: string[]): SetupHealth =>
    lines
      .filter((line) => keys.includes(line.key))
      .reduce<SetupHealth>((held, line) => (SEVERITY.indexOf(line.state) > SEVERITY.indexOf(held) ? line.state : held), "ok")
  const states: Partial<Record<StepKey, SetupHealth>> = { language: "ok", summary: worst(lines.map((line) => line.key)) }
  for (const [step, keys] of Object.entries(STEP_ROWS)) states[step as StepKey] = worst(keys)
  return states
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

/** A Notion board by its name — never by its ID, which says nothing and leads nowhere. */
function notionBoard(name: string, tickets: number | null): Pick<Row, "value" | "params"> {
  if (tickets === null)
    return name
      ? { value: "Notion workspace “{{workspace}}”", params: { workspace: name } }
      : { value: "A Notion workspace", params: {} }
  return name
    ? withCount(
        count(tickets, "Notion workspace “{{workspace}}” — {{count}} ticket", "Notion workspace “{{workspace}}” — {{count}} tickets"),
        { workspace: name }
      )
    : withCount(count(tickets, "Notion workspace — {{count}} ticket", "Notion workspace — {{count}} tickets"), {})
}

/** What a line says of itself, if anything. */
function noted(said: string): Explained[] {
  return said ? [explain(said)] : []
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
        ? notionBoard(board.name, board.tickets)
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
      notes: lacking.flatMap(explainNeed),
      step: "summary",
      section: "update",
    },
    {
      key: "provider",
      label: "Claude provider",
      ...providerValue,
      state: provider.state,
      said: provider.said,
      notes: noted(provider.said),
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
      notes: noted(model.said),
      step: "summary",
      section: "models",
    },
    {
      key: "board",
      label: "Board",
      ...boardValue,
      state: board.state,
      said: board.said,
      notes: noted(board.said),
      step: "notion",
      section: board.storage === "markdown" ? "storage" : "notion",
      link:
        board.storage !== "markdown" && board.name && board.url
          ? { param: "workspace", url: board.url, title: board.workspace }
          : undefined,
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
      notes: noted(github.said),
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
      notes: [],
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
      notes: [],
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
      notes: [],
      step: "summary",
      section: "update",
    },
  ]
}
