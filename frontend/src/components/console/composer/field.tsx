import * as React from "react"
import { TerminalIcon } from "lucide-react"

import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

/** The words of the bar — set in amber and monospace once they are a `>` command. */
export function Field({
  command,
  className,
  ...props
}: React.ComponentProps<"textarea"> & { command: boolean }) {
  const t = useT()
  return (
    <div className="flex items-start gap-2 px-4 pt-3">
      {command ? (
        <span className="bg-tr-amber/10 text-tr-amber mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[0.65rem] font-semibold">
          <TerminalIcon className="size-3" />
          {t("command")}
        </span>
      ) : null}
      <textarea
        rows={1}
        spellCheck={!command}
        autoComplete="off"
        {...props}
        className={cn(
          "placeholder:text-muted-foreground max-h-[200px] min-h-6 w-full flex-1 resize-none bg-transparent text-[0.9375rem] leading-6 outline-none disabled:opacity-60",
          "scroll-thin",
          command && "text-tr-amber font-mono text-sm",
          className
        )}
      />
    </div>
  )
}
