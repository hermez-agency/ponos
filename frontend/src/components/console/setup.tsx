import * as React from "react"
import {
  ArrowRight,
  Bell,
  Bot,
  Check,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  Copy,
  ExternalLink,
  FolderGit2,
  GitPullRequest,
  HardDrive,
  KeyRound,
  Languages,
  ListChecks,
  LoaderCircle,
  NotebookText,
  Play,
  RefreshCw,
  Route,
  Stethoscope,
  Terminal,
} from "lucide-react"

import { ConnectGithub } from "@/components/console/github-page"
import { Rich } from "@/components/console/text"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, why, type Provisioned } from "@/lib/api"
import { LANGUAGES, setLanguage, useLanguage, useT, type Language } from "@/lib/i18n"
import {
  accessProblem,
  demoOutcome,
  nextStep,
  rows,
  stepFrom,
  stepsFor,
  type Demo,
  type Health,
  type Provider,
  type Row,
  type SetupState,
  type Shared,
  type StepKey,
  type Summary,
} from "@/lib/setup"
import { cn } from "@/lib/utils"

/* The first connection, in steps.
 *
 * Drawn instead of the console when the server marks the page `data-setup`
 * (see `main.tsx`): on a console nobody has claimed, to anybody — the bundle is
 * no secret, and what it asks first is the code, the email and the password —
 * and on `/setup` to somebody already in, which is where a console claimed from
 * the environment lands until it has a board.
 *
 * One write per step, each through the endpoint that checks it: a key is tried
 * against its provider before it is written, a board is built the way `ponos
 * init` builds it. Every step after the account can be left for later — the
 * summary at the end says what is missing, and the Settings page says it again.
 */

const ICONS: Record<StepKey, React.ComponentType<{ className?: string }>> = {
  language: Languages,
  access: KeyRound,
  provider: Bot,
  notion: NotebookText,
  github: GitPullRequest,
  project: FolderGit2,
  channels: Bell,
  demo: Play,
  summary: ListChecks,
}

const TITLES: Record<StepKey, string> = {
  language: "Language",
  access: "Access",
  provider: "Claude provider",
  notion: "Notion",
  github: "GitHub",
  project: "First project",
  channels: "Channels",
  demo: "First ticket",
  summary: "Summary",
}

/** The address carries the step, so a reload — or a link — lands on it. */
function askedStep(): string | null {
  return new URLSearchParams(window.location.search).get("step")
}

function remember(step: StepKey) {
  // `/setup`, whatever the page was opened as: an unclaimed console draws this
  // at any address, and once it is claimed only `/setup` still does.
  const url = new URL("/setup", window.location.href)
  url.searchParams.set("step", step)
  window.history.replaceState(null, "", url)
}

export function SetupApp() {
  const t = useT()
  const [state, setState] = React.useState<SetupState | null>(null)
  const [failed, setFailed] = React.useState("")
  const [step, setStep] = React.useState<StepKey>("access")

  const load = React.useCallback(async () => {
    try {
      const read = await api.setupState()
      if (!read) {
        // Neither unclaimed nor signed in: the door is the server's to draw.
        window.location.assign("/")
        return
      }
      setState(read)
      setStep((current) => (read.claimed && current === "access" ? stepFrom(read, null) : current))
    } catch (error) {
      setFailed(why(error))
    }
  }, [])

  React.useEffect(() => {
    void api.setupState().then(
      (read) => {
        if (!read) {
          window.location.assign("/")
          return
        }
        setState(read)
        setStep(stepFrom(read, askedStep()))
      },
      (error) => setFailed(why(error))
    )
  }, [])

  React.useEffect(() => {
    document.title = `${t("First connection")} · Ponos`
  }, [t])

  const go = (next: StepKey) => {
    remember(next)
    setStep(next)
    window.scrollTo({ top: 0 })
  }

  if (failed)
    return (
      <Shell>
        <Alert variant="destructive">
          <AlertDescription>{failed}</AlertDescription>
        </Alert>
      </Shell>
    )
  if (!state)
    return (
      <Shell>
        <p className="text-muted-foreground text-sm">{t("Reading the configuration…")}</p>
      </Shell>
    )

  const steps = stepsFor(state)
  const forward = () => go(nextStep(state, step))

  return (
    <Shell>
      <Stepper steps={steps} current={step} reachable={state.claimed} onStep={go} />
      <div data-testid={`setup-${step}`}>
        {step === "language" ? (
          <LanguageStep claimed={state.claimed} onNext={forward} />
        ) : step === "access" ? (
          <AccessStep
            state={state}
            onClaimed={async () => {
              await load()
              go("provider")
            }}
          />
        ) : step === "provider" ? (
          <ProviderStep container={state.container} onNext={forward} />
        ) : step === "notion" ? (
          <NotionStep storage={state.storage} onNext={forward} />
        ) : step === "github" ? (
          <GithubStep container={state.container} onNext={forward} />
        ) : step === "project" ? (
          <ProjectStep onNext={forward} />
        ) : step === "channels" ? (
          <ChannelsStep container={state.container} onNext={forward} />
        ) : step === "demo" ? (
          <DemoStep onNext={forward} onStep={go} />
        ) : (
          <SummaryStep onStep={go} />
        )}
      </div>
    </Shell>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  const t = useT()
  return (
    <main className="bg-background text-foreground min-h-svh px-4 py-10">
      <div className="mx-auto w-full max-w-3xl">
        <header className="mb-6">
          <p className="text-muted-foreground font-mono text-xs tracking-wide uppercase">Ponos</p>
          <h1 className="text-2xl leading-tight font-bold tracking-[-0.03em] sm:text-[1.75rem]">
            {t("First connection")}
          </h1>
        </header>
        {children}
      </div>
    </main>
  )
}

function Stepper({
  steps,
  current,
  reachable,
  onStep,
}: {
  steps: StepKey[]
  current: StepKey
  reachable: boolean
  onStep: (step: StepKey) => void
}) {
  const t = useT()
  const at = steps.indexOf(current)
  return (
    <ol className="mb-6 flex flex-wrap gap-1.5" aria-label={t("Steps")}>
      {steps.map((step, index) => {
        const Icon = ICONS[step]
        const here = step === current
        return (
          <li key={step}>
            <button
              type="button"
              disabled={!reachable}
              aria-current={here ? "step" : undefined}
              onClick={() => (here ? undefined : onStep(step))}
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                here
                  ? "bg-primary text-primary-foreground border-primary"
                  : index < at
                    ? "text-foreground hover:bg-muted"
                    : "text-muted-foreground hover:bg-muted",
                "disabled:cursor-default"
              )}
            >
              <span className="tabular-nums">{index + 1}</span>
              <Icon className="size-3.5" />
              {t(TITLES[step])}
            </button>
          </li>
        )
      })}
    </ol>
  )
}

