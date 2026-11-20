import * as React from "react"
import { Download, FileArchive, Upload } from "lucide-react"

import { ConfirmDialog } from "@/components/console/confirm-dialog"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { api, why } from "@/lib/api"
import { Worded, counted, useT } from "@/lib/i18n"
import { settingsFrench } from "@/lib/settings-store"
import type { Imported, TransferCategory } from "@/lib/types"

/* The settings' Export & import page — see `transfer.py`.
 *
 * An export is one click and a download. An import is two calls with the same
 * file: the first reads it and says what it holds and what conflicts (writing
 * nothing), the second imports what is ticked. The file is not kept on the
 * server between the two — the page holds it, and sends it again.
 */

type Key = TransferCategory["key"]

/* The categories, in the server's order, with what each carries and whether
 * it is ticked by default: the conversations are not. */
const CATEGORIES: { key: Key; label: string; detail: string; ticked: boolean }[] = [
  { key: "settings", label: "Settings", detail: "config.toml, without its secrets", ticked: true },
  { key: "projects", label: "Projects", detail: "and their own settings: validation, models, rights", ticked: true },
  { key: "context", label: "Context", detail: "the standing context and the agents", ticked: true },
  { key: "memories", label: "Memories", detail: "every scope", ticked: true },
  { key: "goals", label: "Goals", detail: "", ticked: true },
  { key: "schedules", label: "Recurrences", detail: "imported switched off", ticked: true },
  { key: "ideas", label: "Ideas", detail: "", ticked: true },
  { key: "skills", label: "Skills", detail: "and their files", ticked: true },
  {
    key: "tickets",
    label: "Tickets",
    detail: "mission, result, journal, status, comments and history",
    ticked: true,
  },
  { key: "conversations", label: "Conversations", detail: "with the assistant", ticked: false },
]

function labelOf(key: string) {
  return CATEGORIES.find((category) => category.key === key)?.label ?? key
}

function Choice({
  checked,
  onChange,
  label,
  detail,
  testId,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
  detail: string
  testId: string
}) {
  const t = useT()
  return (
    <label className="flex cursor-pointer items-start gap-2.5 py-1 text-sm" data-testid={testId}>
      <Checkbox checked={checked} onCheckedChange={(value) => onChange(value === true)} className="mt-0.5" />
      <span>
        <span className="font-medium">{t(label)}</span>
        {detail ? <span className="text-muted-foreground"> — {t(detail)}</span> : null}
      </span>
    </label>
  )
}

