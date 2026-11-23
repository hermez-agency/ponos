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
 * standalone SVG, the Open Graph image and the sheet of states are all written
 * from this module by `node scripts/mascot.mjs`, never drawn twice. The app's
 * icon is not the robot: it is the logo, `ponos-logo.js` beside this file.
 * Nothing here touches the DOM at import time, so Node can import it.
 *
 * The robot is its head and nothing else — the very head of the logo: two
 * ears, a flame with its heart, an orange shell and its screen, in two
 * oranges, and a face drawn in one colour on the screen. No body, no
 * gradient, no gloss: at the size a card draws it, a detail is a smudge, and
 * a face is all a state needs.
 *
 * Two tables make the robot, and extending it means adding a row to one of
 * them, never copying the drawing:
 *
 *   PALETTES     the colours, as CSS variables (--robot-body, --robot-eye…),
 *                for a light and a dark background;
 *   STATES       each reaction: its face, what it draws around the head, and
 *                which layer gets which style and which keyframes (declared
 *                in KEYFRAMES).
 *
 *   <script src="mascot/ponos-robot.js" type="module"></script>
 *   <ponos-robot state="thinking" theme="dark" size="96"></ponos-robot>
 *
 * Attributes: `state` (a key of STATES, idle by default), `theme` (light,
 * dark, or auto — the default, which follows prefers-color-scheme),
 * `size` (pixels; without it the robot takes the width of its container),
 * `still` (hold the pose, never move nor blink — what a list of a hundred
 * robots asks for, where only the ones that are doing something should look
 * like it).
 *
 * The web console bundles this very file rather than a copy of it: a hundred
 * robots on one board is a hundred shadow roots, so they share one stylesheet
 * and clone one parsed drawing instead of each parsing their own.
 *
 * Most of those robots are drawn at 16 to 32 pixels — a card, a toast, the
 * bar. Under SMALL pixels wide ears, the flame's heart and a thin mouth are a
 * smudge: the robot is the logo's simple head, with bigger eyes that still
 * say the state. It is a CSS query, not an attribute, so nobody has to
 * remember to ask for it.
 */

/* The flat drawing reads the same on a light and a dark ground — the head is
   orange on both — so the two sets agree; they are kept apart for a page that
   would change one and not the other. */
const COLOURS = {
  '--robot-body': '#E8611A',
  '--robot-body-shade': '#BF4A02',
  '--robot-screen': '#1c1917',
  '--robot-eye': '#FFE1CC',
  '--robot-flame': '#E8611A',
  '--robot-ash': '#a8a29e',
  '--robot-ash-core': '#e7e5e4',
};

export const PALETTES = {
  light: { ...COLOURS },
  dark: { ...COLOURS },
};

/* Below this width, in CSS pixels, the simple head is drawn — the logo's
   threshold, `SMALL` in ponos-logo.js. */
const SMALL = 24;

/*
 * The reactions. Each is a label, what it means on the board, its `face` (SVG
 * on the screen, in the drawing's units, inked with the classes `ink` and
 * `line`), its `tiny` face (the same, on the simple head under SMALL: bigger
 * eyes, thicker strokes, the mouth left out where the eyes say enough), an
 * optional `fx` drawn around the head, and a map of layer → CSS
 * declarations. The plain declarations are the pose (what stays when
 * prefers-reduced-motion switches every animation off); `animation` names
 * keyframes from KEYFRAMES without their prefix. `blink` lets the component
 * close the eyes — the group of class `eyes` — at random moments.
 */