function StepCard({
  title,
  blurb,
  children,
  footer,
}: {
  title: string
  blurb: string
  children: React.ReactNode
  footer?: React.ReactNode
}) {
  return (
    <Card className="gap-5">
      <CardHeader>
        <CardTitle className="text-lg">{title}</CardTitle>
        <CardDescription className="leading-relaxed">
          <Rich text={blurb} />
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">{children}</CardContent>
      {footer ? <div className="flex flex-wrap justify-end gap-2 px-6">{footer}</div> : null}
    </Card>
  )
}

function Field({
  id,
  label,
  hint,
  ...props
}: { id: string; label: string; hint?: string } & React.ComponentProps<typeof Input>) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} name={id} autoComplete="off" spellCheck={false} {...props} />
      {hint ? (
        <p className="text-muted-foreground text-xs leading-relaxed">
          <Rich text={hint} />
        </p>
      ) : null}
    </div>
  )
}

/** A sentence that went well or did not, said where the gesture was made. */
function Said({ ok, text }: { ok: boolean; text: string }) {
  if (!text) return null
  return (
    <Alert variant={ok ? "success" : "destructive"} role="status">
      {ok ? <CircleCheck /> : <CircleAlert />}
      <AlertDescription>
        <Rich text={text} />
      </AlertDescription>
    </Alert>
  )
}

/** A command to type somewhere else, with the button that copies it. */
function Command({ text }: { text: string }) {
  const t = useT()
  const [copied, setCopied] = React.useState(false)
  return (
    <div className="bg-muted flex items-center gap-2 rounded-lg border px-3 py-2">
      <Terminal className="text-muted-foreground size-4 shrink-0" />
      <code className="min-w-0 flex-1 font-mono text-sm break-all">{text}</code>
      <Button
        type="button"
        size="xs"
        variant="ghost"
        onClick={() => {
          void navigator.clipboard?.writeText(text).then(() => setCopied(true))
        }}
        aria-label={t("Copy")}
      >
        {copied ? <Check /> : <Copy />}
      </Button>
    </div>
  )
}

/** What a step that built something did, one line each. */
function Report({ done }: { done: Provisioned | null }) {
  if (!done) return null
  return (
    <>
      {done.steps.length ? (
        <ul className="text-muted-foreground list-disc pl-5 text-xs leading-relaxed">
          {done.steps.map(([verb, what], index) => (
            <li key={index}>
              <span className="text-tr-green font-medium">{verb}</span> {what}
            </li>
          ))}
        </ul>
      ) : null}
      {done.problem ? <Said ok={false} text={done.problem} /> : null}
    </>
  )
}

/* -- 0. the language -------------------------------------------------------- */

/** The language, first: every step after it is read in it.
 *
 * Taken in this browser the moment it is clicked, like the picker of the
 * settings; and written to the file as the language of the reports and of the
 * console — at once when somebody is signed in, with the account otherwise. */
