import * as React from "react"
import { MoreHorizontal, RotateCw } from "lucide-react"
import { toast } from "sonner"
import { useNavigate } from "react-resource-view"

import { Bubble, BubbleContent } from "@/components/ui/bubble"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Message, MessageContent, MessageHeader } from "@/components/ui/message"
import { Skeleton } from "@/components/ui/skeleton"
import { useConsole } from "@/hooks/use-console"
import { api, why } from "@/lib/api"
import { currentBoard, titleOf, useBoard } from "@/lib/board-store"
import {
  type Reply,
  answersIn,
  askedAt,
  itemsOf,
  labelOf,
  quiet,
  repliesOf,
  typedOf,
} from "@/lib/decision"
import { currentLanguage, t as translate, useT } from "@/lib/i18n"
import { secretsIn } from "@/lib/secrets"
import type { Decision, Solution, Ticket } from "@/lib/types"

import { boardHref } from "@/resources/tickets"

import { Composer } from "./composer"
import { ModelChoice } from "./model-input"
import { ConfirmDialog } from "./confirm-dialog"
import { Markdown } from "./markdown"
import { Robot } from "./robot"
import { NO_COMMIT, blockSaid, lasted } from "./ticket-bits"
import { Turn } from "./turn"

/** An instant as the language the console is in would write it, or nothing at all. */
function moment(at?: string): string {
  if (!at) return ""
  const date = new Date(at)
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleString(currentLanguage(), { dateStyle: "short", timeStyle: "short" })
}

// The page's own language, as in the workspace's bar: what the person
// answering is reading, and so the likeliest one they are speaking.
const transcribe = async (audio: Blob) => (await api.transcribe(audio, currentLanguage())).text

// How often a discussion is read again while Ponos is answering words rather
// than running: a reply to a mention moves no card, and nothing else would say it came.
const REREAD = 20_000

/* One ticket's discussion, on its page.
 *
 * What you type is a comment on it, and a comment is already how a ticket is
 * answered: a reply under the question a run asked puts the ticket back in the
 * queue, and one that names the runner asks it for words instead. So there is
 * nothing new to learn here, and nothing kept on the side: the discussion is
 * Notion's, and the same words typed into Notion do the same.
 *
 * It used to be behind the bubble, which changed role on a ticket's page and
 * said so nowhere: a question waiting on you was a question you had to guess
 * was there. It is a tab of the page now, counted, and the one the page opens
 * on when the ticket is waiting — see `TicketPage`.
 *
 * A blocked ticket had a tab of its own beside this one, Unblock, which said
 * the question a second time, and again as its reason, with two fields to
 * answer in. It is answered here now: the report it stopped on is drawn as
 * Ponos asking — what is done, why it stops, the question — and under it the
 * quick replies, each the answer it says and the ticket back to work (see
 * `repliesOf`). What is typed is an answer too, on the model picked beside it;
 * the rarer gestures, running it again as it is and giving it up, are behind ⋯.
 *
 * Once something is sent, Ponos is shown at work under it until it says
 * something back — or until the session fails, which is said in its place.
 * The run's lines in passing, the model it chose and the like, are a grey line
 * across rather than a bubble each: they are not Ponos talking to you.
 *
 * The bar is the workspace's, given the words and the voice. Not the files: a
 * comment carries text, and a + that attached nothing would be a + that lied.
 * The steps of a running session are not here either — they are the next tab.
 */
