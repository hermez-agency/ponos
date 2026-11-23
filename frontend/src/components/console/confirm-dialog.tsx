import * as React from "react"
import { Loader2Icon } from "lucide-react"

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { enterConfirms, enterLabel } from "@/lib/confirm"
import { isMac } from "@/lib/hotkeys"
import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

/* The one window the console asks "are you sure?" in.
 *
 * Every confirmation goes through it, so that they all answer the keyboard the
 * same way: Enter does the main thing, Escape cancels, and the badge in each
 * button says so (hidden where there is no keyboard to press them on). The
 * focus opens on the main button rather than on Cancel, so that Enter is what
 * it looks like; while the main button cannot be pressed yet — a name still to
 * type — it goes to the first field instead. Where the main thing loses work
 * that nothing brings back (`focusCancel`), it opens on Cancel instead, and the
 * main button drops its Enter badge: Enter then presses Cancel, and doing the
 * thing is a gesture of its own. The primitive underneath is an
 * alert dialog: the focus stays inside, and goes back to where it was.
 *
 * Asking twice does nothing. The button turns into a spinner while `onConfirm`
 * runs, and a key held down or pressed again is ignored — by the keys
 * (`enterConfirms`) and by a flag, since two events can land before React has
 * painted the first. `onConfirm` may return `false` to keep the window open,
 * when what it asked for was refused.
 */

/** A key cap, small enough to sit in a button. Hidden on a touch screen. */
export function Kbd({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <kbd
      aria-hidden
      className={cn(
        "pointer-fine:inline-flex pointer-events-none ml-0.5 hidden items-center rounded border border-current/25 bg-current/10 px-1 font-mono text-[0.65rem] leading-4 font-normal opacity-70",
        className
      )}
    >
      {children}
    </kbd>
  )
}

export function ConfirmDialog({
  title,
  description,
  confirm,
  onConfirm,
  cancel,
  destructive,
  focusCancel,
  disabled,
  multiline,
  children,
  trigger,
  open,
  onOpenChange,
  contentProps,
}: {
  title: React.ReactNode
  description?: React.ReactNode
  /** The main button's words — the thing that will be done. */
  confirm: React.ReactNode
  onConfirm: () => void | boolean | Promise<void | boolean>
  /** The way out, when "Cancel" is not what it is. */
  cancel?: React.ReactNode
  destructive?: boolean
  /** The focus opens on Cancel: what the main button does loses work for good. */
  focusCancel?: boolean
  /** The main button cannot be pressed yet. */
  disabled?: boolean
  /** The window holds a field of several lines: Enter stays a new line there, ⌘/Ctrl+Enter confirms. */
  multiline?: boolean
  /** What else the window says, between the description and the buttons. */
  children?: React.ReactNode
  /** The button that opens it, when it draws one. Without it, `open` does. */
  trigger?: React.ReactNode
  open?: boolean
  onOpenChange?: (open: boolean) => void
  contentProps?: React.ComponentProps<typeof AlertDialogContent>
}) {
  const t = useT()
  const [inner, setInner] = React.useState(false)
  const [pending, setPending] = React.useState(false)
  const running = React.useRef(false)
  const main = React.useRef<HTMLButtonElement>(null)
  const back = React.useRef<HTMLButtonElement>(null)
  const content = React.useRef<HTMLDivElement>(null)
  const shown = open ?? inner
  const mac = typeof navigator !== "undefined" && isMac(navigator.platform || navigator.userAgent)

  const change = (next: boolean) => {
    if (running.current) return
    setInner(next)
    onOpenChange?.(next)
  }

  const run = async () => {
    if (running.current || disabled) return
    running.current = true
    setPending(true)
    let keep = false
    try {
      keep = (await onConfirm()) === false
    } finally {
      running.current = false
      setPending(false)
    }
    if (!keep) {
      setInner(false)
      onOpenChange?.(false)
    }
  }

  return (
    <AlertDialog open={shown} onOpenChange={change}>
      {trigger ? <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger> : null}
      <AlertDialogContent
        {...contentProps}
        ref={content}
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          if (focusCancel && back.current) {
            back.current.focus()
            return
          }
          const field = content.current?.querySelector<HTMLElement>("input:not([type=checkbox]), textarea")
          ;(main.current && !main.current.disabled ? main.current : (field ?? main.current))?.focus()
        }}
        onKeyDown={(event) => {
          contentProps?.onKeyDown?.(event)
          // A checkbox swallows Enter (preventDefault) without using it.
          if (event.defaultPrevented && (event.target as HTMLElement).getAttribute("role") !== "checkbox") return
          if (event.key === "Enter" && event.repeat) {
            event.preventDefault()
            return
          }
          if (!enterConfirms(event.nativeEvent, event.target as HTMLElement)) return
          event.preventDefault()
          void run()
        }}
      >
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {description ? <AlertDialogDescription>{description}</AlertDialogDescription> : null}
        </AlertDialogHeader>
        {children}
        <AlertDialogFooter>
          <AlertDialogCancel ref={back} disabled={pending}>
            {cancel ?? t("Cancel")}
            <Kbd>{t("Esc")}</Kbd>
          </AlertDialogCancel>
          <Button
            ref={main}
            type="button"
            variant={destructive ? "destructive" : "default"}
            disabled={disabled || pending}
            aria-busy={pending || undefined}
            aria-keyshortcuts={focusCancel ? undefined : multiline ? (mac ? "Meta+Enter" : "Control+Enter") : "Enter"}
            onClick={() => void run()}
          >
            {pending ? <Loader2Icon className="animate-spin" /> : null}
            {confirm}
            {focusCancel ? null : <Kbd>{multiline ? enterLabel(true, mac) : `↵ ${t("Enter")}`}</Kbd>}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
