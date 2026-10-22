/* What the Decide tab and a blocked ticket's discussion decide, without a DOM to decide it in.
 *
 * The server says what a card offers (`decisions.py`): a key, the column it
 * moves the ticket to, and what it needs before it can be done. What a button
 * is called, whether a click is enough or opens a field first, and whether
 * what was typed is enough to send — that is here, plain data in and out, so
 * that `node --test` holds it to what it says. Imports nothing, like
 * `composer.ts`.
 *
 * The sentences are English, and are the keys `t()` translates: see `french.ts`.
 */

/** The shape of one offer, as much of it as this file reads. */
export interface Offer {
  key: string
  column: string
  needs: "" | "text" | "note" | "model" | "titles"
  text: string
  number: number
}

/** What each kind of stop is called, in front of why — see `question.CATEGORIES`. */
export const CATEGORIES: Record<string, string> = {
  question: "A decision to make",
  access: "Missing access",
  manual: "Something to do by hand",
  credits: "Out of credit",
  ci: "Failing checks",
  conflict: "Conflict",
  split: "Too big for one ticket",
  other: "Stuck",
}

/** The button for each offer. An option is called by its own words instead. */
export const LABELS: Record<string, string> = {
  yes: "Yes, go ahead",
  close: "Yes, close it",
  answer: "Answer the question",
  "done-retry": "It's done, run it again",
  retry: "Run it again",
  model: "Run it again on another model",
  instruct: "Run it again with an instruction",
  split: "Split into sub-tickets",
  abandon: "Abandon — move to done",
  "abandon-cancelled": "Abandon — move to cancelled",
  other: "Other: write an instruction",
  validate: "Validate",
  rework: "Send back with an instruction",
  "fix-ci": "Fix the CI",
  "add-tests": "Add the missing tests",
  screenshots: "Take the screenshots",
  rebase: "Rebase onto the base branch",
  caveat: "Send back on this point",
  reject: "Reject",
}

/** What the field under an offer is asking for, when it opens one. */
export const PROMPTS: Record<Offer["needs"], string> = {
  "": "",
  text: "The instruction the next session reads",
  note: "A note, if you want one",
  model: "The model it runs on next",
  titles: "One sub-ticket a line",
}

/** What the field under an offer says while it is empty: an answer is an answer, not an instruction. */
export const promptOf = (offer: Offer): string =>
  offer.key === "answer" ? "Your answer" : offer.needs === "model" ? PROMPTS.note : PROMPTS[offer.needs]

/** The category's name, for one the server sent — or "Stuck" for one it did not know. */
export const categoryOf = (key: string | undefined): string =>
  CATEGORIES[key ?? ""] ?? CATEGORIES.other

/** The button an offer is drawn as: the option's words, or its key's sentence — giving up says where it files the ticket. */
export const labelOf = (offer: Offer): string =>
  offer.key === "option"
    ? offer.text
    : offer.key === "abandon" && offer.column === "cancelled"
      ? LABELS["abandon-cancelled"]
      : (LABELS[offer.key] ?? offer.key)

/** Whether a click does it at once, rather than opening a field to fill first. */
export const immediate = (offer: Offer): boolean => offer.needs === ""

/** What the field opens with: the instruction ready to edit, the sub-tickets proposed. */
export const prefilled = (offer: Offer): string =>
  offer.needs === "text" || offer.needs === "titles" ? offer.text : ""

/** The sub-tickets a field names: one a line, blank lines dropped. */
export const titlesIn = (text: string): string[] =>
  text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)

/** Whether what was typed is enough to do it. */
export function sendable(offer: Offer, text: string, model = ""): boolean {
  if (offer.needs === "text") return text.trim() !== ""
  if (offer.needs === "model") return model.trim() !== ""
  if (offer.needs === "titles") return titlesIn(text).length > 0
  return true
}

/** Whether an offer files the ticket away: drawn quieter, in the colour of a way out. */
export const away = (offer: Offer): boolean => offer.key === "abandon" || offer.key === "reject"

/* How a button looks: an outline, each of them, until it is the one chosen.
 * The first used to be drawn full, the way forward standing out — and read as
 * already chosen. Full is what a click did, and a way out is full in its red. */
export function tone(offer: Offer, chosen: boolean): "default" | "destructive" | "outline" {
  return !chosen ? "outline" : away(offer) ? "destructive" : "default"
}

/* The order the buttons are drawn in: the server's, the ways out last, apart —
 * a click on Abandon or Reject is one too many, in the middle of the others.
 * Each is numbered in that order, its key the same: see `keyOf`. */
export const arranged = <T extends Offer>(offers: T[]): { forward: T[]; out: T[] } => ({
  forward: offers.filter((offer) => !away(offer)),
  out: offers.filter(away),
})

/** The key that picks the button drawn at this place, from 1: none past 9. */
export const keyOf = (place: number): string => (place >= 1 && place <= 9 ? String(place) : "")

/* Where the CI of a pull request's repository is read: its Actions page, from
 * the pull request's own address. */
