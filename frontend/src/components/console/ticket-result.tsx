import * as React from "react"
import {
  CopyIcon,
  Download,
  ExternalLink,
  GitBranch,
  History,
  MessageSquarePlus,
  Pencil,
  TriangleAlert,
} from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Textarea } from "@/components/ui/textarea"
import { api, why } from "@/lib/api"
import { copy } from "@/lib/copy"
import { useT } from "@/lib/i18n"
import { changes, fileName, isDocument, missionText, plainText } from "@/lib/result"
import { canAct } from "@/lib/role"
import type { ResultVersion, TicketDetail } from "@/lib/types"

import { Eyebrow } from "./frame"
import { Markdown } from "./markdown"
import { PreviewPairs } from "./preview-pairs"
import { TicketCi, when } from "./ticket-bits"

/* A ticket opened: its result, in a tab of its own, and its mission in another.
 *
 * The result — the post, the audit, the summary of a change — used to sit in
 * the part « What was done », under the runner's line about the session and
 * above its history: to copy the post, you selected around the rest. It is a
 * part of its own now (results.py), the first thing the page shows once the
 * work is over, with what one does with a deliverable: copy it, download it,
 * retouch it, send it back with an instruction. What the sessions said of
 * themselves is the Journal tab.
 *
 * The mission and the result shared one tab for a while, the mission folded
 * above once there was a result — a tab called « Mission », then « Result »,
 * over a block called « Mission » over a text headed « Mission ». Each has its
 * tab now (see `TicketTabs`): the mission whole, under one title.
 */

export function TicketMission({ mission }: { mission: string }) {
  const t = useT()
  const text = missionText(mission)
  return (
    <section data-slot="ticket-mission" className="flex flex-col gap-2">
      <Eyebrow>{t("Mission")}</Eyebrow>
      {text ? (
        <Markdown text={text} />
      ) : (
        <p className="text-muted-foreground text-sm">
          {t("The page is empty: the title is the whole brief.")}
        </p>
      )}
    </section>
  )
}

type Mode = "read" | "edit" | "revise"