export const STATES = {
  idle: {
    label: 'Idle',
    means: 'waiting for a ticket',
    blink: true,
    face: `<g class="eyes"><ellipse class="ink" cx="46" cy="66" rx="7.5" ry="9"/><ellipse class="ink" cx="74" cy="66" rx="7.5" ry="9"/></g>
      <path class="line" d="M53 82Q60 87 67 82"/>`,
    tiny: '<g class="eyes"><circle class="ink" cx="44" cy="72" r="11"/><circle class="ink" cx="76" cy="72" r="11"/></g>',
    layers: {
      rig: { animation: 'breathe 3.2s ease-in-out infinite' },
      flame: { animation: 'waver 1.6s ease-in-out infinite' },
    },
  },
  thinking: {
    label: 'Thinking',
    means: 'a ticket is in progress',
    blink: true,
    face: `<g class="eyes"><ellipse class="ink" cx="50" cy="62" rx="7.5" ry="9"/><ellipse class="ink" cx="78" cy="62" rx="7.5" ry="9"/></g>
      <path class="line" d="M56 83H64"/>`,
    tiny: '<g class="eyes"><circle class="ink" cx="50" cy="66" r="10"/><circle class="ink" cx="81" cy="66" r="10"/></g>',
    layers: {
      rig: { animation: 'breathe 3.2s ease-in-out infinite' },
      flame: { animation: 'waver 1.1s ease-in-out infinite' },
    },
  },
  working: {
    label: 'Working',
    means: 'Claude Code is at it',
    blink: true,
    face: `<g class="eyes"><rect class="ink" x="37" y="63" width="18" height="7" rx="3.5"/><rect class="ink" x="65" y="63" width="18" height="7" rx="3.5"/></g>
      <path class="line" d="M54 83H66"/>`,
    tiny: '<g class="eyes"><rect class="ink" x="28" y="65" width="30" height="13" rx="6.5"/><rect class="ink" x="62" y="65" width="30" height="13" rx="6.5"/></g>',
    layers: {
      rig: { animation: 'breathe 1.6s ease-in-out infinite' },
      flame: { animation: 'waver .7s ease-in-out infinite' },
    },
  },
  success: {
    label: 'Success',
    means: 'the pull request is open',
    face: `<path class="line" d="M38 70Q46 59 54 70M66 70Q74 59 82 70"/>
      <path class="line" d="M51 79Q60 89 69 79"/>`,
    tiny: '<path class="line" d="M31 79Q44 59 57 79M63 79Q76 59 89 79"/>',
    fx: '<path data-layer="spark" class="spark" d="M104 5Q105.4 12.6 113 14Q105.4 15.4 104 23Q102.6 15.4 95 14Q102.6 12.6 104 5Z"/>',
    layers: {
      rig: { animation: 'breathe 3.2s ease-in-out infinite' },
      flame: { animation: 'waver 1.6s ease-in-out infinite' },
      spark: { animation: 'twinkle 1.6s ease-in-out infinite' },
    },
  },
  error: {
    label: 'Error',
    means: 'the ticket is blocked',
    face: `<g class="eyes"><circle class="ink" cx="46" cy="68" r="6.5"/><circle class="ink" cx="74" cy="68" r="6.5"/></g>
      <path class="line" d="M53 86Q60 79 67 86"/>`,
    tiny: '<g class="eyes"><circle class="ink" cx="44" cy="66" r="8"/><circle class="ink" cx="76" cy="66" r="8"/></g><path class="line" d="M48 93Q60 83 72 93"/>',
    layers: {
      rig: { animation: 'breathe 4.8s ease-in-out infinite' },
      // A fire gone out: grey, its heart paler, and still.
      '.flame': { fill: 'var(--robot-ash)' },
      '.core': { fill: 'var(--robot-ash-core)' },
    },
  },
  sleep: {
    label: 'Sleep',
    means: 'the queue is empty',
    face: `<path class="line" d="M38 66Q46 72 54 66M66 66Q74 72 82 66"/>
      <circle class="ink" cx="60" cy="82" r="3"/>`,
    tiny: '<path class="line" d="M31 70Q44 82 57 70M63 70Q76 82 89 70"/>',
    fx: `<path data-layer="z1" class="z" d="M84 15h8l-8 9h8"/>
      <path data-layer="z2" class="z" d="M97 4h6l-6 7h6"/>`,
    layers: {
      rig: { animation: 'breathe 4.8s ease-in-out infinite' },
      flame: { transform: 'scale(.58)' },
      z1: { animation: 'drift 3.2s ease-in-out infinite' },
      z2: { animation: 'drift 3.2s ease-in-out 1.6s infinite' },
    },
  },
  waiting: {
    label: 'Waiting',
    means: 'waiting on a person',
    face: `<circle data-layer="dot1" class="ink" cx="44" cy="69" r="5"/>
      <circle data-layer="dot2" class="ink" cx="60" cy="69" r="5"/>
      <circle data-layer="dot3" class="ink" cx="76" cy="69" r="5"/>`,
    tiny: `<circle data-layer="dot1" class="ink" cx="35" cy="72" r="9"/>
      <circle data-layer="dot2" class="ink" cx="60" cy="72" r="9"/>
      <circle data-layer="dot3" class="ink" cx="85" cy="72" r="9"/>`,
    layers: {
      rig: { animation: 'breathe 4.8s ease-in-out infinite' },
      flame: { animation: 'waver 1.6s ease-in-out infinite' },
      dot1: { animation: 'tick 1.8s ease-in-out infinite' },
      dot2: { animation: 'tick 1.8s ease-in-out .3s infinite' },
      dot3: { animation: 'tick 1.8s ease-in-out .6s infinite' },
    },
  },
};