export function TicketTalk({ ticket, onSession }: { ticket: Ticket; onSession: () => void }) {
  const { talk, mention, tell, rereadTalk, talkLoading, talkWaiting, runner, move } = useConsole()
  const board = useBoard()
  const navigate = useNavigate()
  const t = useT()
  // Unblocked: the window has nothing more to say, the card is back on the board.
  const backToBoard = () => void navigate({ to: boardHref() })
  const [problem, setProblem] = React.useState("")
  // The message held back once for a secret in it: sent, masked, if pressed again as it is.
  const [warned, setWarned] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [model, setModel] = React.useState("")
  const [abandoning, setAbandoning] = React.useState(false)
  // Answered: the replies are done with, though the stream has yet to say the ticket moved.
  const [answered, setAnswered] = React.useState(false)
  React.useEffect(() => setAnswered(false), [ticket.column])
  // How many times Ponos had spoken when you last did: it is at work until it speaks again.
  const [sent, setSent] = React.useState<number | null>(null)
  const blocked = ticket.column === "blocked"
  const decision = useDecision(ticket, blocked)
  const solutions = decision?.solutions ?? []
  const answers = answersIn(talk)
  const asked = askedAt(talk)
  const loud = talk.filter((message) => !quiet(message.role, message.text))
  const last = loud[loud.length - 1]
  const moving = ticket.column === "ready" || ticket.column === "running"
  const failed = sent !== null && answers <= sent && ticket.column === "failed"
  // A running ticket is at work whatever was said last: the window reopened
  // after an unblock, or after a reload, has no memory of having sent.
  const working =
    !failed &&
    ((sent !== null && answers <= sent) ||
      (sent === null && (ticket.column === "running" || (moving && last?.role === "you"))))

  // Ponos spoke: it is no longer at work on what you said.
  React.useEffect(() => {
    if (sent !== null && answers > sent) setSent(null)
  }, [sent, answers])

  // Asked for words, it answers without moving the card: read again until it has.
  React.useEffect(() => {
    if (!working || moving) return
    const timer = window.setInterval(rereadTalk, REREAD)
    return () => window.clearInterval(timer)
  }, [working, moving, rereadTalk])

  // A blocked ticket opens on its question, which is the last thing said.
  const end = React.useRef<HTMLDivElement>(null)
  const scrolled = React.useRef(false)
  React.useEffect(() => {
    if (scrolled.current || !blocked || !talk.length || !decision) return
    scrolled.current = true
    end.current?.scrollIntoView({ block: "end" })
  }, [blocked, talk.length, decision])
  React.useEffect(() => {
    if (working) end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [working])

  /** One of the offers sent; the ticket at work again when it goes back to Ready. */
  async function decide(offer: Solution, text: string, picked = "") {
    setBusy(true)
    setProblem("")
    try {
      await api.decide(ticket.id, { key: offer.key, number: offer.number, text, model: picked })
      toast.success(
        t("“{{title}}” moved to {{column}}", {
          title: titleOf(ticket),
          column: board.columns.find((item) => item.key === offer.column)?.name || offer.column,
        })
      )
      setAnswered(true)
      if (offer.column === "ready") {
        setSent(answers)
        backToBoard()
      }
      return true
    } catch (error) {
      toast.error(t("The decision was not sent"), { description: why(error) })
      return false
    } finally {
      setBusy(false)
    }
  }

  async function reply(chosen: Reply<Solution>) {
    if (chosen.offer) {
      await decide(chosen.offer, chosen.text ? translate(chosen.text) : "")
      return
    }
    // Nothing on offer runs it again as it is: the move back to Ready does.
    setBusy(true)
    try {
      await move(ticket, "ready")
      setAnswered(true)
      setSent(answers)
      // A move that failed was put back by the board, and said so: the window stays.
      if (currentBoard()?.tickets.find((item) => item.id === ticket.id)?.column === "ready") backToBoard()
    } finally {
      setBusy(false)
    }
  }

  const send = async (text: string) => {
    setProblem("")
    // A comment stays on the page: a password in it is said before it leaves.
    if (secretsIn(text).length && warned !== text) {
      setWarned(text)
      setProblem(
        t(
          "This looks like a password or a token. Nothing was sent: remove it, or send again and it will be masked before it reaches the ticket."
        )
      )
      return false
    }
    setWarned("")
    const offer = blocked
      ? model
        ? solutions.find((solution) => solution.key === "model")
        : typedOf(solutions)
      : null
    if (offer) {
      const done = await decide(offer, text.trim(), model)
      if (done) setModel("")
      return done
    }
    try {
      await tell(text)
      // An answer to its question, or its name: Ponos is going to say something.
      if (talkWaiting || text.toLowerCase().includes(mention.toLowerCase())) setSent(answers)
      return true
    } catch (error) {
      setProblem(translate("not written: {{why}}", { why: why(error) }))
      return false
    }
  }

  const replies = decision ? repliesOf(ticket.column, solutions) : []
  const retry = replies[replies.length - 1]
  const abandon = solutions.find((solution) => solution.key === "abandon")
  const models = solutions.some((solution) => solution.key === "model")
    ? (board.choices?.model ?? []).filter((one) => one.value && one.value !== decision?.model)
    : []
  // Where the question is drawn: in place of the report it was asked in, or
  // last, for a ticket set aside by hand that no report explains.
  const at = decision ? (asked >= 0 ? asked : talk.length) : -1
  const session = sessionLine(ticket)
  const lastSaid = talk.findLastIndex((message) => message.role === "runner" && !quiet(message.role, message.text))
  const sessionAt = session && !moving ? (lastSaid >= 0 ? lastSaid : talk.length) : -1

  const question = (
    <React.Fragment key="question">
      {decision ? <Asked decision={decision} when={asked >= 0 ? moment(talk[asked].at) : ""} /> : null}
      {replies.length ? (
        <div
          role="group"
          aria-label={t("Quick replies")}
          data-slot="quick-replies"
          className="flex flex-wrap gap-2 sm:pl-8"
        >
          {replies.map((chosen) => (
            <Button
              key={chosen.offer ? `${chosen.offer.key}-${chosen.offer.number}` : "plain"}
              type="button"
              variant="outline"
              size="sm"
              data-reply={chosen.offer?.key ?? "plain"}
              disabled={busy || working || answered}
              className="h-auto min-h-8 max-w-full justify-start rounded-2xl py-1.5 text-left whitespace-normal"
              onClick={() => void reply(chosen)}
            >
              <span className="min-w-0 break-words">
                {chosen.offer?.key === "option" ? chosen.label : t(chosen.label)}
              </span>
            </Button>
          ))}
        </div>
      ) : null}
    </React.Fragment>
  )

  const lines: React.ReactNode[] = []
  talk.forEach((message, index) => {
    if (index === sessionAt) lines.push(<Quiet key="session">{session}</Quiet>)
    if (index === at) {
      lines.push(question)
      return
    }
    lines.push(
      quiet(message.role, message.text) ? (
        <Quiet key={index} title={message.text}>
          {[message.text.trimStart().replace(/^\S+\s*/, "").replace(/\s*\n+\s*/g, " · "), moment(message.at)]
            .filter(Boolean)
            .join(" · ")}
        </Quiet>
      ) : (
        <Turn key={index} role={message.role} text={message.text} when={moment(message.at)} />
      )
    )
  })
  if (sessionAt === talk.length) lines.push(<Quiet key="session">{session}</Quiet>)
  if (at === talk.length) lines.push(question)

  return (
    <div className="flex max-w-3xl flex-col gap-3">
      <div className="flex items-center gap-2">
        <p className="text-muted-foreground min-w-0 flex-1 text-xs">
          {t("an answer to its question runs it again")} ·{" "}
          <code className="bg-muted rounded px-1 py-0.5 font-mono">{mention}</code>{" "}
          {t("asks it for words instead")}
        </p>
        <Button
          variant="ghost"
          size="sm"
          onClick={rereadTalk}
          disabled={talkLoading}
          title={t("read the discussion again")}
        >
          <RotateCw className={talkLoading ? "animate-spin" : undefined} />
          {talkLoading ? t("reading…") : t("reread")}
        </Button>
        {/* The rarer gestures, out of the way of the answer. */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              data-slot="talk-menu"
              aria-label={t("More actions")}
              title={t("More actions")}
            >
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {blocked && retry ? (
              <DropdownMenuItem disabled={busy || working || answered} onSelect={() => void reply(retry)}>
                {t("Run it again as it is")}
              </DropdownMenuItem>
            ) : null}
            {blocked && abandon ? (
              <DropdownMenuItem
                disabled={busy}
                className="text-destructive focus:text-destructive"
                onSelect={() => setAbandoning(true)}
              >
                {t("Abandon")}
              </DropdownMenuItem>
            ) : null}
            <DropdownMenuItem onSelect={onSession}>{t("See the session")}</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* A log rather than a scroller of its own: the page already scrolls,
          and a discussion read oldest first is read the way a page is. */}
      <div role="log" aria-live="polite" className="flex flex-col gap-2">
        {lines}
        {blocked && !decision && asked < 0 && !talkLoading ? (
          <div className="flex flex-col gap-2" aria-busy="true">
            <Skeleton className="h-16 w-2/3" />
            <Skeleton className="h-8 w-1/2" />
          </div>
        ) : null}
        {working ? <Working /> : null}
        {failed ? <Failed ticket={ticket} /> : null}
        {!talk.length && !talkLoading && !blocked ? (
          <p className="text-muted-foreground text-sm">
            {t("Nothing has been said on this ticket yet.")}
          </p>
        ) : null}
        {talkLoading && !talk.length ? (
          <p className="text-muted-foreground text-sm">{t("reading the discussion…")}</p>
        ) : null}
        <div ref={end} />
      </div>

      {problem ? <p className="text-destructive text-xs">{problem}</p> : null}
      <Composer
        className="mx-0 max-w-none"
        busy={false}
        onSend={send}
        placeholder={t("Answer Ponos or give it an instruction…")}
        transcribe={transcribe}
        dictation={
          runner?.chat?.dictation ?? { ready: false, why: t("Dictation is not available"), send: false }
        }
        tools={
          models.length ? (
            <ModelChoice
              value={model}
              onChange={setModel}
              extra={models.map((one) => one.value)}
              label={t("The model it runs on next")}
              className="max-w-48 rounded-full border-transparent shadow-none"
              empty={decision?.model ? t("Same model ({{model}})", { model: decision.model }) : t("Same model")}
            />
          ) : null
        }
      />
      {abandon ? (
        <ConfirmDialog
          open={abandoning}
          onOpenChange={setAbandoning}
          destructive
          title={t("Abandon this ticket?")}
          description={t(labelOf(abandon))}
          confirm={t("Abandon")}
          onConfirm={async () => {
            await decide(abandon, "")
          }}
        />
      ) : null}
    </div>
  )
}

/** Why a blocked ticket waits and what it offers, read when it is blocked and again when it is blocked anew. */
function useDecision(ticket: Ticket, blocked: boolean): Decision | null {
  const [decision, setDecision] = React.useState<{ id: string; decision: Decision } | null>(null)
  const { talk } = useConsole()
  const reports = answersIn(talk)
  React.useEffect(() => {
    if (!blocked) return
    let current = true
    api
      .decision(ticket.id)
      .then((found) => current && setDecision({ id: ticket.id, decision: found }))
      .catch(() => current && setDecision(null))
    return () => {
      current = false
    }
  }, [ticket.id, blocked, reports])
  return blocked && decision?.id === ticket.id && decision.decision.column === "blocked" ? decision.decision : null
}

/* What the ticket's last session was, in passing: which, on what, how long —
 * and that it committed nothing, which is no fault when there was nothing to
 * change, and was a red badge over the page for a while. */
function sessionLine(ticket: Ticket): string {
  if (!ticket.session) return ""
  return [
    `${translate("Session")} ${ticket.session.slice(0, 8)}`,
    (ticket.model_label ?? ticket.model ?? "").replace(/^claude\//, ""),
    typeof ticket.duration === "number" && ticket.duration ? lasted(ticket.duration) : "",
    ticket.block?.code === NO_COMMIT ? blockSaid(ticket.block.label) : "",
  ]
    .filter(Boolean)
    .join(" · ")
}

/** A line in passing, across the discussion: small, grey, centred. */
function Quiet({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <p
      data-slot="talk-quiet"
      title={title}
      className="text-muted-foreground mx-auto max-w-[60ch] py-1 text-center text-xs break-words"
    >
      {children}
    </p>
  )
}

/** Ponos's side of a message, signed the way `Turn` signs it. */
function Ponos({
  children,
  when,
  variant = "outline",
  slot,
}: {
  children: React.ReactNode
  when?: string
  variant?: "outline" | "destructive"
  slot?: string
}) {
  return (
    <Message align="start" data-talk={slot}>
      <MessageContent>
        <MessageHeader className="font-mono text-[0.65rem] font-semibold tracking-[0.14em] uppercase">
          <span data-slot="turn-avatar" className="bg-muted mr-1.5 flex size-6 shrink-0 items-center justify-center rounded-full">
            <Robot state="idle" size={18} still />
          </span>
          Ponos
          {when ? <span className="font-normal normal-case">{` · ${when}`}</span> : null}
        </MessageHeader>
        <Bubble variant={variant} align="start" className="max-w-[92%]">
          <BubbleContent className="text-message flex flex-col gap-2 font-medium [&_:is(p,div)]:max-w-[80ch]">
            {children}
          </BubbleContent>
        </Bubble>
      </MessageContent>
    </Message>
  )
}

/* The question a run stopped on, said once: what is done, why it stops, and
 * the question itself, in bold — the report's three parts, without its marks.
 * The series of blocked tickets draws it too, over the choices. */
export function Asked({ decision, when }: { decision: Decision; when: string }) {
  const t = useT()
  const ask = decision.question?.ask?.trim() ?? ""
  const reason = decision.reason?.trim() ?? ""
  const done = itemsOf(decision.done)
  return (
    <Ponos when={when} slot="question">
      {done.length ? (
        <div className="text-muted-foreground">
          <Markdown text={done.length > 1 ? done.map((item) => `- ${item}`).join("\n") : done[0]} />
        </div>
      ) : null}
      {reason && reason !== ask ? <Markdown text={reason} /> : null}
      {!reason && !ask ? (
        <p>{decision.reported ? t("The run did not say why.") : t("Set aside by hand: no run said why.")}</p>
      ) : null}
      {ask ? (
        <div className="font-semibold" data-slot="talk-ask">
          <Markdown text={ask} />
        </div>
      ) : null}
    </Ponos>
  )
}

/** Ponos at work on what you said: the robot the session wears, and the words. */
function Working() {
  const t = useT()
  return (
    <Message align="start" data-talk="working">
      <MessageContent>
        <div role="status" className="flex items-center gap-3">
          <Robot state="thinking" size={44} className="shrink-0" />
          <p className="text-muted-foreground text-sm">{t("Ponos is working…")}</p>
        </div>
      </MessageContent>
    </Message>
  )
}

/** The session that was to answer failed: why, where Ponos would have answered. */
function Failed({ ticket }: { ticket: Ticket }) {
  const t = useT()
  return (
    <Ponos variant="destructive" slot="failed">
      <p className="font-semibold">{ticket.block ? blockSaid(ticket.block.label) : t("The session failed.")}</p>
      {ticket.block ? <p>{blockSaid(ticket.block.help)}</p> : null}
    </Ponos>
  )
}
