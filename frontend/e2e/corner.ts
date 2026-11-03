import type { Page } from "@playwright/test"

/** What a tap meant for a clickable thing would land on something else for,
 * in the corner where the discussion's bubble stood over the bottom bar: the
 * page scrolled a half screen at a time, and `elementFromPoint` asked at the
 * middle of the part of each thing that is in the corner. */
export async function underTheCorner(page: Page): Promise<string[]> {
  return page.evaluate(async () => {
    const nav = document.querySelector<HTMLElement>('[data-slot="admin-mobile-nav"]')!
    const covered = new Set<string>()
    const settled = () => new Promise((resolve) => setTimeout(resolve, 50))
    for (let y = 0; ; y += window.innerHeight / 2) {
      window.scrollTo(0, y)
      await settled()
      // Measured at every step: the bar grows once its badge and its words are in.
      // A whole pixel clear of its edge: `elementFromPoint` answers in whole
      // pixels, and asked at 758.4 over a bar that starts at 759 it names the
      // bar — a card scrolling under it, caught there by the order of the runs.
      const bottom = Math.floor(nav.getBoundingClientRect().top) - 1
      const corner = { left: window.innerWidth - 96, right: window.innerWidth, top: bottom - 96, bottom }
      for (const element of Array.from(document.querySelectorAll<HTMLElement>("a, button, input, textarea, select, [role=tab]"))) {
        if (nav.contains(element) || !element.checkVisibility()) continue
        const box = element.getBoundingClientRect()
        const left = Math.max(box.left, corner.left)
        const right = Math.min(box.right, corner.right)
        const top = Math.max(box.top, corner.top)
        const end = Math.min(box.bottom, corner.bottom)
        // A pixel at least: a title whose last fraction of a pixel touches the bar is beside it.
        if (right - left < 1 || end - top < 1) continue
        const hit = document.elementFromPoint((left + right) / 2, (top + end) / 2)
        if (hit && (element.contains(hit) || hit.contains(element))) continue
        const name = (node: Element) =>
          node.getAttribute("aria-label") || node.getAttribute("data-slot") || node.textContent?.trim().slice(0, 40) || node.tagName
        covered.add(`${name(element)} under ${hit ? name(hit) : "nothing"}`)
      }
      if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 1) break
    }
    return Array.from(covered)
  })
}
