import { currentLanguage, t } from "@/lib/i18n"

/* A schedule's rule said in a sentence, kept apart from the form that first
 * said it: the list says it too, in the one column that replaced three. A
 * cadence, an hour and a day read in three cells contradicted each other — an
 * hourly schedule "at 00:00", with an empty day — where the sentence says only
 * what the runner reads of them.
 *
 * In the first load, unlike the form (`recurrence-dialog`): the list is what
 * the page opens on.
 */

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
// "09:00", "9h30", "9" — the shapes the runner reads (`schedules._CLOCK`).
const CLOCK = /^(\d{1,2})\s*(?:[:hH]\s*(\d{1,2})?)?$/

/** A day as the board writes it, found again from what a row says: "Mon", "monday". */
export const weekdayOf = (day: string) => {
  const text = day.trim().toLowerCase()
  return text ? WEEKDAYS.findIndex((name) => name.toLowerCase().startsWith(text)) : -1
}

/** The hour a row says, in the one shape a time field shows; empty is midnight, as for the runner. */
export function clockOf(at: string): string {
  const match = CLOCK.exec(at.trim() || "0")
  if (!match) return ""
  const hour = Number(match[1])
  const minute = Number(match[2] ?? 0)
  if (hour > 23 || minute > 59) return ""
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`
}

export const locale = () => (currentLanguage() === "fr" ? "fr-FR" : "en-GB")

/* A Monday, at noon in UTC: where the names of the days are read from. */
export const dayName = (index: number, width: "long" | "narrow") =>
  new Intl.DateTimeFormat(locale(), { weekday: width, timeZone: "UTC" }).format(
    Date.UTC(2024, 0, 1 + index, 12)
  )

/** The rule in the console's language — "Every Monday at 09:00" — or empty for a cadence the runner does not know. */
export function ruleOf({ cadence, at, day }: { cadence: string; at: string; day: string }): string {
  const time = clockOf(at)
  if (cadence === "Hourly") return t("Every hour at :{{minute}}", { minute: time.slice(3) || "00" })
  if (cadence === "Daily") return t("Every day at {{time}}", { time })
  if (cadence === "Weekly") {
    const index = weekdayOf(day)
    return index < 0
      ? t("Every week at {{time}}", { time })
      : t("Every {{day}} at {{time}}", { day: dayName(index, "long"), time })
  }
  if (cadence === "Monthly") return t("On day {{day}} of every month at {{time}}", { day: day.trim() || "1", time })
  return ""
}
