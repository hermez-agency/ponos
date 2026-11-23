/*
 * The logo — Ponos's head, and nothing else.
 *
 * There used to be three symbols: a perforated ticket, a white tile with the
 * robot's screen in an orange frame, and the robot. The tile did not look like
 * the mascot and did not hold at 16 pixels. The logo is now the robot's head
 * alone, without body or frame, on a transparent ground: the same orange on a
 * light page and a dark one, so there is one version and no theme. It is what
 * a tab, an installed app, a home screen, a dock, a notification and the
 * Dokploy template show, all written from here by `node scripts/mascot.mjs`.
 *
 * At 24 pixels and under (a tab's favicon) ears, the flame's heart and the
 * mouth are a smudge: the head is drawn simpler, larger and with bigger eyes
 * in the same 120 × 120 box — the robot's own SMALL rule, `ponos-robot.js`.
 * `small: 'auto'` holds both drawings and lets a media query pick, so an <img>
 * of `logo.svg` is right at any size; `true` and `false` pin one.
 */

/* Below this width, in CSS pixels, the simple head is drawn. */
export const SMALL = 24;

export const HEAD = `<rect x="3" y="60" width="9" height="24" rx="4.5" fill="#BF4A02"/>
<rect x="108" y="60" width="9" height="24" rx="4.5" fill="#BF4A02"/>
<path d="M60 4C70 14 72 22 68.5 28C66.5 31.5 53.5 31.5 51.5 28C48 22 50 14 60 4Z" fill="#E8611A"/>
<path d="M60 14C64 18 65 21.5 63.2 24.2C62 26 58 26 56.8 24.2C55 21.5 56 18 60 14Z" fill="#FFE1CC"/>
<rect x="8" y="30" width="104" height="84" rx="32" fill="#E8611A"/>
<rect x="19" y="41" width="82" height="56" rx="20" fill="#1c1917"/>
<ellipse cx="46" cy="66" rx="7.5" ry="9" fill="#FFE1CC"/>
<ellipse cx="74" cy="66" rx="7.5" ry="9" fill="#FFE1CC"/>
<path d="M53 82Q60 87 67 82" fill="none" stroke="#FFE1CC" stroke-width="3.5" stroke-linecap="round"/>`;

export const SMALL_HEAD = `<path d="M60 3C70 13 72 21 68.5 27C66.5 30.5 53.5 30.5 51.5 27C48 21 50 13 60 3Z" fill="#E8611A"/>
<rect x="6" y="30" width="108" height="86" rx="32" fill="#E8611A"/>
<rect x="18" y="42" width="84" height="60" rx="20" fill="#1c1917"/>
<circle cx="44" cy="72" r="11" fill="#FFE1CC"/>
<circle cx="76" cy="72" r="11" fill="#FFE1CC"/>`;

/** The logo as an SVG file, on its 120 × 120 grid, on a transparent ground. */
export function logo({ small = 'auto', title = 'Ponos' } = {}) {
  const head = small === 'auto'
    ? `<style>.small { display: none; } @media (max-width: ${SMALL}px) { .small { display: inline; } .head { display: none; } }</style>
<g class="head">
${HEAD}
</g>
<g class="small">
${SMALL_HEAD}
</g>`
    : (small ? SMALL_HEAD : HEAD);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" role="img">
<title>${title}</title>
${head}
</svg>
`;
}
