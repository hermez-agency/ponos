import * as React from "react"
import { Link } from "react-resource-view"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { splitHelp } from "@/lib/settings-search"
import type { ProjectSettings, TicketKind, ValidationField } from "@/lib/types"
import { settingsHref } from "@/resources/settings"

import { MoreHelp } from "./settings-bits"
import { Rich } from "./text"

/* What a project decides for itself, against the settings of the whole runner.
 *
 * A tab of cards, the way the settings page is a column of them, so that the
 * next setting a project may hold is one more card here. The first is its
 * automatic validation: off, the project follows the global switches, shown as
 * they stand and greyed, with the way to where they are changed; on, it has
 * four switches of its own, worded as the global card words them — the server
 * sends the same fields — and started from what the global ones said.
 *
 * A switch saves as it is flipped, as the switches of a phone's settings do:
 * there is nothing to type here, and a bar saying "unsaved" under four
 * switches would be one more thing to forget.
 */

export function ProjectSettingsTab({ project }: { project: string }) {
  const t = useT()
  const [settings, setSettings] = React.useState<ProjectSettings | null>(null)
  const [problem, setProblem] = React.useState("")
  const [saving, setSaving] = React.useState(false)

  const read = React.useCallback(() => {
    api.projectSettings(project).then(
      (read) => {
        setSettings(read)
        setProblem("")
      },
      (error) => setProblem(why(error))
    )
  }, [project])

  React.useEffect(() => {
    read()
    // The global switches changed in another tab, or another tab changed these.
    window.addEventListener("ponos:settings", read)
    return () => window.removeEventListener("ponos:settings", read)
  }, [read])

  const save = async (own: boolean, values?: Record<TicketKind, boolean>) => {
    setSaving(true)
    try {
      setSettings(await api.saveProjectSettings(project, { validation: { own, values } }))
      setProblem("")
    } catch (error) {
      setProblem(why(error))
    } finally {
      setSaving(false)
    }
  }

  const saveIdeas = async (enabled: boolean) => {
    setSaving(true)
    try {
      setSettings(await api.saveProjectSettings(project, { ideas: { enabled } }))
      setProblem("")
    } catch (error) {
      setProblem(why(error))
    } finally {
      setSaving(false)
    }
  }

  const saveLocalCi = async (enabled: boolean, command: string) => {
    setSaving(true)
    try {
      setSettings(await api.saveProjectSettings(project, { local_ci: { enabled, command } }))
      setProblem("")
    } catch (error) {
      setProblem(why(error))
    } finally {
      setSaving(false)
    }
  }

  if (!settings)
    return problem ? (
      <p className="text-destructive text-sm">{problem}</p>
    ) : (
      <div className="flex max-w-[720px] flex-col gap-2">
        <Skeleton className="h-6 w-1/3" />
        <Skeleton className="h-24 w-full" />
      </div>
    )

  const { validation, ideas, local_ci: localCi } = settings
  return (
    <div className="flex max-w-[720px] min-w-0 flex-col gap-5" data-slot="project-settings">
      {problem ? (
        <Alert variant="destructive">
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      ) : null}
      <Card data-card="project-validation" className="gap-0 py-0">
        <CardHeader className="gap-1 px-5 pt-5 pb-2 sm:px-6">
          <CardTitle className="text-base">{t("Automatic validation")}</CardTitle>
          <CardDescription className="text-[13px] leading-relaxed">
            <Rich
              text={t(
                "Skip your review for some types of ticket: once the session succeeds, the runner validates it itself and says so. A failed or blocked ticket never is."
              )}
            />
          </CardDescription>
        </CardHeader>
        <CardContent className="px-5 pb-4 sm:px-6">
          <div className="divide-y">
            <Row
              id="project-own-validation"
              label={t("Its own automatic validation")}
              line={
                validation.own
                  ? t("This project's switches apply to its tickets, whatever the global settings say.")
                  : t("Off: this project follows the global settings.")
              }
              checked={validation.own}
              disabled={saving}
              // Turned on, the project starts from what applied a moment ago.
              onChange={(own) => void save(own, own ? validation.global : undefined)}
            />
            {!validation.own ? (
              <p className="text-muted-foreground py-3 text-[13px]" data-slot="project-validation-global">
                {t("The global settings that apply, read only.")}{" "}
                <Link to={settingsHref("validation")} className="text-foreground underline underline-offset-2">
                  {t("Change them in the global settings")}
                </Link>
              </p>
            ) : null}
            {validation.fields.map((field) => (
              <KindRow
                key={field.kind}
                field={field}
                checked={validation.values[field.kind]}
                // Read only while the project follows the file: what is shown is the
                // file's, and is changed there.
                disabled={!validation.own || saving}
                onChange={(on) => void save(true, { ...validation.values, [field.kind]: on })}
              />
            ))}
          </div>
        </CardContent>
      </Card>
      <Card data-card="project-ideas" className="gap-0 py-0">
        <CardHeader className="gap-1 px-5 pt-5 pb-2 sm:px-6">
          <CardTitle className="text-base">{t("Ideas on a schedule")}</CardTitle>
          <CardDescription className="text-[13px] leading-relaxed">
            {t(
              "Ponos can look for ideas for this project on its own, at the times set in the Ideas page's Settings. The button on this page works whatever is set here."
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="px-5 pb-4 sm:px-6">
          <Row
            id="project-ideas-scheduled"
            label={t("Find ideas for this project on the schedule")}
            line={
              ideas.schedule === "off"
                ? t("No schedule is set: only the button finds ideas.")
                : ideas.own
                  ? t("This project's own choice, whatever the general settings say.")
                  : t("Follows the general settings.")
            }
            checked={ideas.enabled}
            disabled={saving}
            onChange={(enabled) => void saveIdeas(enabled)}
          />
        </CardContent>
      </Card>
      <LocalCiCard key={localCi.command} localCi={localCi} saving={saving} onSave={saveLocalCi} />
    </div>
  )
}

/* The project's local CI: whether it runs before its pull requests — greyed,
 * with the reason, while Docker does not answer here — and what runs it. The
 * switch saves as it is flipped; the command, which is typed, with its button. */
function LocalCiCard({
  localCi,
  saving,
  onSave,
}: {
  localCi: ProjectSettings["local_ci"]
  saving: boolean
  onSave: (enabled: boolean, command: string) => Promise<void>
}) {
  const t = useT()
  const [command, setCommand] = React.useState(localCi.command)
  const changed = command.trim() !== localCi.command
  return (
    <Card data-card="project-local-ci" className="gap-0 py-0">
      <CardHeader className="gap-1 px-5 pt-5 pb-2 sm:px-6">
        <CardTitle className="text-base">{t("Local CI before pull request")}</CardTitle>
        <CardDescription className="text-[13px] leading-relaxed">
          {t(
            "The project's CI runs on this machine, in Docker, once the session has committed; a red one goes back to the session to be fixed before anything is pushed. The CI on GitHub still runs."
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="px-5 pb-4 sm:px-6">
        <p className="pt-1 pb-2 text-[13px]" data-slot="docker-state">
          <span className={localCi.docker ? "font-semibold text-emerald-700 dark:text-emerald-400" : "font-semibold"}>
            {localCi.docker ? t("Docker detected") : t("Docker missing")}
          </span>{" "}
          <span className="text-muted-foreground">
            {localCi.unavailable ? t(localCi.unavailable) : t("The local CI can be turned on.")}
          </span>
        </p>
        <div className="divide-y">
          <Row
            id="project-local-ci"
            label={t("Run the local CI before the pull request")}
            line={
              localCi.own
                ? t("This project's own choice, against the global setting.")
                : t("Follows the global setting, in Code and repositories.")
            }
            checked={localCi.enabled}
            // Greyed while Docker is missing — but one left on can still be turned off.
            disabled={saving || (!localCi.docker && !localCi.enabled)}
            onChange={(enabled) => void onSave(enabled, localCi.command)}
          />
          <form
            className="py-4"
            data-field="project-local-ci-command"
            onSubmit={(event) => {
              event.preventDefault()
              if (changed) void onSave(localCi.enabled, command.trim())
            }}
          >
            <Label htmlFor="project-local-ci-command" className="leading-snug font-semibold">
              {t("CI command")}
            </Label>
            <p className="text-muted-foreground mt-1 text-[13px] leading-snug">
              <Rich
                text={t(
                  "Run from the root of the repository, e.g. `make ci`. Empty: the GitHub workflows, through `act` when it is installed."
                )}
              />
            </p>
            <div className="mt-2.5 flex gap-2">
              <Input
                id="project-local-ci-command"
                className="font-mono text-[13px]"
                autoComplete="off"
                spellCheck={false}
                placeholder="make ci"
                value={command}
                onChange={(event) => setCommand(event.target.value)}
              />
              <Button type="submit" variant="outline" disabled={!changed || saving}>
                {t("Save")}
              </Button>
            </div>
          </form>
        </div>
      </CardContent>
    </Card>
  )
}

/* A label in bold, one line under it, the switch on the right: the settings
 * page's own row, for a switch that is not a field of its form. */
function Row({
  id,
  label,
  line,
  help,
  checked,
  disabled,
  onChange,
}: {
  id: string
  label: string
  line: string
  help?: ValidationField
  checked: boolean
  disabled: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-4 first:pt-1" data-field={id}>
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-1">
          <Label htmlFor={id} className="leading-snug font-semibold">
            {label}
          </Label>
          {help ? <MoreHelp field={help} /> : null}
        </div>
        {line ? (
          <p className="text-muted-foreground mt-1 text-[13px] leading-snug">
            <Rich text={line} />
          </p>
        ) : null}
      </div>
      <div className="shrink-0 pt-0.5">
        <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onChange} />
      </div>
    </div>
  )
}

function KindRow({
  field,
  checked,
  disabled,
  onChange,
}: {
  field: ValidationField
  checked: boolean
  disabled: boolean
  onChange: (checked: boolean) => void
}) {
  const t = useT()
  const [line] = splitHelp(t(field.help))
  return (
    <Row
      id={`project-${field.name.replaceAll(".", "-")}`}
      label={t(field.label)}
      line={line}
      help={field}
      checked={checked}
      disabled={disabled}
      onChange={onChange}
    />
  )
}
