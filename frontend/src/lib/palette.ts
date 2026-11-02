/* The command palette, opened from anywhere on the page.
 *
 * An event, as for the drawer (`talk.ts`): the bar's button does not have to
 * import the palette to open it, which would put the palette — cmdk and every
 * entry — back in the first load that `App.tsx` keeps it out of. This module
 * imports nothing, for the same reason. */

export const OPENED = "ponos:palette"

/** Open the palette, from anywhere on the page — the button in the bar. */
export const openPalette = () => window.dispatchEvent(new Event(OPENED))
