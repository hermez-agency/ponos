import * as React from "react"
import { enGB, fr } from "date-fns/locale"
import { configurePorts as configureForms, setFormConfig } from "react-data-form"
import { setTranslation, translate } from "react-mini-i18n"
import { configurePorts as configureViews } from "react-resource-view"

import { count, setNumberLocale } from "./numbers"

/* Which language the console speaks.
 *
 * The console is written in English and the sentence in the source *is* the
 * key — which is what react-mini-i18n is for: a key nobody translated is
 * rendered as it stands, so English needs no dictionary of its own beyond the
 * handful of words the packages under the console say differently. French is
 * the other dictionary, and it lives in `french.ts` — fetched only by a page
 * that reads French: it is a third of what the first load would otherwise
 * download, for a reader who never sees a word of it.
 *
 * Nobody is asked which one they read. The configuration may already say —
 * `runner.app_language`, or the reports' language when that is empty — and the
 * server writes it on `<html data-language>` before the page is drawn. Where
 * it says nothing the browser does — `Accept-Language` is the setting somebody
 * actually made — and where that says nothing useful the time zone answers for
 * it: a machine set to Europe/Paris is a machine whose owner reads French,
 * whatever the browser was installed in. The choice is then one line in
 * `localStorage`, like the theme, and the select in the header is how you take
 * it back — a pick made there outranks the file, since it was made later and
 * by the person reading.
 *
 * What is *not* translated here is everything that comes from somewhere else:
 * a ticket's title is Notion's, a column's name is the board's, the output of
 * a command is the CLI's. The console says its own words in your language and
 * repeats everybody else's in theirs.
 */

export type Language = "en" | "fr"

/** The two, with the flag the select shows. */
export const LANGUAGES: { code: Language; flag: string; name: string }[] = [
  { code: "en", flag: "🇬🇧", name: "English" },
  { code: "fr", flag: "🇫🇷", name: "Français" },
]

const KEY = "ponos-language"

/* The words the packages say, in the console's own. A board with nothing on it
 * is not "No data yet", and the action called `read` is `Open`. */
const ENGLISH: Record<string, string> = {
  "No data yet": "Nothing on the board.",
  "Nothing here": "nothing",
  Saved: "Moved",
  create: "New ticket",
  read: "Open",
  update: "Edit",
  delete: "Remove",
  "Une erreur est survenue": "Something went wrong",
  Continuer: "Continue",
  Fermer: "Close",
  // The calendar the schedules are laid out in says three of its own words in
  // French, and the button that walks forward through them a fourth.
  Jour: "Day",
  Semaine: "Week",
  Mois: "Month",
  Suivant: "Next",
  // A checkbox drawn outside a form — the calendar's preview of a schedule —
  // prints the value as it holds it, and `true` is not a word anybody reads.
  true: "yes",
  false: "no",
}

const DICTIONARIES: Partial<Record<Language, Record<string, string>>> = {
  en: ENGLISH,
}

/** The words of a language, fetched the first time it is asked for. */
async function dictionary(code: Language): Promise<Record<string, string>> {
  if (code === "fr") DICTIONARIES.fr ??= (await import("./french")).FRENCH
  return DICTIONARIES[code] ?? ENGLISH
}

/* Where French is the language of the work, whatever the browser was installed
 * in. A hint rather than a census: a zone that is not here only means the
 * browser's own languages have the last word. */
const FRENCH_ZONES = new Set([
  "Europe/Paris",
  "Europe/Brussels",
  "Europe/Luxembourg",
  "Europe/Monaco",
  "America/Montreal",
  "Africa/Algiers",
  "Africa/Tunis",
  "Africa/Casablanca",
  "Africa/Dakar",
  "Africa/Abidjan",
  "Indian/Reunion",
  "Pacific/Noumea",
])

const known = (code: string): code is Language =>
  LANGUAGES.some((language) => language.code === code)

