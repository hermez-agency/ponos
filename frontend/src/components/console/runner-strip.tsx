import * as React from "react"
import { Activity, Gauge, LayoutGrid } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { useConsole, useStatus } from "@/hooks/use-console"
import { counted, t as translate, useT } from "@/lib/i18n"
import { money, number } from "@/lib/numbers"
import type { Places, Waiting } from "@/lib/types"
import { cn } from "@/lib/utils"

import { Rich } from "./text"

/* The runner's three numbers, in one line over the board.
 *
 * How many sessions are writing, how many of the daemon's places are taken —
 * and, on a click, which ticket holds each and why the queue waits — what has
 * been handled and what it cost. They had a page of their own, as three big tiles
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
 * Above them, whatever is stopping the whole thing: a daemon that is on above a
 * board that stands still has only one other honest reading, and it is "this
 * thing is broken". Everything is read off the state the console already has.
 */

/* What the daemon's state is called, in words. `systemctl` answers in its own
 * vocabulary — `not-found`, `masked`, `failed` — and "daemon not-found" is a
 * log line, not a sentence. */
const DAEMON: Record<string, string> = {
  disabled: "daemon switched off — ponos service on",
  "not-found": "daemon not installed — ponos service on",
  "not installed": "daemon not installed — ponos service on",
  masked: "daemon masked in systemd",
  failed: "daemon stopped on an error — ponos service on",
  stopped: "no daemon — ponos daemon",
  inactive: "daemon stopped — ponos service on",
  "no systemd": "no daemon — ponos daemon",
  unknown: "daemon state unknown",
}

function daemonNote(state: string | undefined): string {
  if (!state) return "—"
  const said = DAEMON[state]
  return said ? translate(said) : translate("daemon {{state}}", { state })
}

/* Why a ticket of the queue waits, as the daemon writes it (`scheduler.py`). */
function waits(waiting: Waiting): string {
  const said: Record<string, string> = {
    places: translate("every place is taken"),
    project: translate("its project is at its limit"),
    after: translate("waits for {{tickets}}", { tickets: waiting.detail }),
    date: translate("not before {{at}}", { at: waiting.detail }),
    credits: translate("out of credit"),
    reserve: translate("the credit reserve is reached"),
  }
  return said[waiting.why] ?? waiting.why
}

/* The places, one line each, then the projects at their count, then the
 * queue with why each waits: what `ponos status` prints, in the console. */
function PlacesList({ places }: { places: Places }) {
  const t = useT()
  return (
    <div className="flex flex-col gap-3 text-sm" data-slot="places-list">
      <section className="flex flex-col gap-1">
        <h3 className="font-medium">
          {t("{{busy}} of {{width}} places taken", {
            busy: String(places.busy.length),
            width: String(places.width),
          })}
        </h3>
        {places.busy.length ? (
          <ul className="text-muted-foreground flex flex-col gap-0.5">
            {places.busy.map((place, index) => (
              <li key={`${place.ticket}-${index}`} className="truncate">
                {place.title || (place.kind === "replies" ? t("the answers to comments") : place.kind)}
                {place.project ? ` · ${place.project}` : ""}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground">{t("every place is free")}</p>
        )}
      </section>
      {places.projects.length ? (
        <section className="flex flex-col gap-1">
          <h3 className="font-medium">{t("By project")}</h3>
          <ul className="text-muted-foreground flex flex-col gap-0.5">
            {places.projects.map((project) => (
              <li key={project.name}>
                {t("{{project}}: {{busy}} of {{limit}}", {
                  project: project.name,
                  busy: String(project.busy),
                  limit: String(project.limit),
                })}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <section className="flex flex-col gap-1">
        <h3 className="font-medium">
          {counted(places.queue.length, "{{count}} ticket waiting", "{{count}} tickets waiting")}
        </h3>
        {places.queue.length ? (
          <ul className="flex flex-col gap-0.5">
            {places.queue.map((waiting) => (
              <li key={waiting.ticket} className="flex min-w-0 flex-col">
                <span className="truncate">{waiting.title}</span>
                <span className="text-muted-foreground truncate text-xs">{waits(waiting)}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </div>
  )
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
  const on = runner?.daemon === "running"
  const places = runner?.places

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
          <Popover>
            <PopoverTrigger
              className="min-w-0 cursor-pointer text-left"
              aria-label={t("The daemon's places and its queue")}
              data-slot="places-trigger"
            >
              <Figure
                icon={LayoutGrid}
                label={t("places")}
                value={on && places ? `${places.busy.length}/${places.width}` : t("off")}
                note={
                  !on
                    ? daemonNote(runner?.daemon)
                    : places?.queue.length
                      ? counted(places.queue.length, "{{count}} ticket waiting", "{{count}} tickets waiting")
                      : t("nothing waits")
                }
                tone={on ? undefined : "text-tr-amber"}
                // "nothing waits" says less than the other two notes: where the
                // line is short, it is the one that gives way.
                spare={on && !places?.queue.length}
              />
            </PopoverTrigger>
            {places ? (
              <PopoverContent align="start" className="w-80">
                <PlacesList places={places} />
              </PopoverContent>
            ) : null}
          </Popover>
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