export function TicketResult({
  ticket,
  result,
  versions,
  journal,
  previews,
  onSaved,
}: {
  ticket: TicketDetail
  result: string
  versions: ResultVersion[]
  journal: string
  previews?: TicketDetail["previews"]
  onSaved: () => void
}) {
  const t = useT()
  const [mode, setMode] = React.useState<Mode>("read")
  const [text, setText] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [problem, setProblem] = React.useState("")
  // A version picked in the history: shown in place of the last one until let go.
  const [picked, setPicked] = React.useState<number>()
  const drawn = React.useRef<HTMLDivElement>(null)
  const shown = versions.find((one) => one.version === picked)
  const body = shown ? shown.text : result
  const latest = versions[0]?.version
  const document = isDocument(ticket.type ?? "", ticket.kind ?? "")
  const acts = canAct()

  const send = (sending: Promise<unknown>, done: string) => {
    setBusy(true)
    setProblem("")
    sending.then(
      () => {
        setBusy(false)
        setMode("read")
        setPicked(undefined)
        toast.success(t(done))
        onSaved()
      },
      (error) => {
        setBusy(false)
        setProblem(why(error))
      }
    )
  }

  const download = (extension: "md" | "pdf") => {
    if (extension === "md") {
      const link = window.document.createElement("a")
      link.href = URL.createObjectURL(new Blob([`${body.trim()}\n`], { type: "text/markdown" }))
      link.download = fileName(ticket.title, "md")
      link.click()
      URL.revokeObjectURL(link.href)
      return
    }
    printed(ticket.title, drawn.current?.innerHTML ?? "")
  }

  const running = ticket.column === "running" || ticket.column === "ready"
  return (
    <section data-slot="ticket-result" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Eyebrow>{t("Result")}</Eyebrow>
        {body.trim() && mode === "read" ? (
          <div className="flex flex-wrap items-center gap-1.5" data-slot="ticket-result-actions">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm">
                  <CopyIcon />
                  {t("Copy")}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => void copy(plainText(body), t("the text"))}>
                  {t("Copy the text")}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => void copy(body.trim(), t("the Markdown"))}>
                  {t("Copy the Markdown")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm">
                  <Download />
                  {t("Download")}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => download("md")}>{t("Markdown (.md)")}</DropdownMenuItem>
                {document ? (
                  <DropdownMenuItem onSelect={() => download("pdf")}>{t("PDF (.pdf)")}</DropdownMenuItem>
                ) : null}
              </DropdownMenuContent>
            </DropdownMenu>
            {versions.length > 1 ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="sm" data-slot="ticket-result-versions">
                    <History />
                    {t("Version {{n}}", { n: String(shown?.version ?? latest ?? 1) })}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {versions.map((one) => (
                    <DropdownMenuItem
                      key={one.version}
                      onSelect={() => setPicked(one.version === latest ? undefined : one.version)}
                    >
                      <span className="font-medium">{t("Version {{n}}", { n: String(one.version) })}</span>
                      <span className="text-muted-foreground text-xs">
                        {sourceWord(t, one)} · {when(one.at)}
                      </span>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
            {acts ? (
              <>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setText(body)
                    setMode("edit")
                  }}
                >
                  <Pencil />
                  {t("Edit")}
                </Button>
                {!running ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setText("")
                      setMode("revise")
                    }}
                  >
                    <MessageSquarePlus />
                    {t("Request a change")}
                  </Button>
                ) : null}
              </>
            ) : null}
          </div>
        ) : null}
      </div>

      {shown ? (
        <p className="text-muted-foreground flex flex-wrap items-center gap-2 text-sm" data-slot="ticket-result-older">
          {t("An earlier version: {{source}}, {{at}}.", { source: sourceWord(t, shown), at: when(shown.at) })}
          <Button variant="link" size="sm" className="h-auto p-0" onClick={() => setPicked(undefined)}>
            {t("Back to the latest")}
          </Button>
          {acts ? (
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0"
              disabled={busy}
              onClick={() => send(api.setResult(ticket.id, shown.text), "This version is the result again")}
            >
              {t("Make it the result again")}
            </Button>
          ) : null}
        </p>
      ) : null}

      {mode === "edit" ? (
        <div className="flex flex-col gap-2">
          <Textarea
            data-slot="ticket-result-editor"
            aria-label={t("Result")}
            className="min-h-64 font-mono text-sm"
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <p className="text-muted-foreground text-xs">{t("Saved as a new version: the one before is kept.")}</p>
          {problem ? <p className="text-destructive text-sm">{problem}</p> : null}
          <div className="flex gap-2">
            <Button size="sm" disabled={busy || !text.trim()} onClick={() => send(api.setResult(ticket.id, text), "Result saved")}>
              {t("Save")}
            </Button>
            <Button variant="outline" size="sm" disabled={busy} onClick={() => setMode("read")}>
              {t("Cancel")}
            </Button>
          </div>
        </div>
      ) : null}

      {mode === "revise" ? (
        <div className="flex flex-col gap-2" data-slot="ticket-result-revise">
          <Textarea
            aria-label={t("What should change")}
            placeholder={t("What should change — the tone, a paragraph, a finding to check again…")}
            className="min-h-24 text-sm"
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <p className="text-muted-foreground text-xs">
            {t("The ticket goes back to work with this instruction; its next result is a new version, this one kept.")}
          </p>
          {problem ? <p className="text-destructive text-sm">{problem}</p> : null}
          <div className="flex gap-2">
            <Button size="sm" disabled={busy || !text.trim()} onClick={() => send(api.revise(ticket.id, text), "Change requested")}>
              {t("Send")}
            </Button>
            <Button variant="outline" size="sm" disabled={busy} onClick={() => setMode("read")}>
              {t("Cancel")}
            </Button>
          </div>
        </div>
      ) : null}

      {mode !== "edit" ? (
        body.trim() ? (
          <div ref={drawn} data-slot="ticket-result-body" className="bg-card rounded-xl border px-4 py-3">
            <Markdown text={body} />
          </div>
        ) : ticket.pull_request ? (
          // A change that wrote no result of its own still has one: its pull
          // request, and what the session said it changed.
          <>
            <PullRequestCard ticket={ticket} />
            {changes(journal) ? (
              <div data-slot="ticket-result-changes" className="bg-card rounded-xl border px-4 py-3">
                <Markdown text={changes(journal)} />
              </div>
            ) : null}
          </>
        ) : journal.trim() && !running ? (
          <p className="text-tr-amber flex items-center gap-1.5 text-sm" data-slot="ticket-no-result">
            <TriangleAlert className="size-4" />
            {t("No result rendered: the session said what it did, in the Journal tab, but handed back no deliverable.")}
          </p>
        ) : (
          <p className="text-muted-foreground text-sm">
            {t("Nothing yet: the result comes with the first session that ends.")}
          </p>
        )
      ) : null}

      {ticket.pull_request && body.trim() ? <PullRequestCard ticket={ticket} /> : null}
      <PreviewPairs ticket={ticket.id} shots={previews} />
    </section>
  )
}

