import * as React from "react"
import { ArrowRight, CircleCheck } from "lucide-react"

import { Command, Said, StepCard } from "@/components/console/setup/bits"
import { useKnown } from "@/components/console/setup/known"
import { NotionIntegration } from "@/components/console/setup/notion-integration"
import { NotionPlace } from "@/components/console/setup/notion-place"
import { NotionShare } from "@/components/console/setup/notion-share"
import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { cn } from "@/lib/utils"
import { counted, useT } from "@/lib/i18n"
import type { Provisioned, Shared, Summary } from "@/lib/types"

/* -- 3. notion -------------------------------------------------------------- */

export function NotionStep({ storage, onNext }: { storage: string; onNext: () => void }) {
  const t = useT()
  const [board, setBoard] = React.useState<Summary["board"] | null>(null)
  const [token, setToken] = React.useState("")
  const [shared, setShared] = React.useState<Shared | null>(null)
  const [page, setPage] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [done, setDone] = React.useState<Provisioned | null>(null)
  const [problem, setProblem] = React.useState("")
  const [picked, setPicked] = React.useState<"" | "notion" | "markdown">("")
  const { summary, reread } = useKnown()

  React.useEffect(() => {
    if (summary) setBoard(summary.board)
  }, [summary])

  React.useEffect(() => {
    // A token already written — a step left half-way, a reload — is asked again.
    void api.sharedWithNotion("").then(
      (answer) => answer.ok && setShared(answer),
      () => undefined
    )
  }, [])

  const found = board?.state === "ok"
  // What the file says now, which a click on "files" changes without a reload.
  const kept = board?.storage ?? storage
  const choice = picked || (kept === "markdown" ? "markdown" : found || kept === "both" ? "notion" : "")
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

  const files = async () => {
    setPicked("markdown")
    setProblem("")
    if (kept === "markdown") return
    setBusy(true)
    try {
      const answer = await api.saveNotion({ token: "", page: "", storage: "markdown" })
      setBoard(answer.board)
      reread()
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
      let answer = await api.saveNotion({ token: "", page: chosen.page ?? "", workspace: chosen.workspace })
      // The board was files until now: Notion takes over once there is one to read.
      if (kept === "markdown" && !answer.problem) {
        answer = { ...answer, board: (await api.saveNotion({ token: "", page: "", storage: "notion" })).board }
      }
      setDone(answer)
      setBoard(answer.board)
      reread()
    } catch (error) {
      setProblem(why(error))
    } finally {
      setBusy(false)
    }
  }

  const footer = (
    <Button
      type="button"
      variant={found || choice === "markdown" ? "default" : "outline"}
      disabled={!choice}
      onClick={onNext}
    >
      {t("Continue")}
      <ArrowRight />
    </Button>
  )

  const roads = [
    {
      key: "notion",
      title: "My board in Notion",
      lines: ["Needs an integration token, and one page shared with it.", "Ponos builds the databases itself."],
    },
    {
      key: "markdown",
      title: "A board of Markdown files",
      lines: ["Nothing to connect, no account, no network.", "A folder to keep under git."],
    },
  ] as const

  return (
    <StepCard
      title={t("The board")}
      blurb={t("Where your tickets live. You can change your mind later in the settings.")}
      footer={footer}
    >
      <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label={t("Where the board lives")}>
        {roads.map((road) => (
          <button
            key={road.key}
            type="button"
            role="radio"
            aria-checked={choice === road.key}
            data-testid={`board-${road.key}`}
            disabled={busy}
            onClick={() => (road.key === "markdown" ? void files() : setPicked("notion"))}
            className={cn(
              "flex flex-col gap-2 rounded-xl border p-4 text-left transition-colors",
              choice === road.key ? "border-primary ring-primary/30 bg-primary/5 ring-2" : "hover:bg-muted/60"
            )}
          >
            <span className="flex items-center justify-between gap-2 font-semibold">
              {t(road.title)}
              {choice === road.key ? <CircleCheck className="text-primary size-4" /> : null}
            </span>
            <ul className="text-muted-foreground flex flex-col gap-1 text-xs leading-relaxed">
              {road.lines.map((line) => (
                <li key={line}>{t(line)}</li>
              ))}
            </ul>
          </button>
        ))}
      </div>
      {choice === "markdown" ? (
        <div className="flex flex-col gap-3" data-testid="board-files">
          <p className="text-muted-foreground text-sm leading-relaxed">
            {t("This console keeps its board in Markdown files: there is nothing to connect.")}
          </p>
          {board?.path ? <Command text={board.path} /> : null}
          <Said ok={false} text={problem} />
        </div>
      ) : null}
      {choice === "notion" ? (
        <>
      {/* Only once there is one: before, what is missing is what the three
          gestures below are about, and the configuration's own words for it
          would only alarm somebody who has not started yet. */}
      {found ? (
        <Said
          ok
          text={counted(
            board.tickets ?? 0,
            "A board is connected: {{count}} ticket on it.",
            "A board is connected: {{count}} tickets on it."
          )}
        />
      ) : board?.state === "error" ? (
        <Said ok={false} text={board.said} />
      ) : null}

      <NotionIntegration token={token} shared={shared} busy={busy} onType={setToken} onCheck={(event) => void check(event)} />
      {shared?.ok ? <NotionShare name={shared.name || "Ponos"} /> : null}
      {shared?.ok ? (
        <NotionPlace
          shared={shared}
          waiting={waiting}
          found={found}
          page={page}
          busy={busy}
          done={done}
          onPage={setPage}
          onBuild={(chosen) => void build(chosen)}
        />
      ) : null}
      <Said ok={false} text={problem} />
        </>
      ) : null}
    </StepCard>
  )
}
