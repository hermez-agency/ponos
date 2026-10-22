import * as React from "react"
import { Moon, RefreshCw, Search, Sun } from "lucide-react"
import {
  Link,
  getPorts,
  useAdminPageTitle,
  useIsActiveItemMenu,
  useScopeContext,
  type MenuItemInterface,
} from "react-resource-view"

import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useConsole, useStatus, useSync } from "@/hooks/use-console"
import { hotkeyLabel } from "@/hooks/use-hotkeys"
import { useRunnerMood } from "@/hooks/use-mood"
import { useTheme } from "@/hooks/use-theme"
import { counted, useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

import { openPalette } from "./command-palette"
import { NotificationBell } from "./notification-bell"
import { InstallApp } from "./install-app"
import { Robot } from "./robot"
import { VersionBadge } from "./version-badge"

/* What the console puts into react-resource-view's admin layout.
 *
 * The layout brings the frame — the sidebar built from the scope's menu, the
 * bar over the page, the bottom navigation on a phone, the page's heading —
 * and leaves the application its places: a logo, the end of the bar, the foot
 * of the sidebar. Everything here goes into one of those, or into the board's
 * menu entry. On a phone the layout puts the foot of the sidebar behind the
 * last entry of its bottom bar, More, with the links pinned there.
 */

/** The mark and the name, in the sidebar's corner — and in the bar, on a phone. */
export function Mark() {
  const mood = useRunnerMood()
  const t = useT()
  return (
    <Link
      to="/"
      aria-label={t("Home")}
      className={cn(
        "-mx-2 flex h-10 items-center gap-2.5 rounded-xl px-2 outline-hidden transition-colors",
        "hover:bg-accent focus-visible:ring-ring/30 focus-visible:ring-2"
      )}
    >
      {/* Ponos, the console's mark and the runner's face, wears the runner's
          mood — the only face that does, now the bar's end no longer carries
          one. Hovered, it says whose face it is. */}
      <span className="flex shrink-0" title="Ponos">
        <Robot state={mood.state} size={28} />
      </span>
      <span className="truncate text-base leading-none font-semibold tracking-tight">Ponos</span>
    </Link>
  )
}

/* -- the menu ------------------------------------------------------------- */

/* The board's entry: its name, and the number of tickets on the board.
 *
 * Seven entries of two lines each used to be a page to read rather than a menu
 * to use — a sentence under every name saying how many tickets were ready,
 * whether the timer was on. What is worth knowing at a glance is a count, and a
 * count fits beside a name.
 *
 * The package's own entry draws a name and an icon and nothing beside them, so
 * this one is the `component` an entry may bring, drawn in the package's own
 * shape. Whether it is lit is the package's answer, not this file's: the entry
 * links to the board, and a ticket opened from it is still the board's. From
 * react-resource-view#136 on, the count is the entry's `badge`, and the entry
 * the package's own.
 */
export function BoardEntry({ menuItem }: { menuItem: MenuItemInterface }) {
  const { board } = useConsole()
  const scope = useScopeContext()?.scope
  const isActive = useIsActiveItemMenu(
    scope && { ...scope.defaultViewResourceContextParams, scope: scope.name }
  )
  const active = isActive(menuItem)
  const Icon = menuItem.icon
  const count = board.tickets.length

  return (
    <Link
      to={menuItem.href || "/"}
      data-active={active || undefined}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex w-full items-center gap-2 overflow-hidden rounded-xl px-3 py-2 text-left text-sm font-medium outline-hidden transition-colors",
        "hover:bg-accent hover:text-accent-foreground focus-visible:ring-ring/30 focus-visible:ring-2",
        "data-active:bg-primary data-active:text-primary-foreground [&_svg]:size-4 [&_svg]:shrink-0"
      )}
    >
      {Icon ? <Icon /> : null}
      <span className="truncate">{menuItem.name}</span>
      {count ? (
        <span className="ml-auto font-mono text-[0.7rem] tabular-nums opacity-80">{count}</span>
      ) : null}
    </Link>
  )
}

/* -- the end of the bar --------------------------------------------------- */

/* When the board last agreed with Notion, and whether anything does not.
 *
 * Green is "read a moment ago, and nothing is out of step". Amber is anything
 * worth a look: a move still waiting for Notion, one Notion refused or one it
 * had been changed under, an écart the last full read found, or a read that
 * failed. What exactly is under the pointer; the button beside it is the one
 * that does something about it. */
