/*
 * <ponos-robot> — Ponos, the robot and the product, as a Web Component.
 *
 * Ponos is the Greek god of toil: the robot is the one who does the tedious
 * part of a ticket in your place, and the product carries his name. What
 * machines address keeps the old one — the command, the package and this
 * element's tag are ponos, and the tag stays `ponos-robot` so
 * that no page embedding it breaks.
 *
 * The landing page is one static file with no build step, so the mascot is
 * vanilla JavaScript rather than React: it has to load the way the page does,
 * from a <script> tag. It is also the single source of the drawing — the
 * favicon, the standalone SVG, the Open Graph image and the sheet of states
 * are all written from this module by `node scripts/mascot.mjs`, never drawn
 * twice. Nothing here touches the DOM at import time, so Node can import it.
 *
 * Three tables make the robot, and extending it means adding a row to one of
 * them, never copying the drawing:
 *
 *   PALETTES     the colours, as CSS variables (--robot-body, --robot-eye…),
 *                for a light and a dark background;
 *   STATES       each reaction: which layer gets which style and which
 *                keyframes (declared in KEYFRAMES);
 *   ACCESSORIES  bits of SVG dropped into the `accessories` layer.
 *
 *   <script src="mascot/ponos-robot.js" type="module"></script>
 *   <ponos-robot state="thinking" theme="dark" size="96"></ponos-robot>
 *
 * Attributes: `state` (a key of STATES, idle by default), `theme` (light,
 * dark, or auto — the default, which follows prefers-color-scheme),
 * `size` (pixels; without it the robot takes the width of its container),
 * `accessories` (space-separated keys of ACCESSORIES), `still` (hold the pose,
 * never move nor blink — what a list of a hundred robots asks for, where only
 * the ones that are doing something should look like it).
 *
 * The web console bundles this very file rather than a copy of it: a hundred
 * robots on one board is a hundred shadow roots, so they share one stylesheet
 * and clone one parsed drawing instead of each parsing their own.
 *
 * Most of those robots are drawn at 18 to 32 pixels — a card, a toast, the
 * bar — where arms, legs and a chest are a smudge. Under SMALL pixels wide the
 * robot is only its face, drawn larger in the same box: the state still reads
 * from the eyes, the mouth and the flame. It is a CSS query, not an attribute,
 * so nobody has to remember to ask for it.
 *
 * The Greek touch — a flame on the head, a tunic, a sash and a brooch — is
 * kept as spare as the rest: flat colours, no folds, no fret. It stays a
 * robot first; the dress only says whose name he carries.
 */

export const PALETTES = {
  light: {
    '--robot-body': '#E8611A',
    '--robot-body-shade': '#BF4A02',
    '--robot-screen': '#18181B',
    '--robot-eye': '#FFE1CC',
    '--robot-accent': '#ffcf5c',
    '--robot-flame': '#FFA524',
    '--robot-flame-core': '#FFE08A',
    '--robot-gold': '#f2c65a',
    '--robot-gold-deep': '#b8861f',
    '--robot-tunic': '#f3ecdc',
    '--robot-sash': '#18181B',
    '--robot-pink': '#ff8fb0',
    '--robot-glint': '#ffffff',
    '--robot-alert': '#ff6b86',
    '--robot-ink': '#8A3206',
    '--robot-shadow': 'rgba(24, 24, 27, .16)',
  },
  dark: {
    '--robot-body': '#F2803F',
    '--robot-body-shade': '#E8611A',
    '--robot-screen': '#141414',
    '--robot-eye': '#FFE1CC',
    '--robot-accent': '#ffd36b',
    '--robot-flame': '#FFA524',
    '--robot-flame-core': '#FFE08A',
    '--robot-gold': '#f2c65a',
    '--robot-gold-deep': '#b8861f',
    '--robot-tunic': '#f3ecdc',
    '--robot-sash': '#141414',
    '--robot-pink': '#ff8fb0',
    '--robot-glint': '#ffffff',
    '--robot-alert': '#ff7d93',
    '--robot-ink': '#FFB38A',
    '--robot-shadow': 'rgba(242, 128, 63, .16)',
  },
};

/* Below this width, in CSS pixels, only the face is drawn. */
const SMALL = 40;

/*
 * The drawing, on a 128 × 128 grid. Every group carries a `data-layer`: the
 * main layers (base, body, head, eyes, eyelids, mouth, flame, arm-left,
 * arm-right, accessories, fx) and the parts a state may need to reach inside
 * them. `rig` is everything that moves with the robot — the shadow stays on
 * the floor when it jumps; `frame` holds it all, and is what the small face
 * zooms. The gradients only lighten or darken what is under them, so they
 * carry no colour of their own: the palette stays in the variables, and two
 * robots inline on one page may share an id without a thing changing. The
 * dress is cut by the torso's own outline, and lives in `body`: whatever the
 * torso does — a hop, a sigh, a jiggle — it does with it.
 */
