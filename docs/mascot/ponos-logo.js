/*
 * The logo — Ponos's icon, not his portrait.
 *
 * The robot (`ponos-robot.js`) is a character: it moves, it has seven moods,
 * and it needs some room to be read. An icon is drawn at 16 pixels in a tab
 * and cropped by a phone's mask, so it is a mark of its own — the robot's
 * screen and flame, nothing else, in the same frame as the Hermez symbol: a
 * rounded square with an orange border. It is what a tab, an installed app, a
 * home screen, a dock, a notification and the Dokploy template show, all
 * written from here by `node scripts/mascot.mjs`.
 *
 * Two versions, and no animation: light, and dark, where the frame takes the
 * ground of a dark page and the screen, darker still, is set apart from it by
 * a thin outline. `theme: 'auto'` holds both and follows prefers-color-scheme —
 * the favicon.
 */

export const LOGOS = {
  light: { ground: 'fill: #FFFFFF;', screen: 'fill: #1c1917;' },
  dark: { ground: 'fill: #1c1917;', screen: 'fill: #0c0a09; stroke: #44403c; stroke-width: 2;' },
};

const rules = (theme) => Object.entries(LOGOS[theme]).map(([part, css]) => `.${part} { ${css} }`).join(' ');

/** The logo as an SVG file, on its 120 × 120 grid. */
export function logo({ theme = 'light', title = 'Ponos' } = {}) {
  const style = theme === 'auto'
    ? `${rules('light')} @media (prefers-color-scheme: dark) { ${rules('dark')} }`
    : rules(theme);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" role="img">
<title>${title}</title>
<style>${style}</style>
<rect x="4" y="4" width="112" height="112" rx="26" class="ground" stroke="#E8611A" stroke-width="8"/>
<path d="M60 20C67 27 69 32 66 36C64 39 56 39 54 36C51 32 53 27 60 20Z" fill="#E8611A"/>
<rect x="28" y="44" width="64" height="50" rx="16" class="screen"/>
<circle cx="48" cy="69" r="7" fill="#FFE1CC"/>
<circle cx="72" cy="69" r="7" fill="#FFE1CC"/>
</svg>
`;
}
