import * as React from "react"
import { Check, CircleAlert, CircleCheck, Copy, Terminal } from "lucide-react"

import { Rich } from "@/components/console/text"
import { explain, type Explained } from "@/lib/said"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { copy } from "@/lib/copy"
import { useT } from "@/lib/i18n"
import type { Provisioned } from "@/lib/types"

export function StepCard({
  title,
  blurb,
  children,
  footer,
}: {
  title: string
  blurb: string
  children: React.ReactNode
  footer?: React.ReactNode
}) {
  return (
    <Card className="gap-5">
      <CardHeader>
        <CardTitle className="text-lg">{title}</CardTitle>
        <CardDescription className="leading-relaxed">
          <Rich text={blurb} />
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">{children}</CardContent>
      {footer ? <div className="flex flex-wrap justify-end gap-2 px-6">{footer}</div> : null}
    </Card>
  )
}

export function Field({
  id,
  label,
  hint,
  ...props
}: { id: string; label: string; hint?: string } & React.ComponentProps<typeof Input>) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} name={id} autoComplete="off" spellCheck={false} {...props} />
      {hint ? (
        <p className="text-muted-foreground text-xs leading-relaxed">
          <Rich text={hint} />
        </p>
      ) : null}
    </div>
  )
}

/** A sentence that went well or did not, said where the gesture was made. */
export function Said({ ok, text }: { ok: boolean; text: string }) {
  if (!text) return null
  return (
    <Alert variant={ok ? "success" : "destructive"} role="status">
      {ok ? <CircleCheck /> : <CircleAlert />}
      <AlertDescription>
        {ok ? <Rich text={text} /> : <Explaining note={explain(text)} />}
      </AlertDescription>
    </Alert>
  )
}

/** What the server said, in the page's language — its technical words behind a "Details". */
export function Explaining({ note }: { note: Explained }) {
  const t = useT()
  const said = Object.keys(note.params).length ? t(note.key, note.params) : t(note.key)
  return (
    <>
      <Rich text={said} />
      {note.detail ? (
        <details className="mt-1 text-xs">
          <summary className="cursor-pointer">{t("Details")}</summary>
          <code className="font-mono break-all whitespace-pre-wrap">{note.detail}</code>
        </details>
      ) : null}
    </>
  )
}

/** A command to type somewhere else, with the button that copies it. */
export function Command({ text }: { text: string }) {
  const t = useT()
  const [copied, setCopied] = React.useState(false)
  return (
    <div className="bg-muted flex items-center gap-2 rounded-lg border px-3 py-2">
      <Terminal className="text-muted-foreground size-4 shrink-0" />
      <code className="min-w-0 flex-1 font-mono text-sm break-all">{text}</code>
      <Button
        type="button"
        size="xs"
        variant="ghost"
        onClick={() => {
          void copy(text).then(setCopied)
        }}
        aria-label={t("Copy")}
      >
        {copied ? <Check /> : <Copy />}
      </Button>
    </div>
  )
}

/** What a step that built something did, one line each. */
export function Report({ done }: { done: Provisioned | null }) {
  if (!done) return null
  return (
    <>
      {done.steps.length ? (
        <ul className="text-muted-foreground list-disc pl-5 text-xs leading-relaxed">
          {done.steps.map(([verb, what], index) => (
            <li key={index}>
              <span className="text-tr-green font-medium">{verb}</span> {what}
            </li>
          ))}
        </ul>
      ) : null}
      {done.problem ? <Said ok={false} text={done.problem} /> : null}
    </>
  )
}