const DRAWING = `
  <defs>
    <linearGradient id="trr-shade" x1="0" y1="0" x2="0" y2="1">
      <stop offset=".4" stop-color="#1c0a02" stop-opacity="0"/>
      <stop offset="1" stop-color="#1c0a02" stop-opacity=".2"/>
    </linearGradient>
    <radialGradient id="trr-sheen" cx=".32" cy=".18" r=".75">
      <stop offset="0" stop-color="#fff" stop-opacity=".38"/>
      <stop offset=".6" stop-color="#fff" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="trr-glow" cx=".5" cy=".35" r=".7">
      <stop offset="0" stop-color="#fff" stop-opacity=".1"/>
      <stop offset="1" stop-color="#fff" stop-opacity="0"/>
    </radialGradient>
    <clipPath id="trr-torso"><rect x="42" y="78" width="44" height="30" rx="15"/></clipPath>
  </defs>
  <g data-layer="frame">
  <g data-layer="base">
    <ellipse class="shadow" cx="64" cy="119" rx="27" ry="4.6"/>
    <ellipse class="shadow" cx="64" cy="119" rx="17" ry="3"/>
  </g>
  <g data-layer="rig">
    <g data-layer="body">
      <g data-layer="leg-left">
        <rect class="limb-fill" x="48" y="99" width="12" height="14" rx="6"/>
        <ellipse class="foot" cx="53" cy="114.5" rx="8" ry="4.5"/>
      </g>
      <g data-layer="leg-right">
        <rect class="limb-fill" x="68" y="99" width="12" height="14" rx="6"/>
        <ellipse class="foot" cx="75" cy="114.5" rx="8" ry="4.5"/>
      </g>
      <rect class="shell" x="42" y="78" width="44" height="30" rx="15"/>
      <g data-layer="dress" clip-path="url(#trr-torso)">
        <path class="tunic" d="M42 92 Q64 89 86 92 V108 H42 Z"/>
        <path class="sash" d="M42 86 L54 81.5 L86 100 L86 108 Z"/>
      </g>
      <rect x="42" y="78" width="44" height="30" rx="15" fill="url(#trr-shade)"/>
      <g data-layer="brooch">
        <circle class="brooch" cx="51" cy="89" r="3.4"/>
        <circle class="brooch-pin" cx="51" cy="89" r="1.5"/>
        <circle class="glint" cx="50" cy="88" r=".8"/>
      </g>
    </g>
    <g data-layer="head">
      <g data-layer="flame">
        <g data-layer="fire">
          <path class="fire" d="M64 4.6 C68.8 10.6 70.6 15.4 67.6 20.2 C66.4 22 61.6 22 60.4 20.2 C57.4 15.4 59.2 10.6 64 4.6 Z"/>
          <path class="fire-core" d="M64 10.6 C66.4 14.2 67 17.2 65.2 19.6 C64.6 20.2 63.4 20.2 62.8 19.6 C61 17.2 61.6 14.2 64 10.6 Z"/>
        </g>
        <rect class="socket" x="59.2" y="19.6" width="9.6" height="3.6" rx="1.2"/>
      </g>
      <circle class="ear" cx="19.5" cy="56" r="7.5"/>
      <circle class="ear" cx="108.5" cy="56" r="7.5"/>
      <rect class="shell" x="20" y="22" width="88" height="64" rx="30"/>
      <rect x="20" y="22" width="88" height="64" rx="30" fill="url(#trr-shade)"/>
      <rect x="20" y="22" width="88" height="64" rx="30" fill="url(#trr-sheen)"/>
      <path class="sheen" d="M33 38 Q38 29 50 26.5"/>
      <rect class="screen" x="30" y="33" width="68" height="44" rx="20"/>
      <g data-layer="eyes">
        <g data-layer="eye-left">
          <g data-layer="eye-open-left" class="eye-open">
            <rect class="eye" x="42.5" y="44" width="15" height="18" rx="7.5"/>
            <circle class="glint" cx="47" cy="49" r="3"/>
            <circle class="glint glint-small" cx="53" cy="57.5" r="1.4"/>
          </g>
          <path data-layer="eye-joy-left" class="eye-line eye-joy" d="M43.5 55 Q50 45.5 56.5 55"/>
          <path data-layer="eye-closed-left" class="eye-line eye-closed" d="M43.5 53 Q50 58.5 56.5 53"/>
        </g>
        <g data-layer="eye-right">
          <g data-layer="eye-open-right" class="eye-open">
            <rect class="eye" x="70.5" y="44" width="15" height="18" rx="7.5"/>
            <circle class="glint" cx="75" cy="49" r="3"/>
            <circle class="glint glint-small" cx="81" cy="57.5" r="1.4"/>
          </g>
          <path data-layer="eye-joy-right" class="eye-line eye-joy" d="M71.5 55 Q78 45.5 84.5 55"/>
          <path data-layer="eye-closed-right" class="eye-line eye-closed" d="M71.5 53 Q78 58.5 84.5 53"/>
        </g>
      </g>
      <g data-layer="eyelids">
        <rect data-layer="lid-left" class="lid" x="40" y="42" width="20" height="22"/>
        <rect data-layer="lid-right" class="lid" x="68" y="42" width="20" height="22"/>
      </g>
      <rect x="30" y="33" width="68" height="44" rx="20" fill="url(#trr-glow)"/>
      <g data-layer="mouth">
        <path data-layer="mouth-smile" class="mouth-line" d="M59.5 66 Q64 70.5 68.5 66"/>
        <g data-layer="mouth-open" class="mouth-alt">
          <path class="mouth-fill" d="M58.5 65 Q64 66 69.5 65 Q69 73 64 73 Q59 73 58.5 65 Z"/>
          <path class="tongue" d="M60.8 70.6 Q64 68.4 67.2 70.6 Q64 73 60.8 70.6 Z"/>
        </g>
        <path data-layer="mouth-frown" class="mouth-line mouth-alt" d="M59.5 70 Q64 65.5 68.5 70"/>
        <ellipse data-layer="mouth-o" class="mouth-line mouth-alt" cx="64" cy="68" rx="2.4" ry="2.8"/>
        <path data-layer="mouth-flat" class="mouth-line mouth-alt" d="M60.5 67.5 Q62.5 66.2 64.5 67.5 Q66.5 68.8 68 67.2"/>
      </g>
      <path data-layer="tear" class="tear" d="M88 60 C85.6 64 85.6 66.6 88 66.6 C90.4 66.6 90.4 64 88 60 Z"/>
    </g>
    <g data-layer="arm-left">
      <path class="limb" d="M45 89 L38.5 96"/>
      <g data-layer="forearm-left">
        <path class="limb" d="M38.5 96 L37 99.5"/>
        <circle class="hand" cx="37" cy="100.5" r="5.5"/>
      </g>
    </g>
    <g data-layer="arm-right">
      <path class="limb" d="M83 89 L89.5 96"/>
      <g data-layer="forearm-right">
        <path class="limb" d="M89.5 96 L91 99.5"/>
        <circle class="hand" cx="91" cy="100.5" r="5.5"/>
      </g>
    </g>
    <g data-layer="accessories"></g>
  </g>
  <g data-layer="fx">
    <g data-layer="fx-zzz" class="fx-zzz">
      <path data-layer="z1" class="z" d="M94 20 h6 l-6 7 h6"/>
      <path data-layer="z2" class="z" d="M104 10 h5 l-5 6 h5"/>
      <path data-layer="z3" class="z" d="M113 2 h4 l-4 5 h4"/>
    </g>
    <g data-layer="fx-dots" class="fx-dots">
      <circle data-layer="dot1" class="dot" cx="98" cy="15" r="2.8"/>
      <circle data-layer="dot2" class="dot" cx="106.5" cy="15" r="2.8"/>
      <circle data-layer="dot3" class="dot" cx="115" cy="15" r="2.8"/>
    </g>
    <g data-layer="fx-stars" class="fx-stars">
      <path class="star" d="M14 24 l2 4.4 l4.4 2 l-4.4 2 l-2 4.4 l-2 -4.4 l-4.4 -2 l4.4 -2 z"/>
      <path class="star" d="M114 30 l1.5 3.3 l3.3 1.5 l-3.3 1.5 l-1.5 3.3 l-1.5 -3.3 l-3.3 -1.5 l3.3 -1.5 z"/>
      <path class="heart" d="M104 8.5 c-1.6 -3 -6 -2 -5 1.6 c.6 2.2 5 5 5 5 s4.4 -2.8 5 -5 c1 -3.6 -3.4 -4.6 -5 -1.6 z"/>
    </g>
  </g>
  </g>`;

