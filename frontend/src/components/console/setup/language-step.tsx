import * as React from "react"
import { ArrowRight, CircleCheck } from "lucide-react"

import { Said, StepCard } from "@/components/console/setup/bits"
import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { LANGUAGES, setLanguage, useLanguage, useT, type Language } from "@/lib/i18n"
import { cn } from "@/lib/utils"

/* -- 0. the language -------------------------------------------------------- */

/** The language, first: every step after it is read in it.
 *
 * Taken in this browser the moment it is clicked, like the picker of the
 * settings; and written to the file as the language of the reports and of the
 * console — at once when somebody is signed in, with the account otherwise. */
export function LanguageStep({ claimed, onNext }: { claimed: boolean; onNext: () => void }) {
  const t = useT()
  const language = useLanguage()
  const [problem, setProblem] = React.useState("")

  const choose = async (code: Language) => {
    setLanguage(code)
    setProblem("")
    if (!claimed) return
    try {
      await api.saveSettings({ settings: { "runner.language": code, "runner.app_language": code } })
    } catch (error) {
      setProblem(why(error))
    }
  }

  return (
    <StepCard
      title={t("Which language")}
      blurb={t(
        "The console's, and the one Ponos writes its reports in. Both can be changed later in the settings."
      )}
      footer={
        <Button type="button" onClick={onNext}>
          {t("Continue")}
          <ArrowRight />
        </Button>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label={t("Language")}>
        {LANGUAGES.map((item) => (
          <button
            key={item.code}
            type="button"
            role="radio"
            aria-checked={language === item.code}
            data-testid={`language-${item.code}`}
            onClick={() => void choose(item.code)}
            className={cn(
              "flex items-center gap-3 rounded-xl border p-4 text-left text-base font-semibold transition-colors",
              language === item.code
                ? "border-primary ring-primary/30 bg-primary/5 ring-2"
                : "hover:bg-muted/60"
            )}
          >
            <span aria-hidden className="text-2xl">
              {item.flag}
            </span>
            {item.name}
            {language === item.code ? <CircleCheck className="text-primary ml-auto size-4" /> : null}
          </button>
        ))}
      </div>
      <Said ok={false} text={problem} />
    </StepCard>
  )
}