/*
 * The drawing, on the logo's 120 × 120 grid: the head of `ponos-logo.js`,
 * nothing under it. Every group carries a `data-layer`: `rig` is everything
 * that breathes, `head` the ears, the flame, the shell and its screen, and
 * every state's face on it — only the one of the state is shown; `fx` what a
 * state draws around the head. The head is drawn twice: `.full`, and `.simple`,
 * the logo's simple head with a big-eyed `tiny` face per state — one of the
 * two is shown, by SMALL.
 */
const faces = (key) => Object.entries(STATES)
  .map(([name, state]) => (state[key] ? `<g class="${key}" data-face="${name}">${state[key]}</g>` : '')).join('');

const DRAWING = `
  <g data-layer="rig">
    <g data-layer="head">
      <g class="full">
        <rect class="ear" x="3" y="60" width="9" height="24" rx="4.5"/>
        <rect class="ear" x="108" y="60" width="9" height="24" rx="4.5"/>
      </g>
      <g data-layer="flame">
        <g class="full">
          <path class="flame" d="M60 4C70 14 72 22 68.5 28C66.5 31.5 53.5 31.5 51.5 28C48 22 50 14 60 4Z"/>
          <path class="core" d="M60 14C64 18 65 21.5 63.2 24.2C62 26 58 26 56.8 24.2C55 21.5 56 18 60 14Z"/>
        </g>
        <path class="flame simple" d="M60 3C70 13 72 21 68.5 27C66.5 30.5 53.5 30.5 51.5 27C48 21 50 13 60 3Z"/>
      </g>
      <g class="full">
        <rect class="shell" x="8" y="30" width="104" height="84" rx="32"/>
        <rect class="screen" x="19" y="41" width="82" height="56" rx="20"/>
        ${faces('face')}
      </g>
      <g class="simple">
        <rect class="shell" x="6" y="30" width="108" height="86" rx="32"/>
        <rect class="screen" x="18" y="42" width="84" height="60" rx="20"/>
        ${faces('tiny')}
      </g>
    </g>
  </g>
  <g data-layer="fx">${faces('fx')}</g>`;

/*
 * Where each layer turns. The origins are in the drawing's own units
 * (transform-box: view-box), so a state can scale the flame without knowing
 * how big the robot is drawn. The rig breathes from the bottom of the head,
 * the flame from where it meets it.
 */
const PIVOTS = {
  rig: '60px 115px',
  flame: '60px 30px',
  spark: '104px 14px',
  z1: '88px 19px', z2: '100px 7px',
  dot1: '44px 69px', dot2: '60px 69px', dot3: '76px 69px',
};

const BASE_STYLE = `
  svg { display: block; width: 100%; height: auto; overflow: visible; }
  [data-layer] { transform-box: view-box; }
  ${Object.entries(PIVOTS).map(([layer, at]) => `[data-layer="${layer}"] { transform-origin: ${at}; }`).join('\n  ')}
  .shell { fill: var(--robot-body); }
  .ear { fill: var(--robot-body-shade); }
  .screen { fill: var(--robot-screen); }
  .flame, .spark { fill: var(--robot-flame); }
  .core, .ink { fill: var(--robot-eye); }
  .line { fill: none; stroke: var(--robot-eye); stroke-width: 3.5; stroke-linecap: round; stroke-linejoin: round; }
  .z { fill: none; stroke: var(--robot-flame); stroke-width: 2.5; stroke-linecap: round; stroke-linejoin: round; }
  .face, .tiny, .fx, .simple { display: none; }
  .eyes { transform-box: fill-box; transform-origin: center; transition: transform .07s ease-in; }
  svg.blinking[data-state] .eyes { transform: scaleY(.1); }
`;