/* A code ticket's pull request, as its result shows it: where it stands, its
 * checks, and the way to its diff. */
function PullRequestCard({ ticket }: { ticket: TicketDetail }) {
  const t = useT()
  const number = ticket.pull_request.match(/\/pull\/(\d+)/)?.[1]
  const state =
    ticket.column === "done"
      ? t("merged")
      : ticket.column === "validated"
        ? t("validated, being merged")
        : ticket.column === "review"
          ? t("open, waiting for your review")
          : ticket.column === "cancelled"
            ? t("closed")
            : t("open")
  return (
    <div data-slot="ticket-result-pr" className="bg-card flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border px-4 py-3 text-sm">
      <a
        href={ticket.pull_request}
        target="_blank"
        rel="noreferrer noopener"
        className="inline-flex items-center gap-1.5 font-semibold underline-offset-2 hover:underline"
      >
        <GitBranch className="size-4" />
        {number ? `PR #${number}` : t("pull request")}
      </a>
      <span className="text-muted-foreground">{state}</span>
      {ticket.ci ? <TicketCi ci={ticket.ci} slot="ticket-result-ci" /> : null}
      <a
        href={`${ticket.pull_request.replace(/\/+$/, "")}/files`}
        target="_blank"
        rel="noreferrer noopener"
        className="text-primary ml-auto inline-flex items-center gap-1 underline-offset-2 hover:underline"
      >
        {t("View the diff")}
        <ExternalLink className="size-3.5" />
      </a>
    </div>
  )
}

function sourceWord(t: ReturnType<typeof useT>, version: ResultVersion): string {
  switch (version.source) {
    case "edit":
      return version.author ? t("retouched by {{who}}", { who: version.author }) : t("retouched by hand")
    case "migration":
      return t("kept from before")
    default:
      return t("by a session")
  }
}

/* The result as a PDF: drawn as the page draws it, in a frame of its own,
 * and handed to the browser's print — where « Save as PDF » is. Nothing is
 * sent anywhere, and no library comes into the first load for it. */
function printed(title: string, html: string) {
  const frame = window.document.createElement("iframe")
  frame.setAttribute("aria-hidden", "true")
  frame.style.cssText = "position:fixed;width:0;height:0;border:0;right:0;bottom:0"
  window.document.body.appendChild(frame)
  const page = frame.contentDocument
  const view = frame.contentWindow
  if (!page || !view) {
    frame.remove()
    return
  }
  const styles = [...window.document.querySelectorAll('link[rel="stylesheet"], style')]
    .map((node) => node.outerHTML)
    .join("")
  page.open()
  page.write(
    `<!doctype html><html><head><meta charset="utf-8"><title></title>${styles}` +
      `<style>body{padding:24px;background:#fff;color:#111}</style></head><body><main></main></body></html>`
  )
  page.close()
  page.title = fileName(title, "pdf").replace(/\.pdf$/, "")
  const main = page.querySelector("main")
  if (main) main.innerHTML = html
  const done = () => frame.remove()
  view.addEventListener("afterprint", done)
  setTimeout(() => {
    view.focus()
    view.print()
    setTimeout(done, 60_000)
  }, 300)
}
