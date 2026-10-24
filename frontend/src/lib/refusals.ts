/* What the server refuses with, recognised so that it can be said in French.
 *
 * A route that refuses answers `{"error": "<sentence>"}`, and the sentence is
 * the English one the Python raised — the server does not know which language
 * the page is drawn in, and the journal it also writes is read in English. So
 * the page translates on arrival, the way it does the settings' sentences: the
 * English is the key in `french.ts`. A sentence with a name or a number in it
 * is a template here, `{{name}}` where the value goes, recognised whole and
 * translated with its values put back.
 *
 * A test holds this list to the `raise`s of the chapters the console asks
 * (`tests/test_release.py`): a refusal reworded in Python and not here would
 * quietly go back to English. A sentence this list does not know is shown as
 * it came — better the server's English than nothing. Imports nothing, like
 * `composer.ts`, so that `node --test` reads it as it is.
 */

/** What a refusal says when the server said nothing — a proxy's page, a crash before the JSON. */
export const SILENT = "The server answered {{status}}"

export const REFUSALS: readonly string[] = [
  SILENT,
  // routes.py: around every route.
  "the board: {{error}}",
  "the body is not JSON",
  "invalid request",
  // goals.py
  "a goal needs a name",
  "this workspace has no goals database",
  "nothing to change",
  "this board has no “{{column}}” column to point a ticket at a goal",
  "no goal with id {{id}}",
  // schedules.py
  "this workspace has no schedules database",
  "a schedule needs a name",
  "no schedule with id {{id}}",
  "unknown type “{{kind}}”",
  "unknown sub-type “{{subtype}}”",
  "this schedule is already being launched",
  // projects.py: a project, its brief and its pictures.
  "no project with id {{id}}",
  "this workspace has no projects database",
  "this brief changed in the board since it was opened",
  "this brief holds what Markdown cannot keep; saving it would lose it",
  "a project has a cover and an icon, not a {{slot}}",
  // upkeep.py: the health band's fixes, and the tidy.
  "a fix is made only once it is confirmed",
  "a run is in progress — try again once it has finished",
  // settings.py: a value the file cannot take.
  "{{label}}: yes or no",
  "{{label}}: a number",
  "{{label}}: “{{offered}}” is not a number",
  "{{label}}: {{minimum}} at the least",
  "{{label}}: {{maximum}} at the most",
  "{{label}}: a list",
  "{{label}}: no such moment “{{moment}}”",
  "{{label}}: one of {{choices}}",
  "{{table}}: a list of {name, value}",
  "settings: a table of name → value",
  "a {{table}} row set to {{value}} has no name",
  "“{{name}}” maps to nothing — fill it in, or remove the row",
  "“{{name}}” is named twice",
  "no such setting: {{name}}",
]

const PLACE = /\{\{(\w+)\}\}/g

/* Each template as the expression that recognises it, whole: the values are
 * the shortest that still let the rest of the sentence match. */
const PATTERNS = REFUSALS.map((template) => {
  const names = [...template.matchAll(PLACE)].map((found) => found[1])
  const source = template
    .split(PLACE)
    .map((part, index) => (index % 2 ? "(.*?)" : part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
    .join("")
  return { template, names, pattern: new RegExp(`^${source}$`, "s") }
})

/** The template a refusal was said from, and the values it was said with — or nothing, for a sentence not on the list. */
export function refusalOf(message: string): { key: string; params: Record<string, string> } | undefined {
  for (const { template, names, pattern } of PATTERNS) {
    const found = pattern.exec(message)
    if (!found) continue
    return { key: template, params: Object.fromEntries(names.map((name, index) => [name, found[index + 1]])) }
  }
  return undefined
}