function LanguageStep({ claimed, onNext }: { claimed: boolean; onNext: () => void }) {
  const t = useT()
  const language = useLanguage()
  const [problem, setProblem] = React.useState("")

  const choose = async (code: Language) => {
    setLanguage(code)
    setProblem("")
    if (!claimed) return
    try {
      await api.saveSettings({ settings: { "runner.language": code, "runner.app_language": code } })
    } catch (error) {
      setProblem(why(error))
    }
  }

  return (
    <StepCard
      title={t("Which language")}
      blurb={t(
        "The console's, and the one Ponos writes its reports in. Both can be changed later in the settings."
      )}
      footer={
        <Button type="button" onClick={onNext}>
          {t("Continue")}
          <ArrowRight />
        </Button>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label={t("Language")}>
        {LANGUAGES.map((item) => (
          <button
            key={item.code}
            type="button"
            role="radio"
            aria-checked={language === item.code}
            data-testid={`language-${item.code}`}
            onClick={() => void choose(item.code)}
            className={cn(
              "flex items-center gap-3 rounded-xl border p-4 text-left text-base font-semibold transition-colors",
              language === item.code
                ? "border-primary ring-primary/30 bg-primary/5 ring-2"
                : "hover:bg-muted/60"
            )}
          >
            <span aria-hidden className="text-2xl">
              {item.flag}
            </span>
            {item.name}
            {language === item.code ? <CircleCheck className="text-primary ml-auto size-4" /> : null}
          </button>
        ))}
      </div>
      <Said ok={false} text={problem} />
    </StepCard>
  )
}

/* -- 1. access -------------------------------------------------------------- */

function AccessStep({ state, onClaimed }: { state: SetupState; onClaimed: () => Promise<void> }) {
  const t = useT()
  const language = useLanguage()
  const [typed, setTyped] = React.useState({ code: "", email: "", password: "", confirm: "" })
  const [problem, setProblem] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const set = (key: keyof typeof typed) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setTyped({ ...typed, [key]: event.target.value })

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const refused = accessProblem(typed, state.code)
    if (refused) {
      setProblem(t(refused))
      return
    }
    setBusy(true)
    setProblem("")
    try {
      await api.claim({ ...typed, language })
      await onClaimed()
    } catch (error) {
      setProblem(why(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      <StepCard
        title={t("Who opens this console")}
        blurb={t(
          "Nobody has claimed this console yet. The email and the password typed here are what it asks for from now on — and what closes this page behind you."
        )}
        footer={
          <Button type="submit" disabled={busy || (state.code && !state.code_drawn)}>
            {busy ? t("Claiming…") : t("Claim the console")}
            <ArrowRight />
          </Button>
        }
      >
        {state.code ? (
          state.code_drawn ? (
            <Field
              id="code"
              label={t("Installation code")}
              hint={t(
                "Printed by the console when it started — in a container, its logs (`docker compose logs ponos`, or the Logs tab in Dokploy). It is asked because this page is reached from outside the machine."
              )}
              value={typed.code}
              onChange={set("code")}
              placeholder="XXXX-XXXX"
              autoFocus
            />
          ) : (
            <Said
              ok={false}
              text={t(
                "This console is reached from outside its machine and was started without an installation code: restart it, and read the code in its logs."
              )}
            />
          )
        ) : null}
        <Field
          id="email"
          label={t("Email")}
          type="email"
          autoComplete="username"
          value={typed.email}
          onChange={set("email")}
          autoFocus={!state.code}
        />
        <Field
          id="password"
          label={t("Password")}
          type="password"
          autoComplete="new-password"
          value={typed.password}
          onChange={set("password")}
          hint={t(
            "8 characters at the least: behind this console sits a runner that runs code on its machine."
          )}
        />
        <Field
          id="confirm"
          label={t("The same password again")}
          type="password"
          autoComplete="new-password"
          value={typed.confirm}
          onChange={set("confirm")}
        />
        <Said ok={false} text={problem} />
      </StepCard>
    </form>
  )
}

/* -- 2. the provider -------------------------------------------------------- */

const CHOICES: { key: Provider; title: string; lines: string[] }[] = [
  {
    key: "cli",
    title: "Claude Code CLI",
    lines: [
      "Your Claude subscription, signed in with `claude auth login`.",
      "The only one that keeps Claude in Chrome and waits for credits when the window runs out.",
      "In a container, the command is typed once in its terminal.",
    ],
  },
  {
    key: "api_key",
    title: "Anthropic API key",
    lines: [
      "A key from console.anthropic.com, billed by the token.",
      "Nothing to sign in, nothing to wait for — and no Claude in Chrome.",
    ],
  },
  {
    key: "openrouter",
    title: "OpenRouter",
    lines: [
      "One key for every provider, billed by OpenRouter.",
      "Models are then named as OpenRouter slugs (`anthropic/claude-sonnet-4.5`, `openai/gpt-5`).",
      "No Claude in Chrome, nothing to wait for.",
    ],
  },
]

function ProviderStep({ container, onNext }: { container: boolean; onNext: () => void }) {
  const t = useT()
  const [chosen, setChosen] = React.useState<Provider | null>(null)
  const [key, setKey] = React.useState("")
  const [routed, setRouted] = React.useState(true)
  const [busy, setBusy] = React.useState(false)
  const [said, setSaid] = React.useState<{ ok: boolean; text: string } | null>(null)
  const [command, setCommand] = React.useState("")

  React.useEffect(() => {
    // What the file already says, so coming back to the step shows it chosen.
    void api.summary().then(
      (summary) => {
        if (summary.provider.stated) setChosen(summary.provider.provider)
        setRouted(summary.provider.provider !== "openrouter" || summary.provider.route_sessions)
      },
      () => undefined
    )
  }, [])

  const save = async (provider: Provider) => {
    setBusy(true)
    setSaid(null)
    try {
      const answer = await api.saveProvider({
        provider,
        key: key.trim(),
        route_sessions: provider === "openrouter" ? routed : undefined,
      })
      setCommand(answer.command ?? "")
      setSaid({
        ok: answer.ok,
        text: answer.ok
          ? t("Written to the configuration: {{said}}", { said: answer.said })
          : answer.said,
      })
      if (answer.ok) setKey("")
    } catch (error) {
      setSaid({ ok: false, text: why(error) })
    } finally {
      setBusy(false)
    }
  }

  const checkLogin = async () => {
    setBusy(true)
    try {
      const answer = await api.claudeLogin()
      setCommand(answer.command)
      setSaid({
        ok: answer.ok,
        text: answer.ok ? t("Claude Code is signed in as {{who}}.", { who: answer.said }) : answer.said,
      })
    } catch (error) {
      setSaid({ ok: false, text: why(error) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <StepCard
      title={t("Who answers the sessions")}
      blurb={t(
        "The choice that matters most: it decides who bills the work, which models a ticket can name, and whether a ticket can use the browser. It can be changed later in the settings."
      )}
      footer={
        <Button type="button" variant="outline" onClick={onNext}>
          {t("Continue")}
          <ArrowRight />
        </Button>
      }
    >
      <div className="grid gap-3 sm:grid-cols-3" role="radiogroup" aria-label={t("Claude provider")}>
        {CHOICES.map((choice) => (
          <button
            key={choice.key}
            type="button"
            role="radio"
            aria-checked={chosen === choice.key}
            data-testid={`provider-${choice.key}`}
            onClick={() => {
              setChosen(choice.key)
              setSaid(null)
              setKey("")
            }}
            className={cn(
              "flex flex-col gap-2 rounded-xl border p-4 text-left transition-colors",
              chosen === choice.key
                ? "border-primary ring-primary/30 bg-primary/5 ring-2"
                : "hover:bg-muted/60"
            )}
          >
            <span className="flex items-center justify-between gap-2 font-semibold">
              {t(choice.title)}
              {chosen === choice.key ? <CircleCheck className="text-primary size-4" /> : null}
            </span>
            <ul className="text-muted-foreground flex flex-col gap-1 text-xs leading-relaxed">
              {choice.lines.map((line) => (
                <li key={line}>
                  <Rich text={t(line)} />
                </li>
              ))}
            </ul>
          </button>
        ))}
      </div>

      {chosen === "cli" ? (
        <div className="flex flex-col gap-3">
          <p className="text-muted-foreground text-sm leading-relaxed">
            <Rich
              text={
                container
                  ? t(
                      "Open a terminal in the container — Dokploy's Terminal tab on the service, or `docker compose exec ponos bash` — and sign in there. The sign-in is kept in the `~/.claude` volume."
                    )
                  : t("In a terminal on this machine, sign Claude Code in:")
              }
            />
          </p>
          <Command text={command || "claude auth login"} />
          <div className="flex flex-wrap gap-2">
            <Button type="button" disabled={busy} onClick={() => void save("cli")}>
              {t("Use the CLI")}
            </Button>
            <Button type="button" variant="outline" disabled={busy} onClick={() => void checkLogin()}>
              <RefreshCw />
              {t("Check the sign-in")}
            </Button>
          </div>
        </div>
      ) : chosen === "api_key" || chosen === "openrouter" ? (
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            void save(chosen)
          }}
        >
          <Field
            id="provider-key"
            label={chosen === "api_key" ? t("Anthropic API key") : t("OpenRouter key")}
            type="password"
            placeholder={chosen === "api_key" ? "sk-ant-…" : "sk-or-…"}
            value={key}
            onChange={(event) => setKey(event.target.value)}
            hint={t(
              "Left empty, the key already in the configuration — or in the container's environment — is the one checked."
            )}
          />
          {chosen === "openrouter" ? (
            <label className="flex items-start gap-2 text-sm">
              <Checkbox
                checked={routed}
                onCheckedChange={(value) => setRouted(value === true)}
                className="mt-0.5"
              />
              <span>
                <span className="font-medium">{t("Run the sessions on OpenRouter")}</span>
                <span className="text-muted-foreground block text-xs leading-relaxed">
                  {t(
                    "Off, the key is only handed to the sessions, and they keep running on the CLI's sign-in."
                  )}
                </span>
              </span>
            </label>
          ) : null}
          <div>
            <Button type="submit" disabled={busy}>
              {busy ? t("Checking…") : t("Check and save")}
            </Button>
          </div>
        </form>
      ) : null}

      {said ? <Said ok={said.ok} text={said.text} /> : null}
    </StepCard>
  )
}

/* -- 3. notion -------------------------------------------------------------- */

function NotionStep({ storage, onNext }: { storage: string; onNext: () => void }) {
  const t = useT()
  const [board, setBoard] = React.useState<Summary["board"] | null>(null)
  const [token, setToken] = React.useState("")
  const [shared, setShared] = React.useState<Shared | null>(null)
  const [page, setPage] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [done, setDone] = React.useState<Provisioned | null>(null)
  const [problem, setProblem] = React.useState("")

  React.useEffect(() => {
    if (storage === "markdown") return
    void api.summary().then(
      (summary) => setBoard(summary.board),
      () => undefined
    )
    // A token already written — a step left half-way, a reload — is asked again.
    void api.sharedWithNotion("").then(
      (answer) => answer.ok && setShared(answer),
      () => undefined
    )
  }, [storage])

  const found = board?.state === "ok"
  const waiting = Boolean(shared?.ok && !found && !shared.pages.length && !shared.boards.length)

  // Nothing shared yet: somebody is in Notion adding the integration to a page,
  // and the page appears here on its own as soon as they have.
  React.useEffect(() => {
    if (!waiting) return
    const timer = window.setInterval(() => {
      if (document.visibilityState === "hidden") return
      void api.sharedWithNotion("").then(
        (answer) => answer.ok && setShared(answer),
        () => undefined
      )
    }, 4000)
    return () => window.clearInterval(timer)
  }, [waiting])

  const check = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setProblem("")
    try {
      const answer = await api.sharedWithNotion(token.trim())
      setShared(answer)
      if (answer.ok) setToken("")
    } catch (error) {
      setProblem(why(error))
    } finally {
      setBusy(false)
    }
  }

  const build = async (chosen: { page?: string; workspace?: string }) => {
    setBusy(true)
    setProblem("")
    setDone(null)
    try {
      const answer = await api.saveNotion({ token: "", page: chosen.page ?? "", workspace: chosen.workspace })
      setDone(answer)
      setBoard(answer.board)
    } catch (error) {
      setProblem(why(error))
    } finally {
      setBusy(false)
    }
  }

  const footer = (
    <Button type="button" variant={found ? "default" : "outline"} onClick={onNext}>
      {t("Continue")}
      <ArrowRight />
    </Button>
  )

  if (storage === "markdown")
    return (
      <StepCard
        title={t("The board")}
        blurb={t("This console keeps its board in Markdown files: there is nothing to connect.")}
        footer={footer}
      >
        {board?.path ? <Command text={board.path} /> : null}
      </StepCard>
    )

  return (
    <StepCard
      title={t("The board, in Notion")}
      blurb={t(
        "Three gestures in Notion, and Ponos does the rest: it builds the Tickets and Projects databases itself, with every column spelled the way it reads them — there is no template to duplicate."
      )}
      footer={footer}
    >
      {/* Only once there is one: before, what is missing is what the three
          gestures below are about, and the configuration's own words for it
          would only alarm somebody who has not started yet. */}
      {found ? (
        <Said ok text={t("A board is connected: {{count}} ticket(s) on it.", { count: String(board.tickets ?? 0) })} />
      ) : board?.state === "error" ? (
        <Said ok={false} text={board.said} />
      ) : null}

      <section className="flex flex-col gap-3" aria-labelledby="notion-one">
        <h3 id="notion-one" className="text-sm font-semibold">
          {t("1. Create the Ponos integration")}
        </h3>
        <ol className="text-muted-foreground list-decimal pl-5 text-sm leading-relaxed">
          <li>{t("Open Notion's integrations page, and click “New integration”.")}</li>
          <li>{t("Name it “Ponos”, choose your workspace, type “Internal”, and save.")}</li>
          <li>
            <Rich text={t("Under Capabilities, tick “Read comments” and “Insert comments”, then copy the “Internal Integration Secret”.")} />
          </li>
        </ol>
        <div>
          <Button asChild variant="outline" size="sm">
            <a href="https://www.notion.so/profile/integrations" target="_blank" rel="noreferrer">
              {t("Open Notion's integrations")}
              <ExternalLink />
            </a>
          </Button>
        </div>
        <form className="flex flex-col gap-3" onSubmit={(event) => void check(event)}>
          <Field
            id="notion-token"
            label={t("Integration secret")}
            type="password"
            placeholder="ntn_…"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            hint={shared?.ok ? t("Already saved — paste another one only to replace it.") : undefined}
          />
          <div>
            <Button type="submit" disabled={busy || !token.trim()}>
              {busy ? t("Checking…") : t("Check the token")}
            </Button>
          </div>
        </form>
        {shared ? (
          <Said
            ok={shared.ok}
            text={
              shared.ok
                ? t("Notion knows this token: it is the integration “{{name}}”.", { name: shared.name || "Ponos" })
                : shared.refused
                  ? t("Notion refused this token: copy the “Internal Integration Secret” again, from Notion's integrations page.")
                  : shared.said
            }
          />
        ) : null}
      </section>

      {shared?.ok ? (
        <section className="flex flex-col gap-3" aria-labelledby="notion-two">
          <h3 id="notion-two" className="text-sm font-semibold">
            {t("2. Add Ponos to your Notion page")}
          </h3>
          <div className="grid items-start gap-4 sm:grid-cols-[1fr_17rem]">
            <ol className="text-muted-foreground list-decimal pl-5 text-sm leading-relaxed">
              <li>{t("In Notion, open the page the board should live under — or create an empty one, “Ponos” for instance.")}</li>
              <li>
                <Rich text={t("Click `···` at the top right of the page, then “Connections”.")} />
              </li>
              <li>{t("Search for “{{name}}”, pick it, and confirm.", { name: shared.name || "Ponos" })}</li>
              <li>{t("Come back here: the page appears below on its own.")}</li>
            </ol>
            <NotionShareIllustration name={shared.name || "Ponos"} />
          </div>
          <div>
            <Button asChild variant="outline" size="sm">
              <a href="https://www.notion.so" target="_blank" rel="noreferrer">
                {t("Open Notion")}
                <ExternalLink />
              </a>
            </Button>
          </div>
        </section>
      ) : null}

      {shared?.ok ? (
        <section className="flex flex-col gap-3" aria-labelledby="notion-three" data-testid="notion-shared">
          <h3 id="notion-three" className="text-sm font-semibold">
            {t("3. Choose where the board goes")}
          </h3>
          {waiting ? (
            <p className="text-muted-foreground flex items-center gap-2 text-sm" role="status">
              <LoaderCircle className="size-4 animate-spin" />
              {t("Waiting for a page shared with “{{name}}”…", { name: shared.name || "Ponos" })}
            </p>
          ) : null}
          {shared.boards.map((one) => (
            <div key={one.id} className="flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm">
              <NotebookText className="text-muted-foreground size-4" />
              <span className="flex-1">{t("A Ponos board is already there.")}</span>
              <Button type="button" size="sm" disabled={busy || found} onClick={() => void build({ workspace: one.id })}>
                {t("Use this board")}
              </Button>
            </div>
          ))}
          {shared.pages.length ? (
            <div className="flex flex-col gap-2" role="radiogroup" aria-label={t("Pages shared with the integration")}>
              {shared.pages.map((one) => (
                <label
                  key={one.id}
                  className={cn(
                    "flex cursor-pointer items-center gap-3 rounded-lg border p-3 text-sm",
                    page === one.id ? "border-primary bg-primary/5" : "hover:bg-muted/60"
                  )}
                >
                  <input
                    type="radio"
                    name="notion-page"
                    value={one.id}
                    checked={page === one.id}
                    onChange={() => setPage(one.id)}
                    className="accent-primary"
                  />
                  <span className="flex-1 font-medium">{one.title || t("(untitled page)")}</span>
                </label>
              ))}
              <div>
                <Button type="button" disabled={busy || !page} onClick={() => void build({ page })}>
                  {busy ? t("Building the board…") : t("Build the board under this page")}
                </Button>
              </div>
            </div>
          ) : null}
          <Report done={done} />
        </section>
      ) : null}
      <Said ok={false} text={problem} />
    </StepCard>
  )
}

/** What Notion's own menu looks like at the moment it matters — drawn rather
 * than photographed, so that it speaks the page's language and stays true
 * whatever the workspace is called. */
function NotionShareIllustration({ name }: { name: string }) {
  const t = useT()
  return (
    <figure className="bg-muted/40 rounded-xl border p-3 text-xs" aria-label={t("Notion's page menu, Connections open")}>
      <div className="mb-2 flex items-center justify-end gap-2 text-[0.7rem]">
        <span className="text-muted-foreground">{t("Share")}</span>
        <span className="text-muted-foreground">☆</span>
        <span className="ring-primary rounded px-1.5 font-bold ring-2">···</span>
      </div>
      <div className="bg-background ml-auto w-56 rounded-lg border shadow-sm">
        <div className="text-muted-foreground border-b px-3 py-1.5">{t("Copy link")}</div>
        <div className="bg-primary/10 text-foreground flex items-center justify-between px-3 py-1.5 font-semibold">
          {t("Connections")}
          <span>›</span>
        </div>
        <div className="border-t p-2">
          <div className="text-muted-foreground mb-1.5 rounded border px-2 py-1">{t("Search for connections…")}</div>
          <div className="bg-primary/10 ring-primary flex items-center gap-2 rounded px-2 py-1 font-medium ring-1">
            <span aria-hidden>🤖</span>
            {name}
          </div>
        </div>
      </div>
      <figcaption className="text-muted-foreground mt-2 text-center">
        <Rich text={t("`···` → Connections → {{name}}", { name })} />
      </figcaption>
    </figure>
  )
}

/* -- 4. github -------------------------------------------------------------- */

function GithubStep({ container, onNext }: { container: boolean; onNext: () => void }) {
  const t = useT()
  const [github, setGithub] = React.useState<Summary["github"] | null>(null)
  const [busy, setBusy] = React.useState(false)

  const check = React.useCallback(async () => {
    setBusy(true)
    try {
      setGithub(await api.github())
    } catch (error) {
      setGithub({ state: "error", account: "", via: "", said: why(error), command: "" })
    } finally {
      setBusy(false)
    }
  }, [])

  React.useEffect(() => {
    void check()
  }, [check])

  return (
    <StepCard
      title={t("GitHub, for the pull requests")}
      blurb={t(
        "A code ticket comes back as a pull request. Connect GitHub in one click: Ponos creates its own GitHub App and you choose the repositories it reaches. Without it, `gh` is used — signed in with `gh auth login`, or given a token in `GH_TOKEN`, the way a container usually is."
      )}
      footer={
        <>
          <Button type="button" variant="outline" disabled={busy} onClick={() => void check()}>
            <RefreshCw />
            {t("Check again")}
          </Button>
          <Button type="button" variant="outline" onClick={onNext}>
            {t("Continue")}
            <ArrowRight />
          </Button>
        </>
      }
    >
      {github?.via !== "app" ? <ConnectGithub /> : null}
      {github ? (
        github.account ? (
          <Said
            ok
            text={
              github.via === "app"
                ? t("Pull requests are opened as {{account}}, through the GitHub App.", {
                    account: github.account,
                  })
                : github.via === "GH_TOKEN"
                ? t("Pull requests are opened as {{account}}, with the token in `GH_TOKEN`.", {
                    account: github.account,
                  })
                : t("Pull requests are opened as {{account}}.", { account: github.account })
            }
          />
        ) : (
          <>
            <Said ok={false} text={github.said || t("gh is not signed in.")} />
            <p className="text-muted-foreground text-sm leading-relaxed">
              {t("Or, without the app:")}{" "}
              <Rich
                text={
                  container
                    ? t(
                        "Set `GH_TOKEN` in the service's environment and redeploy — or sign in from its terminal:"
                      )
                    : t("In a terminal on this machine:")
                }
              />
            </p>
            <Command text={github.command || "gh auth login"} />
          </>
        )
      ) : (
        <p className="text-muted-foreground text-sm">{t("Asking gh…")}</p>
      )}
    </StepCard>
  )
}

/* -- 5. the first project --------------------------------------------------- */

type Choices = Awaited<ReturnType<typeof api.setupProjects>>

/** Where a demonstration ticket and every ticket after it are filed. */
const PROJECT_KEY = "ponos-setup-project"

function ProjectStep({ onNext }: { onNext: () => void }) {
  const t = useT()
  const [choices, setChoices] = React.useState<Choices | null>(null)
  const [failed, setFailed] = React.useState("")
  const [name, setName] = React.useState("")
  const [repository, setRepository] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [made, setMade] = React.useState("")
  const [problem, setProblem] = React.useState("")

  const read = React.useCallback(() => {
    void api.setupProjects().then(setChoices, (error) => setFailed(why(error)))
  }, [])
  React.useEffect(read, [read])

  const create = async (values: Record<string, unknown>) => {
    setBusy(true)
    setProblem("")
    try {
      const written = await api.createProject(values)
      window.localStorage.setItem(PROJECT_KEY, written.id)
      setMade(written.name)
      setName("")
      setRepository("")
      // Added here rather than read again: the board's list of projects is
      // cached for a while, and would not have it yet.
      setChoices((held) =>
        held ? { ...held, projects: [...held.projects, { id: written.id, name: written.name }] } : held
      )
    } catch (error) {
      setProblem(why(error))
    } finally {
      setBusy(false)
    }
  }

  const known = choices?.projects ?? []
  return (
    <StepCard
      title={t("A first project")}
      blurb={t(
        "A ticket belongs to a project: the repository a code ticket works in, or simply a theme for writing. Pick a repository this machine already has, name one on GitHub — it is cloned at the first ticket —, or start with a project without code."
      )}
      footer={
        <Button type="button" variant={known.length ? "default" : "outline"} onClick={onNext}>
          {t("Continue")}
          <ArrowRight />
        </Button>
      }
    >
      {failed ? <Said ok={false} text={failed} /> : null}
      {!choices && !failed ? <p className="text-muted-foreground text-sm">{t("Looking for repositories…")}</p> : null}
      {made ? <Said ok text={t("The project “{{name}}” is created.", { name: made })} /> : null}
      {known.length ? (
        <p className="text-sm" data-testid="setup-projects-known">
          {t("Projects on the board: {{names}}", { names: known.map((one) => one.name).join(", ") })}
        </p>
      ) : null}

      {choices?.repositories.length ? (
        <section className="flex flex-col gap-2" aria-labelledby="project-found">
          <h3 id="project-found" className="text-sm font-semibold">
            {t("Repositories found in {{root}}", { root: choices.root })}
          </h3>
          {choices.repositories.slice(0, 12).map((one) => {
            const taken = known.some((project) => project.name.toLowerCase() === one.name.toLowerCase())
            return (
              <div key={one.path} className="flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm">
                <FolderGit2 className="text-muted-foreground size-4" />
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{one.name}</span>
                  <span className="text-muted-foreground block truncate text-xs">{one.remote || one.path}</span>
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy || taken}
                  onClick={() => void create({ name: one.name, kind: "code", path: one.path })}
                >
                  {taken ? t("Already a project") : t("Make it a project")}
                </Button>
              </div>
            )
          })}
        </section>
      ) : choices ? (
        <p className="text-muted-foreground text-sm">
          <Rich text={t("No repository in `{{root}}` yet — the folder where Ponos keeps them.", { root: choices.root })} />
        </p>
      ) : null}

      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          void create({ name: name.trim(), kind: repository.trim() ? "code" : "document", repository: repository.trim() })
        }}
      >
        <h3 className="text-sm font-semibold">{t("Or a new one")}</h3>
        <Field id="project-name" label={t("Project name")} value={name} onChange={(event) => setName(event.target.value)} />
        <Field
          id="project-repository"
          label={t("GitHub repository (optional)")}
          placeholder="https://github.com/owner/repository"
          value={repository}
          onChange={(event) => setRepository(event.target.value)}
          hint={t("Left empty, the project has no code: its tickets are written answers and documents.")}
        />
        <div>
          <Button type="submit" disabled={busy || !name.trim()}>
            {t("Create the project")}
          </Button>
        </div>
      </form>
      <Said ok={false} text={problem} />
    </StepCard>
  )
}

