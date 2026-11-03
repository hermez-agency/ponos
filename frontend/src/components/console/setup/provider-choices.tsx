import { CircleCheck } from "lucide-react"

import { Rich } from "@/components/console/text"
import { useT } from "@/lib/i18n"
import type { Provider } from "@/lib/types"
import { cn } from "@/lib/utils"

const CHOICES: { key: Provider; title: string; lines: string[] }[] = [
  {
    key: "cli",
    title: "Claude Code CLI",
    lines: [
      "Your Claude subscription, signed in with `claude auth login`.",
      "The only one that keeps Claude in Chrome and waits for credits when the window runs out.",
      "In a container, the command is typed once in its terminal.",
    ],
  },
  {
    key: "api_key",
    title: "Anthropic API key",
    lines: [
      "A key from console.anthropic.com, billed by the token.",
      "Nothing to sign in, nothing to wait for — and no Claude in Chrome.",
    ],
  },
  {
    key: "openrouter",
    title: "OpenRouter",
    lines: [
      "One key for every provider, billed by OpenRouter.",
      "Models are then named as OpenRouter slugs (`anthropic/claude-sonnet-4.5`, `openai/gpt-5`).",
      "No Claude in Chrome, nothing to wait for.",
    ],
  },
]

/** The three ways to answer the sessions, side by side, one of them chosen. */
export function ProviderChoices({ chosen, onChoose }: { chosen: Provider | null; onChoose: (key: Provider) => void }) {
  const t = useT()
  return (
    <div className="grid gap-3 sm:grid-cols-3" role="radiogroup" aria-label={t("Claude provider")}>
      {CHOICES.map((choice) => (
        <button
          key={choice.key}
          type="button"
          role="radio"
          aria-checked={chosen === choice.key}
          data-testid={`provider-${choice.key}`}
          onClick={() => onChoose(choice.key)}
          className={cn(
            "flex flex-col gap-2 rounded-xl border p-4 text-left transition-colors",
            chosen === choice.key
              ? "border-primary ring-primary/30 bg-primary/5 ring-2"
              : "hover:bg-muted/60"
          )}
        >
          <span className="flex items-center justify-between gap-2 font-semibold">
            {t(choice.title)}
            {chosen === choice.key ? <CircleCheck className="text-primary size-4" /> : null}
          </span>
          <ul className="text-muted-foreground flex flex-col gap-1 text-xs leading-relaxed">
            {choice.lines.map((line) => (
              <li key={line}>
                <Rich text={t(line)} />
              </li>
            ))}
          </ul>
        </button>
      ))}
    </div>
  )
}
