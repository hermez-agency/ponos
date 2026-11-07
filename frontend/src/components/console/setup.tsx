import * as React from "react"
import { ArrowLeft } from "lucide-react"

import { AccessStep } from "@/components/console/setup/access-step"
import { ChannelsStep } from "@/components/console/setup/channels-step"
import { DemoStep } from "@/components/console/setup/demo-step"
import { Diagnosis as DiagnosisCard, ServiceLog as ServiceLogCard } from "@/components/console/setup/diagnosis"
import { GithubStep } from "@/components/console/setup/github-step"
import { KnownContext, type Known } from "@/components/console/setup/known"
import { LanguageStep } from "@/components/console/setup/language-step"
import { ProjectStep } from "@/components/console/setup/project-step"
import { ProviderStep } from "@/components/console/setup/provider-step"
import { Stepper } from "@/components/console/setup/stepper"
import { SetupSummary as SummaryCard } from "@/components/console/setup/summary"
import { SummaryStep } from "@/components/console/setup/summary-step"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { Worded as WordedIn, useT } from "@/lib/i18n"
import { nextStep, stepFrom, stepStates, stepsFor, type StepKey } from "@/lib/setup"
import type { SetupState, Summary } from "@/lib/types"

/* The steps' French, in `setup-french.ts`: fetched when they are drawn in
 * French — the language step can turn it on halfway through — and waited for,
 * so that a step is not drawn in English first. */
const words = () => import("@/lib/setup-french").then((module) => module.SETUP_FRENCH)

const Worded = ({ children }: { children: React.ReactNode }) => <WordedIn words={words}>{children}</WordedIn>

// The Settings page draws these too, and loads them through this module.
export const Diagnosis = () => (
  <Worded>
    <DiagnosisCard />
  </Worded>
)
export const ServiceLog = () => (
  <Worded>
    <ServiceLogCard />
  </Worded>
)
export const SetupSummary = (props: React.ComponentProps<typeof SummaryCard>) => (
  <Worded>
    <SummaryCard {...props} />
  </Worded>
)

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
  return (
    <Worded>
      <Steps />
    </Worded>
  )
}

function Steps() {
  const t = useT()
  const [state, setState] = React.useState<SetupState | null>(null)
  const [failed, setFailed] = React.useState("")
  const [step, setStep] = React.useState<StepKey>("access")
  const [summary, setSummary] = React.useState<Summary | null>(null)
  const [unread, setUnread] = React.useState("")

  const reread = React.useCallback(async () => {
    try {
      const read = await api.summary()
      setSummary(read)
      setUnread("")
      return read
    } catch (error) {
      setUnread(why(error))
      return null
    }
  }, [])
  const known = React.useMemo<Known>(
    () => ({ summary, failed: unread, reread: () => void reread() }),
    [summary, unread, reread]
  )

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
      if (read.claimed) void reread()
    } catch (error) {
      setFailed(why(error))
    }
  }, [reread])

  React.useEffect(() => {
    void api.setupState().then(
      async (read) => {
        if (!read) {
          window.location.assign("/")
          return
        }
        // Claimed, the summary decides where a bare `/setup` opens: on itself
        // when nothing is left to do, rather than on the language again.
        const asked = askedStep()
        const pending = read.claimed ? reread() : null
        const opened = pending && !asked ? await pending : null
        setState(read)
        setStep(stepFrom(read, asked, opened))
      },
      (error) => setFailed(why(error))
    )
  }, [reread])

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
    <KnownContext.Provider value={known}>
      <Shell back={state.claimed}>
        <Stepper
          steps={steps}
          current={step}
          reachable={state.claimed}
          marks={summary ? stepStates(summary) : {}}
          onStep={go}
        />
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
    </KnownContext.Provider>
  )
}

/** The page, and — once the console is claimed — the way back to it. */
function Shell({ back = false, children }: { back?: boolean; children: React.ReactNode }) {
  const t = useT()
  return (
    <main className="bg-background text-foreground min-h-svh px-4 py-10">
      <div className="mx-auto w-full max-w-3xl">
        {back ? (
          <Button asChild variant="ghost" size="sm" className="-ml-2 mb-4">
            <a href="/">
              <ArrowLeft />
              {t("Back to the console")}
            </a>
          </Button>
        ) : null}
        <header className="mb-6">
          <p className="text-muted-foreground font-mono text-xs">Ponos</p>
          <h1 className="text-2xl leading-tight font-bold tracking-[-0.03em] sm:text-[1.75rem]">
            {t("First connection")}
          </h1>
        </header>
        {children}
      </div>
    </main>
  )
}