/* -- 7. the first ticket ---------------------------------------------------- */

/** The demonstration ticket being played, so that a reload finds it again. */
const DEMO_KEY = "ponos-setup-demo"

function DemoStep({ onNext, onStep }: { onNext: () => void; onStep: (step: StepKey) => void }) {
  const t = useT()
  const language = useLanguage()
  const [id, setId] = React.useState(() => window.localStorage.getItem(DEMO_KEY) ?? "")
  const [demo, setDemo] = React.useState<Demo | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [problem, setProblem] = React.useState("")

  const outcome = demo ? demoOutcome(demo) : null

  React.useEffect(() => {
    if (!id || (outcome && outcome !== "waiting")) return
    let live = true
    const ask = () =>
      api.demo(id).then(
        (read) => live && setDemo(read),
        (error) => {
          if (!live) return
          // A ticket deleted since, or a board changed: start over.
          window.localStorage.removeItem(DEMO_KEY)
          setId("")
          setProblem(why(error))
        }
      )
    void ask()
    const timer = window.setInterval(() => void ask(), 3000)
    return () => {
      live = false
      window.clearInterval(timer)
    }
  }, [id, outcome])

  const start = async () => {
    setBusy(true)
    setProblem("")
    setDemo(null)
    try {
      const project = window.localStorage.getItem(PROJECT_KEY) ?? ""
      const made = await api.startDemo({ project, language })
      window.localStorage.setItem(DEMO_KEY, made.id)
      setId(made.id)
    } catch (error) {
      setProblem(why(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <StepCard
      title={t("A first ticket, played now")}
      blurb={t(
        "The proof that everything holds: Ponos writes a short ticket on your board and runs it at once — Claude reads it, answers, and the answer lands on the ticket. It takes a minute or two."
      )}
      footer={
        <Button type="button" variant={outcome === "done" ? "default" : "outline"} onClick={onNext}>
          {t("Continue")}
          <ArrowRight />
        </Button>
      }
    >
      {!id ? (
        <div>
          <Button type="button" disabled={busy} onClick={() => void start()} data-testid="demo-start">
            <Play />
            {busy ? t("Writing the ticket…") : t("Create and play the demonstration ticket")}
          </Button>
        </div>
      ) : null}
      {id && !demo ? <p className="text-muted-foreground text-sm">{t("Reading the board…")}</p> : null}
      {demo ? (
        <div className="flex flex-col gap-3" data-testid="demo-state" data-outcome={outcome ?? ""}>
          <div className="flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm">
            {outcome === "waiting" ? (
              <LoaderCircle className="text-primary size-4 animate-spin" />
            ) : outcome === "done" ? (
              <CircleCheck className="text-tr-green size-4" />
            ) : (
              <CircleAlert className="text-destructive size-4" />
            )}
            <span className="min-w-0 flex-1">
              <span className="font-medium">{demo.title}</span>
              <span className="text-muted-foreground block text-xs">
                {demo.status || t("no status")}
                {demo.progress ? ` — ${demo.progress}` : ""}
              </span>
            </span>
            {demo.url ? (
              <Button asChild size="sm" variant="outline">
                <a href={demo.url} target="_blank" rel="noreferrer">
                  {t("Open the ticket")}
                  <ExternalLink />
                </a>
              </Button>
            ) : null}
          </div>
          {outcome === "done" ? (
            <Said ok text={t("It works: the ticket ran, and its answer is on the ticket. Ponos is ready.")} />
          ) : outcome === "stuck" ? (
            <Said ok={false} text={t("The ticket stopped on a question — open it to read what it needs.")} />
          ) : outcome === "failed" ? (
            <>
              <Said
                ok={false}
                text={t("The ticket did not run. What it said is below; the summary and its full diagnosis say which part is missing.")}
              />
              {demo.said ? (
                <pre className="bg-muted max-h-64 overflow-auto rounded-lg border p-3 font-mono text-xs whitespace-pre-wrap">
                  {demo.said}
                </pre>
              ) : null}
            </>
          ) : (
            <p className="text-muted-foreground text-sm" role="status">
              {demo.running ? t("Claude is working on it…") : t("Waiting for the run to start…")}
            </p>
          )}
          {outcome && outcome !== "waiting" && outcome !== "done" ? (
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" onClick={() => onStep("summary")}>
                <Stethoscope />
                {t("See what is missing")}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  window.localStorage.removeItem(DEMO_KEY)
                  setId("")
                  setDemo(null)
                }}
              >
                <RefreshCw />
                {t("Try again")}
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
      <Said ok={false} text={problem} />
    </StepCard>
  )
}

/* -- 6. channels ------------------------------------------------------------ */

function ChannelsStep({ container, onNext }: { container: boolean; onNext: () => void }) {
  const t = useT()
  const [typed, setTyped] = React.useState({
    telegram_token: "",
    telegram_chat: "",
    slack_token: "",
    slack_channel: "",
  })
  const [busy, setBusy] = React.useState(false)
  const [done, setDone] = React.useState<
    (Provisioned & { channels: { name: string; ok: boolean; said: string }[] }) | null
  >(null)
  const [problem, setProblem] = React.useState("")
  const set = (key: keyof typeof typed) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setTyped({ ...typed, [key]: event.target.value })

  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setProblem("")
    try {
      const answer = await api.saveChannels(typed)
      setDone(answer)
      if (!answer.problem)
        setTyped({ telegram_token: "", telegram_chat: "", slack_token: "", slack_channel: "" })
    } catch (error) {
      setProblem(why(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={(event) => void save(event)}>
      <StepCard
        title={t("Being told, and answering")}
        blurb={
          container
            ? t(
                "Optional — but on a server, the only way to hear about a blocked ticket: no desktop notification reaches you from a container. A question asked there is answered in the chat, and the answer lands on the ticket."
              )
            : t(
                "Optional. A blocked ticket asks its question there, and what you answer lands on the ticket."
              )
        }
        footer={
          <Button type="button" variant="outline" onClick={onNext}>
            {t("Continue")}
            <ArrowRight />
          </Button>
        }
      >
        <fieldset className="flex flex-col gap-3">
          <legend className="mb-1 text-sm font-semibold">Telegram</legend>
          <Field
            id="telegram-token"
            label={t("Bot token")}
            type="password"
            value={typed.telegram_token}
            onChange={set("telegram_token")}
            hint={t(
              "@BotFather → `/newbot`, then say anything to your new bot: the chat id is read back from it."
            )}
          />
          <Field
            id="telegram-chat"
            label={t("Chat id")}
            value={typed.telegram_chat}
            onChange={set("telegram_chat")}
            hint={t("Found on its own — leave it empty unless you know it.")}
          />
        </fieldset>
        <fieldset className="flex flex-col gap-3">
          <legend className="mb-1 text-sm font-semibold">Slack</legend>
          <Field
            id="slack-token"
            label={t("Slack bot token")}
            type="password"
            placeholder="xoxb-…"
            value={typed.slack_token}
            onChange={set("slack_token")}
          />
          <Field
            id="slack-channel"
            label={t("Slack channel ID")}
            value={typed.slack_channel}
            onChange={set("slack_channel")}
            hint={t("Then `/invite @your-bot` in the channel — the step everyone forgets.")}
          />
        </fieldset>
        <div>
          <Button type="submit" disabled={busy || !Object.values(typed).some((value) => value.trim())}>
            {busy ? t("Checking…") : t("Save and check")}
          </Button>
        </div>
        <Report done={done} />
        {done?.channels.map((channel) => (
          <Said key={channel.name} ok={channel.ok} text={`${channel.name} — ${channel.said}`} />
        ))}
        <Said ok={false} text={problem} />
      </StepCard>
    </form>
  )
}

/* -- 8. the summary --------------------------------------------------------- */

function SummaryStep({ onStep }: { onStep: (step: StepKey) => void }) {
  const t = useT()
  return (
    <StepCard
      title={t("What this console runs on")}
      blurb={t(
        "One line per thing that has to work. A line that is missing can be fixed from its step now, or later from the settings — this summary is at the top of them."
      )}
      footer={
        <Button asChild>
          <a href="/?view=console/tickets/list">
            {t("Open the console")}
            <ArrowRight />
          </a>
        </Button>
      }
    >
      <SetupSummary
        change={(row) =>
          row.step === "summary" ? (
            <a href={`/?view=console/settings/read/config/${row.section}`}>{t("Settings")}</a>
          ) : (
            <button type="button" onClick={() => onStep(row.step)}>
              {t(TITLES[row.step])}
            </button>
          )
        }
      />
      <Diagnosis />
    </StepCard>
  )
}

/** `ponos doctor`, run here: the terminal's full diagnosis, to read — or to
 * copy whole into a message to whoever is helping. The same text, so that
 * support never has to ask somebody to open a terminal for it. */
export function Diagnosis() {
  const t = useT()
  const [answer, setAnswer] = React.useState<{ code: number; text: string } | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [copied, setCopied] = React.useState(false)

  const run = async () => {
    setBusy(true)
    setCopied(false)
    try {
      setAnswer(await api.doctor())
    } catch (error) {
      setAnswer({ code: -1, text: why(error) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="flex flex-col gap-2" aria-labelledby="diagnosis">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="diagnosis" className="flex-1 text-sm font-semibold">
          {t("Something does not work?")}
        </h3>
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void run()} data-testid="run-doctor">
          {busy ? <LoaderCircle className="animate-spin" /> : <Stethoscope />}
          {busy ? t("Running the diagnosis…") : t("Run the full diagnosis")}
        </Button>
        {answer ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => void navigator.clipboard?.writeText(answer.text).then(() => setCopied(true))}
          >
            {copied ? <Check /> : <Copy />}
            {t("Copy it for support")}
          </Button>
        ) : null}
      </div>
      <p className="text-muted-foreground text-xs leading-relaxed">
        <Rich text={t("The same as `ponos doctor` in a terminal: every check, and what to do about each one that fails.")} />
      </p>
      {answer ? (
        <pre
          className="bg-muted max-h-96 overflow-auto rounded-lg border p-3 font-mono text-xs whitespace-pre-wrap"
          data-testid="doctor-output"
        >
          {answer.text}
        </pre>
      ) : null}
    </section>
  )
}

/* -- the summary, wherever it is drawn -------------------------------------- */

const STATES: Record<Health, { label: string; icon: React.ComponentType<{ className?: string }>; tone: string }> = {
  ok: { label: "OK", icon: CircleCheck, tone: "text-tr-green border-tr-green/40" },
  missing: { label: "Missing", icon: CircleDashed, tone: "text-tr-amber border-tr-amber/40" },
  error: { label: "Error", icon: CircleAlert, tone: "text-destructive border-destructive/40" },
}

const ROW_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  machine: HardDrive,
  provider: Bot,
  model: Route,
  board: NotebookText,
  github: GitPullRequest,
  projects: ListChecks,
  channels: Bell,
  environment: Terminal,
}

/** The installation at a glance, as a record: one line per field, its state, and where it changes. */
export function SetupSummary({ change }: { change: (row: Row) => React.ReactNode }) {
  const t = useT()
  const [summary, setSummary] = React.useState<Summary | null>(null)
  const [failed, setFailed] = React.useState("")

  React.useEffect(() => {
    let live = true
    api.summary().then(
      (read) => live && setSummary(read),
      (error) => live && setFailed(why(error))
    )
    return () => {
      live = false
    }
  }, [])

  if (failed) return <Said ok={false} text={failed} />
  if (!summary) return <p className="text-muted-foreground text-sm">{t("Checking…")}</p>

  return (
    <dl className="divide-border flex flex-col divide-y rounded-xl border" data-testid="summary-rows">
      {rows(summary).map((row) => {
        const state = STATES[row.state]
        const Icon = ROW_ICONS[row.key] ?? ListChecks
        const StateIcon = state.icon
        return (
          <div
            key={row.key}
            data-row={row.key}
            data-state={row.state}
            className="grid grid-cols-[auto_1fr_auto] items-start gap-x-3 gap-y-1 px-4 py-3 sm:grid-cols-[auto_11rem_1fr_auto]"
          >
            <Icon className="text-muted-foreground mt-0.5 size-4" />
            <dt className="text-sm font-medium">{t(row.label)}</dt>
            <dd className="col-start-2 min-w-0 text-sm sm:col-start-3 sm:row-start-1">
              <span className="break-words">{t(row.value, row.params)}</span>
              {row.said ? (
                <span className="text-muted-foreground block text-xs break-words">{row.said}</span>
              ) : null}
            </dd>
            <div className="col-start-3 row-span-2 row-start-1 flex flex-col items-end gap-1 sm:col-start-4 sm:row-span-1">
              <Badge variant="outline" className={state.tone}>
                <StateIcon />
                {t(state.label)}
              </Badge>
              <span className="text-xs underline-offset-2 [&>a]:underline [&>button]:cursor-pointer [&>button]:underline">
                {change(row)}
              </span>
            </div>
          </div>
        )
      })}
    </dl>
  )
}