function useSyncSummary() {
  const synced = useSync()
  const t = useT()
  // Redrawn on a clock of its own: "12 s ago" that never moves is a lie.
  const [, tick] = React.useState(0)
  React.useEffect(() => {
    const timer = window.setInterval(() => tick((count) => count + 1), 5000)
    return () => window.clearInterval(timer)
  }, [])
  if (!synced?.synced_at) return null

  const seconds = Math.max(0, Math.round((Date.now() - new Date(synced.synced_at).getTime()) / 1000))
  const age =
    seconds < 60
      ? t("{{count}} s ago", { count: String(seconds) })
      : t("{{count}} min ago", { count: String(Math.round(seconds / 60)) })
  const troubled =
    Boolean(synced.error) || synced.drift + synced.pending + synced.failed + synced.conflicts > 0
  const clock = (at: string) => (at ? new Date(at).toLocaleTimeString() : "—")
  const said = [
    t("last read of Notion: {{at}}", { at: clock(synced.synced_at) }),
    t("whole board compared: {{at}}", { at: clock(synced.reconciled_at) }),
    synced.drift ? counted(synced.drift, "{{count}} gap found and corrected", "{{count}} gaps found and corrected") : "",
    synced.pending ? counted(synced.pending, "{{count}} move waiting for Notion", "{{count}} moves waiting for Notion") : "",
    synced.failed ? counted(synced.failed, "{{count}} move Notion refused", "{{count}} moves Notion refused") : "",
    synced.conflicts
      ? counted(synced.conflicts, "{{count}} ticket changed in Notion meanwhile", "{{count}} tickets changed in Notion meanwhile")
      : "",
    synced.error ? t("the last read failed: {{why}}", { why: synced.error }) : "",
  ].filter(Boolean)
  return { age, troubled, said }
}

function SyncLine() {
  const summary = useSyncSummary()
  const t = useT()
  if (!summary) return null
  const { age, troubled, said } = summary

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "flex items-center gap-1.5 px-2 font-mono text-[0.7rem]",
            troubled ? "text-tr-amber" : "text-muted-foreground"
          )}
        >
          <span
            className={cn("size-1.5 shrink-0 rounded-full", troubled ? "bg-tr-amber" : "bg-tr-green")}
          />
          <span>{t("synced {{age}}", { age })}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent>
        {said.map((line) => (
          <div key={line}>{line}</div>
        ))}
      </TooltipContent>
    </Tooltip>
  )
}

/** What the stream's dot says, in words. */
function useConnectionWord(): string {
  const { connection } = useStatus()
  const t = useT()
  return connection === "live"
    ? t("live")
    : connection === "connecting"
      ? t("connecting…")
      : t("reconnecting…")
}

/* What the tab says: where you are, so seven tabs of "Ponos" are not a row to
 * open one by one — the record on screen by its name, a page by the name of
 * its view, read the way the layout's own heading reads it. */
function useDocumentTitle() {
  const { viewName, recordTitle, recordId } = useAdminPageTitle()
  const t = useT()
  const here = recordTitle ?? (recordId ? `#${recordId}` : viewName ? t(viewName) : "")
  const { appName } = getPorts()
  React.useEffect(() => {
    document.title = here ? `${here} · ${appName}` : appName
  }, [here, appName])
}

/* The end of the bar, over every page: whether the stream is live, and the
 * ways in that are about the console rather than a page — install it, search
 * it, read what it has to tell you. The same at every width: the bar of a
 * phone has room for them, and what it has no room for is at the foot of the
 * sidebar, which a phone reaches by More. */
export function TopBarEnd() {
  const { connection } = useStatus()
  const word = useConnectionWord()
  const t = useT()
  const palette = hotkeyLabel("palette")
  useDocumentTitle()

  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn(
              "flex items-center gap-1.5 px-2 font-mono text-[0.7rem]",
              connection === "live" ? "text-tr-green" : "text-muted-foreground"
            )}
          >
            <span
              className={cn(
                "size-1.5 shrink-0 rounded-full",
                connection === "live" ? "bg-tr-green" : "bg-tr-amber animate-pulse"
              )}
            />
            <span>{word}</span>
          </span>
        </TooltipTrigger>
        <TooltipContent>{t("event stream")}</TooltipContent>
      </Tooltip>

      <InstallApp />

      {/* The palette's way in for a mouse, and where its shortcut is learnt. */}
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={openPalette}
            aria-label={t("Search")}
            aria-keyshortcuts={palette.aria}
          >
            <Search />
          </Button>
        </TooltipTrigger>
        <TooltipContent>{`${t("search a page, a project, a ticket")} · ${palette.label}`}</TooltipContent>
      </Tooltip>

      <NotificationBell />
    </>
  )
}

/* -- the foot of the sidebar ---------------------------------------------- */

/* The machine's own state, and the two gestures about the board as a whole
 * rather than about a page: reread it, change the light. The version — and,
 * the day a newer one is waiting, the button that installs it — and when the
 * board last agreed with Notion, over the two buttons. */
export function SidebarFooter() {
  const { refresh } = useConsole()
  const { theme, toggle } = useTheme()
  const t = useT()

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-1">
        <VersionBadge />
        <SyncLine />
      </div>
      <div className="flex items-center gap-1">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" onClick={refresh} aria-label={t("Resynchronise now")}>
              <RefreshCw />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {t("resynchronise now: the whole board read again, the refused moves sent again")}
          </TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={toggle}
              aria-label={theme === "dark" ? t("Light") : t("Dark")}
            >
              {theme === "dark" ? <Sun /> : <Moon />}
            </Button>
          </TooltipTrigger>
          <TooltipContent>{theme === "dark" ? t("go light") : t("go dark")}</TooltipContent>
        </Tooltip>
      </div>
    </div>
  )
}