/*
 * Where each layer turns. The origins are in the drawing's own units
 * (transform-box: view-box), so a state can rotate an arm without knowing
 * how big the robot is drawn. The rig squashes from its feet, so a hop lands.
 */
const PIVOTS = {
  frame: '64px 44px',
  base: '64px 119px',
  rig: '64px 119px',
  head: '64px 86px',
  flame: '64px 22px',
  fire: '64px 21px',
  'arm-left': '45px 89px',
  'arm-right': '83px 89px',
  'forearm-left': '38.5px 96px',
  'forearm-right': '89.5px 96px',
  'leg-left': '54px 104px',
  'leg-right': '74px 104px',
  'lid-left': '50px 42px',
  'lid-right': '78px 42px',
  mouth: '64px 68px',
  tear: '88px 60px',
  z1: '97px 23px', z2: '106px 13px', z3: '115px 4px',
};

const BASE_STYLE = `
  svg { display: block; width: 100%; height: auto; overflow: visible; }
  [data-layer] { transform-box: view-box; }
  ${Object.entries(PIVOTS).map(([layer, at]) => `[data-layer="${layer}"] { transform-origin: ${at}; }`).join('\n  ')}
  .shadow { fill: var(--robot-shadow); }
  .shell { fill: var(--robot-body); }
  .ear, .hand, .foot, .limb-fill { fill: var(--robot-body-shade); }
  .limb { fill: none; stroke: var(--robot-body-shade); stroke-width: 8; stroke-linecap: round; }
  .sheen { fill: none; stroke: var(--robot-glint); stroke-width: 3.6; stroke-linecap: round; opacity: .55; }
  .tunic { fill: var(--robot-tunic); }
  .sash { fill: var(--robot-sash); }
  .brooch, .socket { fill: var(--robot-gold); }
  .brooch-pin { fill: var(--robot-gold-deep); }
  .fire { fill: var(--robot-flame); stroke: var(--robot-flame); stroke-width: 0; stroke-linejoin: round; }
  .fire-core { fill: var(--robot-flame-core); }
  .screen, .lid { fill: var(--robot-screen); }
  .eye, .mouth-fill { fill: var(--robot-eye); }
  .glint { fill: var(--robot-glint); }
  .eye .glint, .eye-open .glint { opacity: .95; }
  .eye-line, .mouth-line { fill: none; stroke: var(--robot-eye); stroke-width: 4.2; stroke-linecap: round; stroke-linejoin: round; }
  .mouth-line { stroke-width: 2.6; }
  .eye-joy, .eye-closed, .mouth-alt { opacity: 0; }
  .tongue { fill: var(--robot-pink); }
  .tear { fill: var(--robot-eye); opacity: 0; }
  .lid { transform: scaleY(0); transition: transform .07s ease-in; }
  .z { fill: none; stroke: var(--robot-body-shade); stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
  .star { fill: var(--robot-accent); }
  .heart { fill: var(--robot-pink); }
  .dot { fill: var(--robot-body-shade); }
  .fx-zzz, .fx-stars, .fx-dots { opacity: 0; }
  svg.blinking[data-state] [data-layer^="lid-"] { transform: scaleY(1); }
`;