export function actionsOf(pullRequest: string): string {
  const repository = pullRequest.match(/^(https:\/\/github\.com\/[^/]+\/[^/]+)\/pull\//)
  return repository ? `${repository[1]}/actions` : ""
}

/** What a card's call to action says, in the column it is in. */
export const actionOf = (column: string): string | null =>
  column === "blocked" ? "Unblock" : column === "review" ? "Decide" : null

/* The call to action opens a tab of the ticket's window, and of its page,
 * named in the address like the others: a blocked ticket's discussion, where
 * its question is answered — there is no tab of its own for unblocking any
 * more, and `&tab=unblock`, from a link written before, reads as the
 * discussion — or the Decide tab of one in review. */
export type DecisionTab = "discussion" | "decide"

/** The tab a ticket waiting on you opens on, in the column it is in — none on any other. */
export const decisionTabOf = (column: string): DecisionTab | null =>
  column === "blocked" ? "discussion" : column === "review" ? "decide" : null

/* -- a blocked ticket's discussion ------------------------------------------ */

/* The question a run stopped on is answered where it was asked: in the
 * discussion, by a sentence typed under it or by one of the quick replies drawn
 * under its bubble — each a click that answers and runs the ticket again, the
 * way the same words typed would. A yes-no question is a yes and a no; a choice,
 * one reply per option, in its own words; one that proposes to close the ticket,
 * "yes, close it" in place of the yes, which files it as done; and always
 * running it again as it is. */

/** One quick reply: the offer it sends, and the words it sends with it — or the plain move back to Ready. */
export interface Reply<T extends Offer> {
  label: string
  offer?: T
  /** The answer it gives, before translation: the "No" of a yes-no question. */
  text?: string
}

/** The quick replies under a blocked ticket's question, in the order they are drawn. */
export function repliesOf<T extends Offer>(column: string, offers: T[]): Reply<T>[] {
  if (column !== "blocked") return []
  const find = (key: string) => offers.find((offer) => offer.key === key)
  const replies: Reply<T>[] = []
  const yes = find("yes")
  const close = find("close")
  const answer = find("answer")
  if (close) replies.push({ label: LABELS.close, offer: close })
  else if (yes) replies.push({ label: "Yes", offer: yes })
  if (yes && answer) replies.push({ label: "No", offer: answer, text: "No" })
  for (const option of offers.filter((offer) => offer.key === "option"))
    replies.push({ label: option.text, offer: option })
  replies.push({ label: "Run it again as it is", offer: find("retry") })
  return replies
}

/** The offer a sentence typed under a blocked ticket's question sends: its answer, or an instruction. */
export const typedOf = <T extends Offer>(offers: T[]): T | null =>
  offers.find((offer) => offer.key === "answer") ?? offers.find((offer) => offer.key === "other") ?? null

/* What a run says on a ticket that is not a report of what it did: the model
 * it chose, the class it gave, the queue it went back to, a pause. A line in
 * passing, drawn small and grey across the discussion rather than as a bubble
 * of Ponos's — the marks are `voice.MARKS`. */
const QUIET = ["🧠", "🏷️", "↩️", "⏸️"]

/** The most lines a line in passing may take: a longer one is a report, which is read, not glanced at. */
const PASSING = 2

/** Whether a message is one of the run's lines in passing, rather than something it says to you. */
export const quiet = (role: string, text: string): boolean =>
  role === "runner" &&
  QUIET.some((mark) => text.trimStart().startsWith(mark)) &&
  text.split("\n").filter((line) => line.trim()).length <= PASSING

/** What a session could not check, as a report opens each such line (`voice.py`, « caveat »). */
const CAVEAT = /^(À vérifier|To check)\s*:/

/** A long report as markdown: each point to check is an item of a list, rather than a line run into the next. */
export const listed = (text: string): string =>
  text
    .split("\n")
    .map((line) => (CAVEAT.test(line.trim()) ? `- ${line.trim()}` : line))
    .join("\n")

/** How many times Ponos has spoken to you in a discussion: its lines in passing do not count. */
export const answersIn = (messages: { role: string; text: string }[]): number =>
  messages.filter((message) => message.role === "runner" && !quiet(message.role, message.text)).length

/** Where the last question a run stopped on is, in a discussion — -1 when there is none. */
export const askedAt = (messages: { role: string; text: string }[]): number =>
  messages.findLastIndex((message) => message.role === "runner" && message.text.trimStart().startsWith("🙋"))

/** The words a pull request's checks are summed up in. */
export const CHECKS: Record<string, string> = {
  passed: "Checks pass",
  failed: "Checks fail",
  pending: "Checks running",
  none: "No checks",
  unknown: "Checks unknown",
}

/** What a run says it did, as the lines it is made of: one per line, or per semicolon, without their bullets. */
export const itemsOf = (text?: string): string[] =>
  (text ?? "")
    .split(/\n|;\s/)
    .map((line) => line.replace(/^\s*(?:[-*•]\s+)?/, "").trim())
    .filter(Boolean)