/** What this browser reads, as best as it can be told without asking. */
export function detect(): Language {
  const said = navigator.languages?.length ? navigator.languages : [navigator.language]
  for (const tag of said) {
    const code = String(tag ?? "")
      .slice(0, 2)
      .toLowerCase()
    if (known(code)) return code
  }
  try {
    if (FRENCH_ZONES.has(Intl.DateTimeFormat().resolvedOptions().timeZone)) return "fr"
  } catch {
    // A browser without `Intl` reads the console in English, like every other
    // one that said nothing.
  }
  return "en"
}

/** What the configuration opens the console in, if it says anything. */
function configured(): Language | null {
  const said = document.documentElement.dataset.language ?? ""
  return known(said) ? said : null
}

function remembered(): Language {
  try {
    const kept = localStorage.getItem(KEY)
    if (kept && known(kept)) return kept
  } catch {
    // Storage switched off: the browser is asked again on every load, which is
    // the same answer it gave the first time.
  }
  return configured() ?? detect()
}

let language: Language = remembered()
const listeners = new Set<() => void>()

function apply(next: Language, words: Record<string, string>) {
  setTranslation(words)
  document.documentElement.lang = next
  /* A date is not a sentence, so no dictionary can hold it: the month over the
   * schedules' calendar and the moment in a cell are formatted by the packages
   * themselves, and both ask for the locale rather than guessing. Told here, so
   * the language the console was set to is the language its dates are in —
   * `Accept-Language` is often not the one, on a machine bought abroad.
   *
   * British English rather than American: this console says 14/09 everywhere
   * else, and a date that changed shape between two panes would be a date
   * nobody could read twice. */
  configureViews({ dateLocale: next === "fr" ? fr : enGB })
  // And a number is not one either: « 2 734,75 $ » is `Intl`'s, not French's.
  setNumberLocale(next === "fr" ? "fr-FR" : "en-GB")
  configureForms({
    dateLocale: next === "fr" ? fr : enGB,
    intlLocale: next === "fr" ? "fr-FR" : "en-GB",
  })
  // These two are handed to a toast as they stand rather than translated on
  // the way, so they are written again whenever the dictionary changes.
  //
  // The confirmation does not say where it landed: the same toast answers a
  // project written to Notion, a project written to a Markdown file, and a
  // setting written to `config.toml` — and it used to claim Notion for all
  // three.
  setFormConfig({
    defaultForm: {
      label: {
        success: translate("Written"),
        error: translate("Some fields need another look"),
      },
    },
  })
}

// On import, before a resource is declared: `createViewResource` reads the
// dictionary as it builds. Awaited at the top of the module, so nothing that
// imports this one runs until the French has arrived, when it is French.
apply(language, await dictionary(language))

/** The language the console is in. */
export const currentLanguage = () => language

// The last one picked: a pick made while French is on its way outranks it.
let wanted: Language = language

/** Change it, and redraw everything that says anything. */
export async function setLanguage(next: Language) {
  wanted = next
  if (next === language) return
  const words = await dictionary(next)
  if (wanted !== next) return
  language = next
  apply(next, words)
  try {
    localStorage.setItem(KEY, next)
  } catch {
    // Kept for as long as the tab is open, then. That is the whole cost.
  }
  for (const listener of listeners) listener()
}

/** Told when the language changes, before anything is drawn again in it. */
export function onLanguageChange(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

const subscribe = onLanguageChange

/** The language, read reactively: a component that asks is redrawn when it changes. */
export function useLanguage(): Language {
  return React.useSyncExternalStore(subscribe, currentLanguage)
}

/** Outside a render — a toast, an event handler, a string built on the way to one. */
export const t = translate

/** A sentence about `value` things, in the form the language gives that many:
 *  `counted(6, "{{count}} ticket", "{{count}} tickets")` is « 6 tickets ». */
export function counted(value: number, one: string, other: string): string {
  const said = count(value, one, other)
  return translate(said.key, said.params)
}

/* Inside one. The function is the same; what the hook adds is the redraw, so a
 * pane that says anything at all asks for it here rather than importing `t`. */
export function useT(): typeof translate {
  useLanguage()
  return translate
}
