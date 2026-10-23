import * as React from "react"
import {
  Brain,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Loader2,
  ShieldQuestion,
  Wrench,
  XCircle,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Markdown } from "@/components/console/markdown"
import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

import {
  toolStatus,
  type TextPart,
  type ThinkingPart,
  type ToolCallPart,
  type ToolResultPart,
  type ToolStatus,
} from "./chat-types"

/* The parts of a message, from Brand Assets' chat kit (`chat-parts` in the
 * `hermez` registry), as this console draws them:
 *
 * - the words go through `t()`, the kit says them in French only;
 * - the badges take the variants this console's `Badge` has — the kit's
 *   `success`, `info` and `warning` are not in it, and the icon beside each
 *   label says what the colour used to;
 * - text is drawn by the console's own `Markdown`, the one every other
 *   message of the console is drawn with, instead of the kit's `ChatMarkdown`.
 */

/** The caret of a text still being written. */
function Caret() {
  return (
    <span
      aria-hidden
      className="bg-primary ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 rounded-sm motion-safe:animate-pulse"
    />
  )
}

/** A part of text, in Markdown; the caret blinks while it arrives. */
function TextPartView({
  part,
  streaming,
  className,
}: {
  part: TextPart
  streaming?: boolean
  className?: string
}) {
  return (
    <div data-slot="chat-text-part" className={className}>
      <Markdown text={part.content} className="text-message font-medium" />
      {streaming && <Caret />}
    </div>
  )
}

/** What the model thought, folded. Open while it arrives. */
function ThinkingPartView({
  part,
  streaming,
  defaultOpen,
  className,
}: {
  part: ThinkingPart
  streaming?: boolean
  defaultOpen?: boolean
  className?: string
}) {
  const t = useT()
  const [open, setOpen] = React.useState(defaultOpen ?? false)
  const id = React.useId()

  return (
    <div
      data-slot="chat-thinking-part"
      className={cn("border-border bg-muted/40 rounded-xl border text-sm", className)}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
        className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/30 flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left outline-none focus-visible:ring-3"
      >
        <ChevronRight
          className={cn("size-4 shrink-0 motion-safe:transition-transform", open && "rotate-90")}
          aria-hidden
        />
        <Brain className="size-4 shrink-0" aria-hidden />
        <span className="font-medium">{streaming ? t("Thinking…") : t("Thinking")}</span>
      </button>
      {open && (
        <div
          id={id}
          className="border-border text-muted-foreground border-t px-3 py-2 whitespace-pre-wrap"
        >
          {part.content}
          {streaming && <Caret />}
        </div>
      )}
    </div>
  )
}

const statuses: Record<
  ToolStatus,
  {
    label: string
    icon: React.ReactNode
    variant: React.ComponentProps<typeof Badge>["variant"]
  }
> = {
  pending: { label: "Waiting", icon: <CircleDashed />, variant: "secondary" },
  running: { label: "Running", icon: <Loader2 className="motion-safe:animate-spin" />, variant: "outline" },
  done: { label: "Done", icon: <CheckCircle2 />, variant: "secondary" },
  error: { label: "Failed", icon: <XCircle />, variant: "destructive" },
  approval: { label: "Approval needed", icon: <ShieldQuestion />, variant: "default" },
  denied: { label: "Denied", icon: <XCircle />, variant: "secondary" },
}

/** The state of a tool call: an icon and a label, never the colour alone. */
function ToolStatusBadge({ status }: { status: ToolStatus }) {
  const t = useT()
  const { label, icon, variant } = statuses[status]
  return (
    <Badge variant={variant} data-status={status}>
      {icon}
      {t(label)}
    </Badge>
  )
}

/** A JSON laid out, or the text as it is when it is not JSON (or not yet). */
function pretty(text: string) {
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text
  }
}