/*
 * The face alone, zoomed to fill the box, and the strokes thickened so that
 * they still are a pixel wide at 24. The flame is one orange shape there: its
 * yellow heart and its gold socket are a smudge at a favicon's size, and it
 * is drawn fatter, by an outline of its own colour, so it is still a flame at 16. `at` is where it applies: a class, a
 * container query, a media query — the rules are the same.
 */
const SMALL_RULES = `
  [data-layer="frame"] { transform: translateY(20px) scale(1.4); }
  [data-layer="base"], [data-layer="body"], [data-layer="arm-left"], [data-layer="arm-right"],
  [data-layer="accessories"], [data-layer="fx"], .ear, .sheen, .glint-small, .tear,
  .fire-core, .socket { display: none; }
  .fire { stroke-width: 4.5; }
  .eye-line { stroke-width: 6; }
  .mouth-line { stroke-width: 4; }
`;

function smallStyle(at) {
  const scoped = (prefix) => SMALL_RULES.replace(/([^{}]+)\{/g, (_, selectors) =>
    `${selectors.split(',').map((s) => `${prefix} ${s.trim()}`).join(', ')} {`);
  return at.map(([wrap, prefix]) => (wrap ? `${wrap} { ${scoped(prefix)} }` : scoped(prefix))).join('\n');
}

/*
 * The keyframes a state may name. They are prefixed `robot-` when written out,
 * so two robots on the same page — or the page itself — never collide. Most
 * of them squash a little before they stretch: a toy, not a machine.
 */
export const KEYFRAMES = {
  breathe: '0%, 100% { transform: scale(1, 1) } 50% { transform: scale(1.02, .975) }',
  bob: '0%, 100% { transform: rotate(-1.5deg) } 50% { transform: rotate(1.5deg) }',
  sway: '0%, 100% { transform: rotate(-6deg) } 50% { transform: rotate(6deg) }',
  bounce: '0%, 60%, 100% { transform: scale(1, 1) } 15% { transform: scale(1.18, .82) } 30% { transform: scale(.9, 1.12) } 45% { transform: scale(1.04, .97) }',
  scan: '0%, 100% { transform: translate(-3px, -3px) } 40%, 55% { transform: translate(4px, -4px) }',
  ponder: '0%, 100% { transform: rotate(4deg) } 50% { transform: rotate(7deg) translateY(-.6px) }',
  beacon: '0%, 100% { opacity: 1; transform: scale(1) } 50% { opacity: .45; transform: scale(.82) }',
  waver: '0%, 100% { transform: scale(1, 1) skewX(0) } 33% { transform: scale(.96, 1.05) skewX(-4deg) } 66% { transform: scale(1.03, .97) skewX(3deg) }',
  blaze: '0%, 100% { transform: scale(1.15, 1.3) skewX(0) } 25% { transform: scale(1.05, 1.42) skewX(-6deg) } 50% { transform: scale(1.2, 1.22) skewX(2deg) } 75% { transform: scale(1.08, 1.38) skewX(5deg) }',
  smoulder: '0%, 100% { opacity: .5 } 50% { opacity: .85 }',
  'type-left': '0%, 100% { transform: rotate(40deg) } 50% { transform: rotate(62deg) }',
  'type-right': '0%, 100% { transform: rotate(-62deg) } 50% { transform: rotate(-40deg) }',
  nod: '0%, 100% { transform: rotate(0) } 50% { transform: rotate(2deg) translateY(1px) }',
  jiggle: '0%, 100% { transform: scale(1, 1) } 50% { transform: scale(1.015, .985) }',
  hop: '0%, 60%, 100% { transform: translateY(0) scale(1, 1) } 8% { transform: translateY(0) scale(1.1, .88) } 26% { transform: translateY(-16px) scale(.94, 1.07) } 44% { transform: translateY(0) scale(1.08, .92) } 52% { transform: translateY(0) scale(.98, 1.02) }',
  'hop-shadow': '0%, 60%, 100% { transform: scale(1) } 8% { transform: scale(1.08) } 26% { transform: scale(.72) } 44% { transform: scale(1.06) }',
  'wave-left': '0%, 100% { transform: rotate(15deg) } 50% { transform: rotate(55deg) }',
  'wave-right': '0%, 100% { transform: rotate(-15deg) } 50% { transform: rotate(-55deg) }',
  twinkle: '0%, 100% { opacity: 0; transform: scale(.4) } 30%, 60% { opacity: 1; transform: scale(1) }',
  sigh: '0%, 100% { transform: translateY(2px) scale(1, 1) } 50% { transform: translateY(2px) scale(1.025, .965) }',
  wilt: '0%, 100% { transform: rotate(-22deg) } 50% { transform: rotate(-16deg) }',
  glow: '0%, 100% { opacity: 1 } 50% { opacity: .5 }',
  tear: '0% { opacity: 0; transform: translateY(-2px) scale(.5) } 15% { opacity: 1; transform: translateY(0) scale(1) } 75% { opacity: 1; transform: translateY(9px) scale(1) } 100% { opacity: 0; transform: translateY(12px) scale(.8) }',
  snooze: '0%, 100% { transform: translateY(0) rotate(-7deg) } 50% { transform: translateY(1.4px) rotate(-7deg) scaleY(.98) }',
  snore: '0%, 100% { transform: scale(.8) } 50% { transform: scale(1.25) }',
  drift: '0% { opacity: 0; transform: translate(0, 4px) scale(.6) } 25%, 70% { opacity: 1 } 100% { opacity: 0; transform: translate(4px, -6px) scale(1.1) }',
  tick: '0%, 60%, 100% { opacity: .25; transform: translateY(0) } 30% { opacity: 1; transform: translateY(-2px) }',
  tap: '0%, 50%, 100% { transform: rotate(0) } 25% { transform: rotate(-12deg) }',
};

/*
 * The reactions. Each is a label, what it means on the board, and a map of
 * layer → CSS declarations. The plain declarations are the pose (what stays
 * when prefers-reduced-motion switches every animation off); `animation`
 * names keyframes from KEYFRAMES without their prefix. `blink` lets the
 * component close the eyelids at random moments. A face says the state on
 * its own — eyes and mouth — since the small robot has nothing else.
 */
export const STATES = {
  idle: {
    label: 'Idle',
    means: 'waiting for a ticket',
    blink: true,
    layers: {
      rig: { animation: 'breathe 3.2s ease-in-out infinite' },
      head: { animation: 'bob 6.4s ease-in-out infinite' },
      flame: { animation: 'sway 3.2s ease-in-out infinite' },
      fire: { animation: 'waver 1.6s ease-in-out infinite' },
    },
  },
  thinking: {
    label: 'Thinking',
    means: 'a ticket is in progress',
    blink: true,
    layers: {
      head: { transform: 'rotate(4deg)', animation: 'ponder 3s ease-in-out infinite' },
      eyes: { transform: 'translate(4px, -4px)', animation: 'scan 3s ease-in-out infinite' },
      'mouth-smile': { opacity: '0' },
      'mouth-flat': { opacity: '1' },
      'arm-right': { transform: 'rotate(-128deg)' },
      'forearm-right': { transform: 'rotate(-40deg)' },
      fire: { animation: 'beacon 1s ease-in-out infinite' },
    },
  },
  working: {
    label: 'Working',
    means: 'Claude Code is at it',
    blink: true,
    layers: {
      rig: { animation: 'jiggle .32s ease-in-out infinite' },
      'lid-left': { transform: 'scaleY(.3)' },
      'lid-right': { transform: 'scaleY(.3)' },
      'mouth-smile': { opacity: '0' },
      'mouth-flat': { opacity: '1' },
      'arm-left': { transform: 'rotate(40deg)', animation: 'type-left .32s ease-in-out infinite' },
      'arm-right': { transform: 'rotate(-40deg)', animation: 'type-right .32s ease-in-out infinite' },
      'forearm-left': { transform: 'rotate(-50deg)' },
      'forearm-right': { transform: 'rotate(50deg)' },
      head: { animation: 'nod .64s ease-in-out infinite' },
      fire: { transform: 'scale(1.15, 1.3)', animation: 'blaze .48s ease-in-out infinite' },
    },
  },
  success: {
    label: 'Success',
    means: 'the pull request is open',
    layers: {
      rig: { animation: 'hop 1.4s ease-out infinite' },
      base: { animation: 'hop-shadow 1.4s ease-out infinite' },
      'eye-open-left': { opacity: '0' },
      'eye-open-right': { opacity: '0' },
      'eye-joy-left': { opacity: '1' },
      'eye-joy-right': { opacity: '1' },
      'mouth-smile': { opacity: '0' },
      'mouth-open': { opacity: '1' },
      'arm-left': { transform: 'rotate(100deg)' },
      'arm-right': { transform: 'rotate(-100deg)' },
      'forearm-left': { transform: 'rotate(30deg)', animation: 'wave-left .5s ease-in-out infinite' },
      'forearm-right': { transform: 'rotate(-30deg)', animation: 'wave-right .5s ease-in-out infinite' },
      fire: { animation: 'bounce 1.4s ease-out infinite' },
      'fx-stars': { opacity: '1' },
      '.star': { animation: 'twinkle 1.4s ease-in-out infinite', 'transform-box': 'fill-box', 'transform-origin': 'center' },
      '.heart': { animation: 'twinkle 1.4s ease-in-out .35s infinite', 'transform-box': 'fill-box', 'transform-origin': 'center' },
    },
  },
  error: {
    label: 'Error',
    means: 'the ticket is blocked',
    layers: {
      rig: { transform: 'translateY(2px)', animation: 'sigh 3.6s ease-in-out infinite' },
      head: { transform: 'rotate(-5deg)' },
      'lid-left': { transform: 'rotate(-14deg) scaleY(.32)' },
      'lid-right': { transform: 'rotate(14deg) scaleY(.32)' },
      eyes: { transform: 'translateY(2px)' },
      'mouth-smile': { opacity: '0' },
      'mouth-frown': { opacity: '1' },
      'arm-left': { transform: 'rotate(-14deg)' },
      'arm-right': { transform: 'rotate(14deg)' },
      flame: { transform: 'rotate(-22deg)', animation: 'wilt 3.6s ease-in-out infinite' },
      '.fire': { fill: 'var(--robot-alert)', stroke: 'var(--robot-alert)' },
      fire: { animation: 'glow 1.8s ease-in-out infinite' },
      tear: { opacity: '1', animation: 'tear 2.4s ease-in 0.6s infinite' },
    },
  },
  sleep: {
    label: 'Sleep',
    means: 'the queue is empty',
    layers: {
      rig: { transform: 'translateY(1px)' },
      head: { transform: 'rotate(-7deg)', animation: 'snooze 4s ease-in-out infinite' },
      flame: { transform: 'rotate(-12deg)' },
      'eye-open-left': { opacity: '0' },
      'eye-open-right': { opacity: '0' },
      'eye-closed-left': { opacity: '1' },
      'eye-closed-right': { opacity: '1' },
      'mouth-smile': { opacity: '0' },
      'mouth-o': { opacity: '1' },
      mouth: { animation: 'snore 4s ease-in-out infinite' },
      fire: { transform: 'scale(.45)', opacity: '.5', animation: 'smoulder 4s ease-in-out infinite' },
      '.fire-core': { opacity: '0' },
      'fx-zzz': { opacity: '1' },
      z1: { animation: 'drift 3s ease-in-out infinite' },
      z2: { animation: 'drift 3s ease-in-out 1s infinite' },
      z3: { animation: 'drift 3s ease-in-out 2s infinite' },
    },
  },
  waiting: {
    label: 'Waiting',
    means: 'waiting on a person',
    blink: true,
    layers: {
      rig: { animation: 'breathe 4.8s ease-in-out infinite' },
      head: { transform: 'rotate(-6deg)' },
      eyes: { transform: 'translate(5px, -4px)' },
      'mouth-smile': { opacity: '0' },
      'mouth-o': { opacity: '1' },
      'leg-right': { animation: 'tap .9s ease-in-out infinite' },
      'fx-dots': { opacity: '1' },
      dot1: { animation: 'tick 1.8s ease-in-out infinite' },
      dot2: { animation: 'tick 1.8s ease-in-out .3s infinite' },
      dot3: { animation: 'tick 1.8s ease-in-out .6s infinite' },
    },
  },
};

/* Accessories: SVG on the same 128 grid, drawn above the body and the head. */
export const ACCESSORIES = {
  bowtie: `<path fill="var(--robot-accent)" d="M64 89 L55 84.5 Q53 89 55 93.5 Z M64 89 L73 84.5 Q75 89 73 93.5 Z"/>
           <circle fill="var(--robot-accent)" cx="64" cy="89" r="2.6"/>`,
  headset: `<path fill="none" stroke="var(--robot-ink)" stroke-width="3" stroke-linecap="round" d="M16 50 Q14 16 52 16"/>
            <path fill="none" stroke="var(--robot-ink)" stroke-width="2.4" stroke-linecap="round" d="M20 63 Q23 80 40 80"/>
            <circle fill="var(--robot-accent)" cx="41" cy="80" r="2.6"/>`,
};

const DEFAULT_STATE = 'idle';

function declarations(styles, animate) {
  return Object.entries(styles)
    .filter(([prop]) => animate || prop !== 'animation')
    .map(([prop, value]) => `${prop}: ${prop === 'animation' ? value.replace(/^(\S+)/, 'robot-$1') : value};`)
    .join(' ');
}

function stateStyle(animate) {
  const rules = [];
  for (const [name, state] of Object.entries(STATES)) {
    for (const [layer, styles] of Object.entries(state.layers)) {
      const target = layer.startsWith('.') ? layer : `[data-layer="${layer}"]`;
      const body = declarations(styles, animate);
      if (body) rules.push(`svg[data-state="${name}"] ${target} { ${body} }`);
    }
  }
  if (animate) {
    for (const [name, frames] of Object.entries(KEYFRAMES)) rules.push(`@keyframes robot-${name} { ${frames} }`);
    rules.push('@media (prefers-reduced-motion: reduce) { svg, svg * { animation: none !important; transition: none !important; } }');
  }
  return rules.join('\n');
}

function vars(palette) {
  return Object.entries(PALETTES[palette]).map(([k, v]) => `${k}: ${v};`).join(' ');
}

/*
 * The palette sits on the outermost element — :host for the component, the
 * <svg> for a standalone file — so a page can still set --robot-body on the
 * element itself and win.
 */
function paletteStyle(root, themed) {
  return `
  ${root} { ${vars('light')} }
  ${themed('dark')} { ${vars('dark')} }
  @media (prefers-color-scheme: dark) { ${themed('auto')} { ${vars('dark')} } }`;
}

function accessoriesMarkup(names) {
  return (names || []).map((n) => ACCESSORIES[n] || '').join('');
}

/**
 * A self-contained SVG file: the same layers and the same variables, with a
 * pose instead of an animation. `viewBox` crops it; `theme` pins a palette,
 * or leaves `auto` to follow the colour scheme; `small` draws the face alone
 * whatever the size (the favicon). Without it, the face alone is still what
 * an <img> narrower than SMALL shows, or an SVG inline in a container that is.
 */
export function standalone({ state = DEFAULT_STATE, theme = 'auto', viewBox = '0 0 128 128', accessories = [], title = 'Ponos', small = false } = {}) {
  const themed = (t) => (t === 'auto' ? 'svg:not([data-theme="light"])' : `svg[data-theme="${t}"]`);
  const style = paletteStyle('svg', themed) + BASE_STYLE + stateStyle(false)
    + smallStyle([[null, 'svg.small'], [`@media (max-width: ${SMALL}px)`, 'svg'], [`@container (max-width: ${SMALL}px)`, 'svg']]);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}" data-state="${state}" data-theme="${theme}"${small ? ' class="small"' : ''} role="img">
<title>${title}</title>
<style>${style.replace(/\n\s*/g, '\n')}</style>${DRAWING.replace('<g data-layer="accessories"></g>', `<g data-layer="accessories">${accessoriesMarkup(accessories)}</g>`)}
</svg>
`;
}

const SHADOW_STYLE = `
  :host { display: inline-block; width: 100%; aspect-ratio: 1; vertical-align: middle; container-type: inline-size; }
  :host([hidden]) { display: none; }
  :host([still]) svg, :host([still]) svg * { animation: none !important; transition: none !important; }
  ${paletteStyle(':host', (t) => (t === 'auto' ? ':host(:not([theme="light"]))' : `:host([theme="${t}"])`))}
  ${BASE_STYLE}
  ${stateStyle(true)}
  ${smallStyle([[`@container (max-width: ${SMALL}px)`, 'svg']])}
`;

if (typeof customElements !== 'undefined' && !customElements.get('ponos-robot')) {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');

  /* Parsed once for every robot on the page: the stylesheet adopted where the
     browser can share one, and the drawing cloned rather than parsed again. */
  let shared = null;
  if ('adoptedStyleSheets' in Document.prototype) {
    shared = new CSSStyleSheet();
    shared.replaceSync(SHADOW_STYLE);
  }
  const template = document.createElement('template');
  template.innerHTML = `${shared ? '' : `<style>${SHADOW_STYLE}</style>`}<svg viewBox="0 0 128 128" role="img" aria-hidden="true">${DRAWING}</svg>`;

  class PonosRobot extends HTMLElement {
    static observedAttributes = ['state', 'size', 'accessories', 'still'];

    labelled = false;

    constructor() {
      super();
      const root = this.attachShadow({ mode: 'open' });
      if (shared) root.adoptedStyleSheets = [shared];
      root.appendChild(template.content.cloneNode(true));
      this.svg = root.querySelector('svg');
      this.blinkTimer = 0;
    }

    get state() { return this.svg.dataset.state; }
    set state(value) { this.setAttribute('state', value); }

    connectedCallback() {
      this.render();
      this.scheduleBlink();
    }

    disconnectedCallback() {
      clearTimeout(this.blinkTimer);
    }

    attributeChangedCallback(name) {
      this.render();
      if (name === 'still' && this.isConnected) this.scheduleBlink();
    }

    render() {
      const asked = this.getAttribute('state');
      this.svg.dataset.state = asked in STATES ? asked : DEFAULT_STATE;
      const size = parseFloat(this.getAttribute('size'));
      this.style.width = size > 0 ? `${size}px` : '';
      const accessories = accessoriesMarkup((this.getAttribute('accessories') || '').split(/\s+/).filter(Boolean));
      const layer = this.svg.querySelector('[data-layer="accessories"]');
      if (layer.innerHTML !== accessories) layer.innerHTML = accessories;
      if (!this.hasAttribute('role')) this.setAttribute('role', 'img');
      if (!this.hasAttribute('aria-label') || this.labelled) {
        this.labelled = true;
        this.setAttribute('aria-label', `Ponos — ${STATES[this.state].label.toLowerCase()}`);
      }
    }

    /* A blink every few seconds, never on the beat: a fixed rhythm reads as a machine.
       A robot holding still has no timer at all — a board of them would be a
       hundred timers for eyes nobody sees move. */
    scheduleBlink() {
      clearTimeout(this.blinkTimer);
      if (this.hasAttribute('still')) return;
      this.blinkTimer = setTimeout(() => {
        if (this.isConnected && !reduced.matches && STATES[this.state].blink) {
          this.svg.classList.add('blinking');
          setTimeout(() => this.svg.classList.remove('blinking'), 140);
        }
        if (this.isConnected) this.scheduleBlink();
      }, 1800 + Math.random() * 4200);
    }
  }

  customElements.define('ponos-robot', PonosRobot);
}
