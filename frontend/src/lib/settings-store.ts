import * as React from "react"

import type { SettingGroup, SettingSection, Settings, SettingValue } from "./types"

/* The configuration, as the server last described it.
 *
 * The settings page is a resource with one sub-page per group, and a sub-page
 * is declared before anything has been fetched — `subViewResource` is read off
 * the view as the tabs are drawn. So the description has to be reachable from
 * outside React: `getItem` writes it here, the tab list reads it back, and the
 * page stays what it has always been — drawn from what the server says the
 * configuration holds, never from a list kept in the console.
 *
 * Four other things live here for the same reason.
 *
 * A *draft* is what you have typed on a page and not saved. Only one page is
 * mounted at a time — that is the whole point of tabs — so a form leaving the
 * screen would otherwise take your edits with it. It writes them here instead,
 * under its group, and reads them back on the way in.
 *
 * The *revision*, which is how a save reaches the pages it did not touch: every
 * form is keyed by it, so a fresh description redraws them all — previews,
 * defaults and what the file now states included.
 *
 * Whether the *keys* are shown: a choice of whoever reads the page, kept with
 * the browser like the theme, and read by every field at once.
 *
 * And what a search, or an old link to a section, *asked for*: the page it
 * leads to is mounted after the click, and unfolds and scrolls to it then.
 */

/* The French of every field, fetched by the pages that draw one, when they are
 * drawn in French: see `settings-french.ts`. One function for all of them, so
 * that the dictionary is fetched and merged once (`useFrench`). */
export const settingsFrench = () => import("./settings-french").then((module) => module.SETTINGS_FRENCH)

let drawn: Settings | null = null
let revision = 0

const listeners = new Set<() => void>()
const drafts = new Map<string, Record<string, SettingValue>>()

const tell = () => listeners.forEach((listener) => listener())

/** What the server just said the file holds. */
export function publishSettings(fresh: Settings) {
  drawn = fresh
  revision += 1
  tell()
}

export const currentSettings = (): Settings | null => drawn

/** One card of it, by the key the server names it with. */
export const sectionOf = (key: string): SettingSection | undefined =>
  drawn?.sections.find((section) => section.key === key)

/** One page of it. */
export const groupOf = (key: string): SettingGroup | undefined =>
  drawn?.groups.find((group) => group.key === key)

/** The cards of one page, in the order the server lists them. */
export const sectionsIn = (group: string): SettingSection[] =>
  drawn?.sections.filter((section) => section.group === group) ?? []

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** How many times the description has been redrawn. Read to be redrawn with it. */
export function useSettingsRevision(): number {
  return React.useSyncExternalStore(subscribe, () => revision)
}

/** What a page holds that the file does not — or nothing, once it is saved. */
export function rememberDraft(group: string, data: Record<string, SettingValue>, dirty: boolean) {
  if (dirty) drafts.set(group, data)
  else drafts.delete(group)
}

export const draftOf = (group: string): Record<string, SettingValue> | undefined => drafts.get(group)

export const forgetDraft = (group: string) => drafts.delete(group)

/** Whether anything typed is waiting to be saved — asked before a redraw takes it away. */
export const somethingIsEdited = (): boolean => drafts.size > 0

/* -- the keys, shown or not -------------------------------------------------- */

const KEYS = "ponos:settings-keys"

let keysShown = (() => {
  try {
    return window.localStorage.getItem(KEYS) === "shown"
  } catch {
    return false
  }
})()

/** Show `config.toml`'s keys under every field, or hide them again. */
export function showKeys(shown: boolean) {
  keysShown = shown
  try {
    window.localStorage.setItem(KEYS, shown ? "shown" : "hidden")
  } catch {
    // A browser that keeps nothing still shows them for as long as the page is open.
  }
  tell()
}

export function useKeysShown(): boolean {
  return React.useSyncExternalStore(subscribe, () => keysShown)
}

/* -- what was asked for -------------------------------------------------------- */

/** A field's name (`notion.token`) or a card's key (`notify`) the page should bring into view. */
let wanted = ""

export function ask(target: string) {
  wanted = target
  tell()
}

/** What was asked for, once: a page that has scrolled to it lets it go. */
export function takeAsked(): string {
  const target = wanted
  wanted = ""
  if (target) tell()
  return target
}

export const asked = (): string => wanted

/** The same, for a block to unfold when it holds what was asked for. */
export function useAsked(): string {
  return React.useSyncExternalStore(subscribe, () => wanted)
}

/* A setting is named by its path into the file — `notion.status.ready` — and
 * react-data-form reads a dot in an input's name as a step into a nested
 * object: it would file the input under `inputs.notion.status` and lose the
 * flat entry the form was built with. So the dots become dashes on the way in,
 * and the field's own name comes back from the description rather than from
 * the input. */
export const inputName = (name: string) => name.replaceAll(".", "-")

/** Where a card is, for a link or a search to scroll to. */
export const cardId = (key: string) => `settings-card-${key}`