/*
 * The logo's simple head — no ears, no heart in the flame — with the state's
 * big-eyed face, and nothing around it: the strokes are thickened so that
 * they still are more than a pixel wide at 16. `at` is where it applies: a
 * class, a container query, a media query — the rules are the same.
 */
const SMALL_RULES = `
  .full, [data-layer="fx"] { display: none; }
  .simple { display: inline; }
  .line { stroke-width: 9; }
`;

function smallStyle(at) {
  const scoped = (prefix) => SMALL_RULES.replace(/([^{}]+)\{/g, (_, selectors) =>
    `${selectors.split(',').map((s) => `${prefix} ${s.trim()}`).join(', ')} {`);
  return at.map(([wrap, prefix]) => (wrap ? `${wrap} { ${scoped(prefix)} }` : scoped(prefix))).join('\n');
}

/*
 * The keyframes a state may name. They are prefixed `robot-` when written out,
 * so two robots on the same page — or the page itself — never collide. They
 * stay small: a breath, a flame in the draught, a spark — a robot at work, not
 * a toy asking to be looked at.
 */
export const KEYFRAMES = {
  breathe: '0%, 100% { transform: scale(1, 1) } 50% { transform: scale(1.015, .985) }',
  waver: '0%, 100% { transform: scale(1, 1) skewX(0) } 33% { transform: scale(.97, 1.04) skewX(-4deg) } 66% { transform: scale(1.02, .98) skewX(3deg) }',
  twinkle: '0%, 100% { opacity: .55; transform: scale(.7) } 50% { opacity: 1; transform: scale(1) }',
  drift: '0% { opacity: 0; transform: translate(0, 3px) } 25%, 70% { opacity: 1 } 100% { opacity: 0; transform: translate(3px, -4px) }',
  tick: '0%, 60%, 100% { opacity: .35; transform: translateY(0) } 30% { opacity: 1; transform: translateY(-2px) }',
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
    rules.push(`svg[data-state="${name}"] [data-face="${name}"] { display: inline; }`);
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

/**
 * A self-contained SVG file: the same layers and the same variables, with a
 * pose instead of an animation. `viewBox` crops it; `theme` pins a palette,
 * or leaves `auto` to follow the colour scheme; `small` draws the simple head
 * whatever the size. Without it, the simple head is still what an <img>
 * narrower than SMALL shows, or an SVG inline in a container that is.
 */
export function standalone({ state = DEFAULT_STATE, theme = 'auto', viewBox = '0 0 120 120', title = 'Ponos', small = false } = {}) {
  const themed = (t) => (t === 'auto' ? 'svg:not([data-theme="light"])' : `svg[data-theme="${t}"]`);
  const style = paletteStyle('svg', themed) + BASE_STYLE + stateStyle(false)
    + smallStyle([[null, 'svg.small'], [`@media (max-width: ${SMALL}px)`, 'svg'], [`@container (max-width: ${SMALL}px)`, 'svg']]);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}" data-state="${state}" data-theme="${theme}"${small ? ' class="small"' : ''} role="img">
<title>${title}</title>
<style>${style.replace(/\n\s*/g, '\n')}</style>${DRAWING}
</svg>
`;
}

/* The element is a square, like the drawing: the pages that embed it size it
   by its width, and the head fills it. */
const SHADOW_STYLE = `
  :host { display: inline-block; width: 100%; aspect-ratio: 1; vertical-align: middle; container-type: inline-size; }
  :host([hidden]) { display: none; }
  :host([still]) svg, :host([still]) svg * { animation: none !important; transition: none !important; }
  ${paletteStyle(':host', (t) => (t === 'auto' ? ':host(:not([theme="light"]))' : `:host([theme="${t}"])`))}
  ${BASE_STYLE}
  svg { height: 100%; }
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
  template.innerHTML = `${shared ? '' : `<style>${SHADOW_STYLE}</style>`}<svg viewBox="0 0 120 120" role="img" aria-hidden="true">${DRAWING}</svg>`;

  class PonosRobot extends HTMLElement {
    static observedAttributes = ['state', 'size', 'still'];

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
