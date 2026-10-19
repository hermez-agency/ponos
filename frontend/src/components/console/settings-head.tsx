import * as React from "react"
import { Search } from "lucide-react"
import { useCurrentViewResourceContext, useNavigate } from "react-resource-view"

import { PageHead } from "@/components/console/frame"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { useT } from "@/lib/i18n"
import { search } from "@/lib/settings-search"
import {
  ask,
  asked,
  currentSettings,
  groupOf,
  sectionOf,
  showKeys,
  somethingIsEdited,
  useKeysShown,
  useSettingsRevision,
} from "@/lib/settings-store"
import { settingsHref } from "@/resources/settings"

/* The head of the settings page — see `resources/settings.tsx`, which
 * declares the page and fetches this with it. */

/** One answer of the search: a field, or a card that is a list of rows. */
interface Found {
  name: string
  words: string[]
  target: string
  group: string
  label: string
  where: string
}

/* A search over every field of every page, by what it is called, what it does
 * or its key — in the console's language and in the file's. A click opens the
 * page it is on, unfolds what hides it, and brings it into view. */
function SettingsSearch() {
  const t = useT()
  useSettingsRevision()
  const navigate = useNavigate()
  const { setViewResource } = useCurrentViewResourceContext()
  const [typed, setTyped] = React.useState("")
  const [open, setOpen] = React.useState(false)
  const box = React.useRef<HTMLDivElement>(null)
  const drawn = currentSettings()

  const items = React.useMemo<Found[]>(() => {
    if (!drawn) return []
    return drawn.sections.flatMap((section) => {
      const where = `${t(groupOf(section.group)?.title ?? "")} › ${t(section.title)}`
      if (section.pairs)
        return [
          {
            name: section.pairs,
            words: [t(section.title), t(section.blurb), section.title],
            target: section.key,
            group: section.group,
            label: t(section.title),
            where,
          },
        ]
      return section.fields.map((field) => ({
        name: field.variable ? `${field.name} ${field.variable}` : field.name,
        words: [t(field.label), t(field.help), field.label, field.help],
        target: field.name,
        group: section.group,
        label: t(field.label),
        where,
      }))
    })
  }, [drawn, t])

  const found = search(items, typed)

  const go = (item: Found) => {
    setTyped("")
    setOpen(false)
    ask(item.target)
    setViewResource((current) => ({ ...current, subResource: item.group }))
    void navigate({ to: settingsHref(item.group), replace: true, resetScroll: false })
  }

  return (
    <div
      ref={box}
      className="relative w-full sm:w-80"
      onBlur={(event) => {
        if (!box.current?.contains(event.relatedTarget as Node | null)) setOpen(false)
      }}
    >
      <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
      <Input
        type="search"
        aria-label={t("Search the settings")}
        placeholder={t("Search the settings")}
        className="pl-9"
        value={typed}
        onChange={(event) => {
          setTyped(event.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && found[0]) go(found[0])
          if (event.key === "Escape") {
            setTyped("")
            setOpen(false)
          }
        }}
      />
      {open && typed.trim().length >= 2 ? (
        <div
          role="listbox"
          aria-label={t("Settings found")}
          className="bg-popover text-popover-foreground absolute top-full right-0 left-0 z-40 mt-1 max-h-96 overflow-y-auto rounded-md border p-1 shadow-md"
        >
          {found.length ? (
            found.map((item) => (
              <button
                key={item.target}
                type="button"
                role="option"
                aria-selected={false}
                className="hover:bg-muted focus-visible:bg-muted flex w-full flex-col items-start rounded-sm px-2 py-1.5 text-left outline-none"
                onClick={() => go(item)}
              >
                <span className="text-sm font-medium">{item.label}</span>
                <span className="text-muted-foreground text-xs">{item.where}</span>
              </button>
            ))
          ) : (
            <p className="text-muted-foreground px-2 py-1.5 text-sm">{t("No setting by that name.")}</p>
          )}
        </div>
      ) : null}
    </div>
  )
}

/** The switch that shows `config.toml`'s keys under every field. */
function KeysSwitch() {
  const t = useT()
  const shown = useKeysShown()
  return (
    <label className="flex shrink-0 cursor-pointer items-center gap-2 text-sm">
      <Switch checked={shown} onCheckedChange={showKeys} />
      {t("Show keys")}
    </label>
  )
}

/** The two pages the file does not describe, named as their tabs are (see `resources/settings`). */
const PAGE_NAMES: Record<string, string> = { "github-app": "GitHub", mcp: "MCP" }

/* What sits above the tabs: where you are, how to find a setting, and whatever
 * `doctor` would refuse to start over. */
export function SettingsHead() {
  const { data, fetchData, subResource, setViewResource } = useCurrentViewResourceContext()
  const navigate = useNavigate()
  const t = useT()
  useSettingsRevision()
  const drawn = currentSettings()

  const latest = React.useRef(fetchData)
  latest.current = fetchData
  React.useEffect(() => {
    // Another tab saved, or `ponos config` did. Read it again — unless a page
    // is in the middle of an edit, which is not something to take away from you.
    const listener = () => {
      if (!somethingIsEdited()) void latest.current()
    }
    window.addEventListener("ponos:settings", listener)
    return () => window.removeEventListener("ponos:settings", listener)
  }, [])

  React.useEffect(() => {
    // Leaving the page with something typed and not saved: the browser asks.
    const warn = (event: BeforeUnloadEvent) => {
      if (somethingIsEdited()) event.preventDefault()
    }
    window.addEventListener("beforeunload", warn)
    return () => window.removeEventListener("beforeunload", warn)
  }, [])

  React.useEffect(() => {
    // An address that names a card rather than a page — a link written before
    // there were pages, or one that means "the notifications" wherever they
    // are: the page it is on, scrolled to it.
    if (!drawn || !subResource || groupOf(subResource)) return
    const section = sectionOf(subResource)
    if (!section) return
    if (asked() !== section.key) ask(section.key)
    setViewResource((current) => ({ ...current, subResource: section.group }))
    void navigate({ to: settingsHref(section.group), replace: true })
  }, [drawn, subResource, navigate, setViewResource])

  // The bar's breadcrumb names the record, and the record is the file: it
  // said "Settings › config.toml" whatever page was open. Named after the page
  // instead — "Settings › General" — and named again when another is opened,
  // when the file is read again or when the console changes language.
  const page = subResource ?? drawn?.groups[0]?.key ?? ""
  const named = PAGE_NAMES[page] ?? groupOf(page)?.title
  const name = named ? t(named) : undefined
  const shown = (data as { name?: unknown } | undefined)?.name
  React.useEffect(() => {
    if (!name || shown === name) return
    setViewResource((current) =>
      current.data ? { ...current, data: { ...current.data, name } } : current
    )
  }, [name, shown, setViewResource])

  if (!drawn)
    return <p className="text-muted-foreground text-sm">{t("Reading the configuration…")}</p>

  return (
    <>
      <PageHead
        title={t("Configure the runner")}
        action={
          <div className="flex w-full flex-wrap items-center gap-x-4 gap-y-2 sm:w-auto">
            <SettingsSearch />
            <KeysSwitch />
          </div>
        }
      />
      {drawn.problem ? (
        <Alert variant="destructive" className="mb-4">
          <AlertDescription>{drawn.problem}</AlertDescription>
        </Alert>
      ) : null}
    </>
  )
}