function ExportCard() {
  const t = useT()
  const [ticked, setTicked] = React.useState<Set<Key>>(
    () => new Set(CATEGORIES.filter((category) => category.ticked).map((category) => category.key))
  )
  const [busy, setBusy] = React.useState(false)
  const [said, setSaid] = React.useState<{ text: string; bad: boolean } | null>(null)

  const toggle = (key: Key, on: boolean) =>
    setTicked((current) => {
      const next = new Set(current)
      if (on) next.add(key)
      else next.delete(key)
      return next
    })

  const run = async () => {
    setBusy(true)
    setSaid(null)
    try {
      const { blob, name } = await api.exportArchive(
        CATEGORIES.filter((category) => ticked.has(category.key)).map((category) => category.key)
      )
      const address = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = address
      link.download = name
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.setTimeout(() => URL.revokeObjectURL(address), 10_000)
      setSaid({ text: t("{{name}} downloaded.", { name }), bad: false })
    } catch (error) {
      setSaid({ text: why(error), bad: true })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card data-card="export">
      <CardHeader>
        <CardTitle className="text-base">{t("Export")}</CardTitle>
        <CardDescription className="text-[13px]">
          {t("This Ponos in one archive, to import on another machine, after a reinstallation, or to keep.")}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="grid gap-x-6 sm:grid-cols-2">
          {CATEGORIES.map((category) => (
            <Choice
              key={category.key}
              checked={ticked.has(category.key)}
              onChange={(on) => toggle(category.key, on)}
              label={category.label}
              detail={category.detail}
              testId={`export-${category.key}`}
            />
          ))}
        </div>
        <p className="text-muted-foreground text-[13px]" data-testid="export-never">
          {t(
            "Never exported, whatever is ticked: the vault and every secret — API keys, tokens, passwords, session cookies. The archive lists their names only, to know what to type again."
          )}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => void run()} disabled={busy || !ticked.size} data-testid="export-run">
            <Download />
            {busy ? t("Exporting…") : t("Export")}
          </Button>
          {said ? (
            <span className={said.bad ? "text-destructive text-sm" : "text-muted-foreground text-sm"}>{said.text}</span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}

/* What an archive holds — or what its import did — one line a category. */
function Outcomes({ read, chosen, onToggle }: { read: Imported; chosen?: Set<string>; onToggle?: (key: string, on: boolean) => void }) {
  const t = useT()
  return (
    <ul className="flex flex-col divide-y text-sm" data-testid="import-categories">
      {read.categories.map((category) => {
        const line = read.applied
          ? t("{{imported}} imported, {{ignored}} already here", {
              imported: String(category.imported),
              ignored: String(category.ignored),
            })
          : t("{{count}} in the archive — {{imported}} to import, {{ignored}} already here", {
              count: String(category.count),
              imported: String(category.imported),
              ignored: String(category.ignored),
            })
        return (
          <li key={category.key} className="flex flex-col gap-1 py-2" data-testid={`import-${category.key}`}>
            <span className="flex items-center gap-2.5">
              {onToggle && chosen ? (
                <Checkbox
                  checked={chosen.has(category.key)}
                  onCheckedChange={(value) => onToggle(category.key, value === true)}
                  aria-label={t(labelOf(category.key))}
                />
              ) : null}
              <span className="font-medium">{t(labelOf(category.key))}</span>
              <span className="text-muted-foreground">{line}</span>
            </span>
            {category.conflicts.length ? (
              <span className="text-amber-700 dark:text-amber-400 text-[13px]" data-testid={`conflicts-${category.key}`}>
                {counted(
                  category.conflicts.length,
                  "{{count}} conflict, left as it is here:",
                  "{{count}} conflicts, left as they are here:"
                )}{" "}
                {category.conflicts.slice(0, 12).join(", ")}
                {category.conflicts.length > 12 ? "…" : ""}
              </span>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}

/* The secrets the archive did not carry, by name: what to type again. */
function ToTypeAgain({ read }: { read: Imported }) {
  const t = useT()
  const names = [
    ...read.secrets.vault.map((entry) => entry.name),
    ...read.secrets.config.map((entry) => `${entry.name} (${entry.setting})`),
    ...read.secrets.own.filter((name) => !read.secrets.config.some((entry) => entry.name === name)),
  ]
  if (!names.length) return null
  return (
    <p className="text-[13px]" data-testid="import-secrets">
      <span className="font-medium">{t("To type again, in Context → Vault or the settings:")}</span>{" "}
      <span className="font-mono">{names.join(", ")}</span>
    </p>
  )
}

function ImportCard() {
  const t = useT()
  const [file, setFile] = React.useState<File | null>(null)
  const [preview, setPreview] = React.useState<Imported | null>(null)
  const [chosen, setChosen] = React.useState<Set<string>>(new Set())
  const [mode, setMode] = React.useState<"merge" | "replace">("merge")
  const [done, setDone] = React.useState<Imported | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [problem, setProblem] = React.useState("")
  const input = React.useRef<HTMLInputElement>(null)

  const read = async (picked: File, wanted: "merge" | "replace" = mode, fresh = true) => {
    setFile(picked)
    setDone(null)
    setProblem("")
    setBusy(true)
    try {
      const said = await api.importArchive(picked, { mode: wanted })
      setPreview(said)
      if (fresh) setChosen(new Set(said.available))
    } catch (error) {
      setPreview(null)
      setProblem(why(error))
    } finally {
      setBusy(false)
    }
  }

  const apply = async () => {
    if (!file) return false
    setBusy(true)
    setProblem("")
    try {
      const said = await api.importArchive(file, {
        categories: [...chosen],
        mode,
        apply: true,
        confirm: mode === "replace",
      })
      setDone(said)
      setPreview(null)
      return true
    } catch (error) {
      setProblem(why(error))
      return false
    } finally {
      setBusy(false)
    }
  }

  const toggle = (key: string, on: boolean) =>
    setChosen((current) => {
      const next = new Set(current)
      if (on) next.add(key)
      else next.delete(key)
      return next
    })

  const switchMode = (wanted: "merge" | "replace") => {
    setMode(wanted)
    if (file) void read(file, wanted, false)
  }

  const importButton = (
    <Button size="sm" disabled={busy || !chosen.size} data-testid="import-run" variant={mode === "replace" ? "destructive" : "default"}>
      <Upload />
      {busy ? t("Importing…") : mode === "replace" ? t("Replace and import") : t("Import")}
    </Button>
  )

  return (
    <Card data-card="import">
      <CardHeader>
        <CardTitle className="text-base">{t("Import")}</CardTitle>
        <CardDescription className="text-[13px]">
          {t("An archive of Ponos's Export. Nothing starts on its own: ready and running tickets arrive as drafts, recurrences switched off.")}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div
          className="border-input text-muted-foreground flex flex-col items-center gap-2 rounded-md border border-dashed px-4 py-6 text-center text-sm"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault()
            const dropped = event.dataTransfer.files[0]
            if (dropped) void read(dropped)
          }}
          data-testid="import-drop"
        >
          <FileArchive className="size-5" />
          <span>{file ? file.name : t("Drop a ponos-export-….zip here")}</span>
          <Button size="xs" variant="outline" onClick={() => input.current?.click()} disabled={busy}>
            {t("Choose a file")}
          </Button>
          <input
            ref={input}
            type="file"
            accept=".zip,application/zip"
            className="hidden"
            data-testid="import-file"
            onChange={(event) => {
              const picked = event.target.files?.[0]
              event.target.value = ""
              if (picked) void read(picked)
            }}
          />
        </div>
        {problem ? (
          <Alert variant="destructive">
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        ) : null}
        {preview ? (
          <div className="flex flex-col gap-3" data-testid="import-preview">
            <p className="text-muted-foreground text-[13px]">
              {t("Exported by Ponos {{version}} on {{date}}.", {
                version: preview.ponos,
                date: preview.created.slice(0, 16).replace("T", " "),
              })}
            </p>
            <Outcomes read={preview} chosen={chosen} onToggle={toggle} />
            <fieldset className="flex flex-col gap-1.5 text-sm">
              <legend className="mb-1 font-medium">{t("How")}</legend>
              <label className="flex cursor-pointer items-start gap-2">
                <input type="radio" name="import-mode" checked={mode === "merge"} onChange={() => switchMode("merge")} className="mt-1" />
                <span>
                  <span className="font-medium">{t("Merge")}</span>
                  <span className="text-muted-foreground"> — {t("add what is missing, replace nothing; conflicts are left as they are")}</span>
                </span>
              </label>
              <label className="flex cursor-pointer items-start gap-2">
                <input
                  type="radio"
                  name="import-mode"
                  checked={mode === "replace"}
                  onChange={() => switchMode("replace")}
                  className="mt-1"
                  data-testid="import-replace"
                />
                <span>
                  <span className="font-medium">{t("Replace")}</span>
                  <span className="text-muted-foreground"> — {t("empty the ticked categories first; the database is copied beside itself before")}</span>
                </span>
              </label>
            </fieldset>
            <ToTypeAgain read={preview} />
            <div>
              {mode === "replace" ? (
                <ConfirmDialog
                  title={t("Replace what this Ponos holds?")}
                  description={t(
                    "The ticked categories are emptied, then filled with the archive's. A copy of the database is taken first."
                  )}
                  destructive
                  confirm={t("Replace and import")}
                  onConfirm={apply}
                  trigger={importButton}
                />
              ) : (
                React.cloneElement(importButton, { onClick: () => void apply() })
              )}
            </div>
          </div>
        ) : null}
        {done ? (
          <div className="flex flex-col gap-3" data-testid="import-done">
            <Alert variant="success">
              <AlertDescription>{t("Imported. Nothing was started: move the tickets and switch the recurrences back on yourself.")}</AlertDescription>
            </Alert>
            <Outcomes read={{ ...done, categories: done.categories.filter((category) => done.chosen.includes(category.key)) }} />
            {done.backup ? (
              <p className="text-muted-foreground text-[13px]">
                {t("The database as it was:")} <span className="font-mono break-all">{done.backup}</span>
              </p>
            ) : null}
            <ToTypeAgain read={done} />
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

export function TransferPage() {
  return (
    <Worded words={settingsFrench}>
      <div className="flex min-w-0 flex-col gap-5">
        <ExportCard />
        <ImportCard />
      </div>
    </Worded>
  )
}
