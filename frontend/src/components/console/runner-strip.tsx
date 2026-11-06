import * as React from "react"
import { Activity, Gauge, Timer } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { useConsole, useStatus } from "@/hooks/use-console"
import { counted, t as translate, useT } from "@/lib/i18n"
import { money, number } from "@/lib/numbers"
import { cn } from "@/lib/utils"

import { Rich } from "./text"

/* The runner's three numbers, in one line over the board.
 *
 * How many sessions are writing, how often the timer comes round, what has been
 * handled and what it cost. They had a page of their own, as three big tiles
 * over the sessions — and the sessions now live on their tickets, so the numbers
 * came to the board, where those tickets are, as a strip rather than tiles: a
 * board is for reading cards, and a row of figures over it is read in one
 * glance or not at all.
 *
 * At the end of the same line, whatever the page that holds it puts there — the
 * dashboard's call for ideas — so that the strip and its button are one band
 * rather than a button alone on a line of its own above it. Each figure reads
 * the same way: its number first, then what it counts, then a note one shade
 * quieter, in one face and one size; a rule between two figures. The strip's
 * own width decides, not the screen's — the menu beside it takes a quarter of a
 * laptop — so it is a container: under 44rem one figure a line, and the button
 * says its words only where the three notes have room beside it.
 *
 * Above them, whatever is stopping the whole thing: a timer that is on above a
 * board that stands still has only one other honest reading, and it is "this
 * thing is broken". Everything is read off the state the console already has.
 */

/* What the timer's state is called, in words. `systemctl is-enabled` answers
 * in its own vocabulary — `not-found`, `masked`, `static` — and "timer
 * not-found" is a log line, not a sentence. */
const TIMER: Record<string, string> = {
  disabled: "timer switched off — ponos service on",
  "not-found": "timer not installed — ponos service on",
  "not installed": "timer not installed — ponos service on",
  masked: "timer masked in systemd",
  stalled: "timer on, with no next run",
  "no systemd": "no systemd and no runner loop — ponos run --every",
  unknown: "timer state unknown",
}

function timerNote(state: string | undefined): string {
  if (!state) return "—"
  const said = TIMER[state]
  return said ? translate(said) : translate("timer {{state}}", { state })
}

/** An interval, as somebody would say it out loud. */
export function every(seconds: number): string {
  if (!seconds) return "—"
  return seconds < 120 ? `${seconds}s` : `${Math.round(seconds / 60)} min`
}

function Figure({
  icon: Icon,
  label,
  value,
  note,
  tone,
  spare = false,
}: {
  icon: typeof Activity
  label: string
  value: string
  note: string
  tone?: string
  /** A note that may go where the line is short. */
  spare?: boolean
}) {
  return (
    <div className="flex min-w-0 items-center gap-2 @min-[44rem]:border-l @min-[44rem]:pl-3 @min-[44rem]:first:border-l-0 @min-[44rem]:first:pl-0">
      <Icon className="text-muted-foreground size-4 shrink-0" aria-hidden />
      <span className="flex min-w-0 items-baseline gap-1.5">
        <span className={cn("font-semibold whitespace-nowrap tabular-nums", tone)}>{value}</span>
        <span className="text-muted-foreground shrink-0">{label}</span>
        <span
          className={cn(
            "text-muted-foreground truncate",
            spare && "@min-[44rem]:@max-[60rem]:hidden"
          )}
          title={note}
        >
          · {note}
        </span>
      </span>
    </div>
  )
}

export function RunnerStrip({ action }: { action?: React.ReactNode }) {
  const { runner, board } = useConsole()
  const { running: sessions } = useStatus()
  const t = useT()
  const running = board.tickets.filter((item) => item.column === "running").length
  const on = runner?.timer === "enabled"

  return (
    <div className="mb-4 flex flex-col gap-3">
      {runner?.credits ? (
        <Alert variant="destructive">
          <AlertDescription>
            {t(
              "Out of credit until {{at}}. The subscription's window is spent: tickets stay where they are, and the first run after that takes them again.",
              { at: runner.credits_at }
            )}
          </AlertDescription>
        </Alert>
      ) : null}
      {runner?.budget ? (
        <Alert variant="destructive">
          <AlertDescription>
            {t(
              "Today's spending limit is reached: {{spent}} spent, limit {{limit}}. Ready tickets wait, and nothing new starts before midnight.",
              { spent: money(runner.budget_spent), limit: money(runner.budget) }
            )}
          </AlertDescription>
        </Alert>
      ) : null}
      {runner && !runner.claude ? (
        <Alert variant="destructive">
          <AlertDescription>
            <Rich text={t("`claude` was not found on this machine: no session can start.")} />
          </AlertDescription>
        </Alert>
      ) : null}

      <div
        className="bg-card @container flex min-h-12 items-center gap-3 rounded-xl border py-2 pr-2 pl-3.5 text-sm"
        data-slot="runner-strip"
      >
        <div className="flex min-w-0 flex-1 flex-col gap-1.5 @min-[44rem]:flex-row @min-[44rem]:items-center @min-[44rem]:gap-3">
          <Figure
            icon={Activity}
            label={t("sessions")}
            value={String(sessions.length)}
            note={
              running
                ? counted(running, "{{count}} ticket in progress", "{{count}} tickets in progress")
                : t("nothing in progress")
            }
            tone={sessions.length ? "text-tr-green" : undefined}
          />
          <Figure
            icon={Timer}
            label={t("timer")}
            value={on ? every(runner?.interval_seconds ?? 0) : t("off")}
            note={on ? t("between two runs") : timerNote(runner?.timer)}
            tone={on ? undefined : "text-tr-amber"}
          // "between two runs" says less than the other two notes: where the
          // line is short, it is the one that gives way.
          spare={on}
          />
          <Figure
            icon={Gauge}
            label={t("handled")}
            value={number(runner?.handled ?? 0)}
            note={t("{{amount}} spent so far", { amount: money(runner?.spend ?? 0) })}
          />
        </div>
        {action ? <div className="ml-auto shrink-0">{action}</div> : null}
      </div>
    </div>
  )
}