/** A tool asking to be approved, with its Approve and Deny buttons. */
function ToolApproval({
  toolName,
  onRespond,
  className,
}: {
  toolName: string
  onRespond: (approved: boolean) => void
  className?: string
}) {
  const t = useT()
  return (
    <div
      role="group"
      aria-label={t("Approval of the tool {{name}}", { name: toolName })}
      data-slot="chat-tool-approval"
      className={cn(
        "border-border bg-accent flex flex-wrap items-center justify-between gap-3 border-t px-3 py-2",
        className
      )}
    >
      <p className="text-sm">
        {t("The assistant asks to use")} <code className="font-mono">{toolName}</code>.
      </p>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={() => onRespond(false)}>
          {t("Deny")}
        </Button>
        <Button size="sm" onClick={() => onRespond(true)}>
          {t("Approve")}
        </Button>
      </div>
    </div>
  )
}

/** A tool call: its name, its state, its arguments, and the approval it waits for. */
function ToolCallPartView({
  part,
  result,
  onApprove,
  className,
}: {
  part: ToolCallPart
  /** The result of this call, once it has come: it sets the state shown. */
  result?: ToolResultPart
  /** Called with the id of the approval request, and the answer. */
  onApprove?: (approvalId: string, approved: boolean) => void
  className?: string
}) {
  const t = useT()
  const status = toolStatus(part, result)
  const id = React.useId()

  return (
    <div
      data-slot="chat-tool-call"
      data-status={status}
      className={cn("border-border bg-card overflow-hidden rounded-xl border text-sm", className)}
    >
      <div className="flex items-center justify-between gap-3 px-3 py-2">
        <span className="flex min-w-0 items-center gap-2">
          <Wrench className="text-muted-foreground size-4 shrink-0" aria-hidden />
          <span className="truncate font-mono font-medium">{part.name}</span>
        </span>
        <ToolStatusBadge status={status} />
      </div>
      {part.arguments && (
        <pre
          id={id}
          tabIndex={0}
          aria-label={t("Arguments of {{name}}", { name: part.name })}
          className="border-border bg-muted/40 focus-visible:ring-ring/30 max-h-48 overflow-auto border-t px-3 py-2 font-mono text-xs leading-relaxed outline-none focus-visible:ring-3"
        >
          {pretty(part.arguments)}
        </pre>
      )}
      {status === "approval" && part.approval && onApprove && (
        <ToolApproval
          toolName={part.name}
          onRespond={(approved) => onApprove(part.approval!.id, approved)}
        />
      )}
    </div>
  )
}

/** What a tool answered, or its failure. */
function ToolResultPartView({
  part,
  toolName,
  className,
}: {
  part: ToolResultPart
  toolName?: string
  className?: string
}) {
  const t = useT()
  const failed = part.state === "error"

  return (
    <div
      data-slot="chat-tool-result"
      data-state={part.state}
      className={cn(
        "bg-card overflow-hidden rounded-xl border text-sm",
        failed ? "border-destructive/40" : "border-border",
        className
      )}
    >
      <div className="text-muted-foreground flex items-center gap-2 px-3 py-2">
        {failed ? (
          <XCircle className="text-destructive size-4 shrink-0" aria-hidden />
        ) : part.state === "streaming" ? (
          <Loader2 className="size-4 shrink-0 motion-safe:animate-spin" aria-hidden />
        ) : (
          <CheckCircle2 className="text-primary size-4 shrink-0" aria-hidden />
        )}
        <span className="text-foreground font-medium">{failed ? t("Failed") : t("Result")}</span>
        {toolName && <code className="font-mono text-xs">{toolName}</code>}
      </div>
      <pre
        tabIndex={0}
        aria-label={
          toolName ? t("Result of {{name}}", { name: toolName }) : t("Result of the tool")
        }
        className={cn(
          "focus-visible:ring-ring/30 max-h-64 overflow-auto border-t px-3 py-2 font-mono text-xs leading-relaxed whitespace-pre-wrap outline-none focus-visible:ring-3",
          failed
            ? "border-destructive/40 bg-destructive/10 text-destructive"
            : "border-border bg-muted/40"
        )}
      >
        {failed ? part.error || part.content : pretty(part.content)}
        {part.state === "streaming" && <Caret />}
      </pre>
    </div>
  )
}

export {
  Caret,
  TextPartView,
  ThinkingPartView,
  ToolApproval,
  ToolCallPartView,
  ToolResultPartView,
  ToolStatusBadge,
}
