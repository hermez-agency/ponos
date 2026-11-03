import * as React from "react"
import { TerminalIcon } from "lucide-react"

import { completed, completions, cycled, isCommand } from "@/lib/composer"
import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

/* The `>` mode: the commands a half-typed verb is heading for, above the bar.
 *
 * The keys are the field's — the menu never takes the focus, so that typing
 * goes on while it is open — which is why the hook hands back `onKey` for the
 * field to ask first.
 */

export function useCommands(text: string, setText: (text: string) => void, commands?: string[]) {
  const [choice, setChoice] = React.useState(0)
  const [closed, setClosed] = React.useState(false)
  const command = commands !== undefined && isCommand(text)
  const offered = commands && !closed ? completions(text, commands) : []

  React.useEffect(() => setChoice(0), [text])

  /** Whether the key was the menu's, and is not to be read again. */
  const onKey = (event: React.KeyboardEvent): boolean => {
    if (!offered.length) return false
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault()
      const step = event.key === "ArrowDown" ? 1 : -1
      setChoice((current) => cycled(current, step, offered.length))
      return true
    }
    if (event.key === "Tab" || (event.key === "Enter" && !event.shiftKey)) {
      event.preventDefault()
      setText(completed(offered[choice] ?? offered[0]))
      return true
    }
    if (event.key === "Escape") {
      event.preventDefault()
      event.stopPropagation()
      setClosed(true)
      return true
    }
    return false
  }

  return { command, offered, choice, onKey, reopen: () => setClosed(false) }
}

export function CommandMenu({
  offered,
  choice,
  onPick,
}: {
  offered: string[]
  choice: number
  onPick: (verb: string) => void
}) {
  const t = useT()
  if (!offered.length) return null
  return (
    <div
      role="listbox"
      aria-label={t("Commands")}
      className="bg-popover text-popover-foreground absolute inset-x-0 bottom-full z-20 mb-2 max-h-64 overflow-auto rounded-xl border p-1 shadow-md"
    >
      {offered.map((verb, index) => (
        <button
          key={verb}
          type="button"
          role="option"
          aria-selected={index === choice}
          className={cn(
            "flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left font-mono text-sm",
            index === choice ? "bg-accent text-accent-foreground" : "hover:bg-muted"
          )}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => onPick(verb)}
        >
          <TerminalIcon className="text-muted-foreground size-3.5" />
          <span className="text-tr-amber">&gt;</span>
          {verb}
        </button>
      ))}
    </div>
  )
}
