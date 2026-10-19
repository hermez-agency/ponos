#!/usr/bin/env node
/*
 * Writes every file of the mascot from its one source,
 * docs/mascot/ponos-robot.js:
 *
 *   docs/mascot/robot.svg     the whole robot, layers and variables kept
 *   docs/mascot/favicon.svg   the face alone, following the browser's colour scheme
 *   docs/mascot/og.png        the Open Graph card, 1200 × 630
 *   docs/mascot/states.png    every state, light and dark, and the sizes
 *   frontend/public/pwa/*     the app icons: the robot on the dark ground
 *   docs/apple-touch-icon.png the same, at the root where an iPhone looks for it
 *   docs/favicon.ico          the face at 16, 32 and 48 px, for whoever asks /favicon.ico
 *   src/ponos/icons/*         the desktop's icons: the robot cut out, for the dock
 *                             and the notifications
 *
 *   node scripts/mascot.mjs
 *
 * Node, not Python like release.py: the drawing is a JavaScript module, and
 * importing it is the only way to be sure the files say what the page shows.
 * The PNGs are screenshots from headless Chrome ($CHROME, or google-chrome on
 * the PATH) — the only rasteriser that reads the SVG exactly as a browser
 * does. The robot on the page stays vector; the PNGs are only for the places
 * that will not take an SVG (social cards, a pull request).
 */

import { execFileSync } from 'node:child_process';
import { copyFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const out = join(root, 'docs', 'mascot');
const source = readFileSync(join(out, 'ponos-robot.js'), 'utf8');
const { STATES, standalone } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

writeFileSync(join(out, 'robot.svg'), standalone({ title: 'Ponos' }));
writeFileSync(join(out, 'favicon.svg'), standalone({ small: true }));

/* The cards are drawn in the product's own tokens — the file the console and
   the landing page share — rather than in colours written here a third time. */
const tokens = `<style>${readFileSync(join(root, 'docs', 'tokens.css'), 'utf8')}</style>`;
const fonts = `<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&family=JetBrains+Mono&display=swap" rel="stylesheet">${tokens}`;

const og = `<!doctype html><html class="dark"><meta charset="utf-8">${fonts}
<style>
  html, body { margin: 0; width: 1200px; height: 630px; overflow: hidden; }
  body { background: radial-gradient(700px 420px at 28% 30%, color-mix(in srgb, var(--primary) 14%, transparent), transparent 70%), var(--background);
         color: var(--foreground); font-family: var(--sans); display: flex; align-items: center; gap: 40px; padding: 0 80px; box-sizing: border-box; }
  .bot { width: 380px; flex: none; }
  .mark { font: 700 60px/1 var(--sans); letter-spacing: -.035em; margin: 0 0 26px; }
  h1 { font: 700 76px/1.02 var(--sans); margin: 0; letter-spacing: -.035em; }
  h1 span { color: var(--primary); }
  p { font-size: 28px; line-height: 1.4; color: var(--muted-foreground); margin: 26px 0 0; }
  p b { color: var(--foreground); font-weight: 600; }
  code { font: 20px var(--mono); color: var(--primary); display: block; margin-top: 30px; }
</style>
<div class="bot">${standalone({ state: 'success', theme: 'dark' })}</div>
<div><div class="mark">Ponos</div><h1>Write the ticket.<br><span>It comes back done.</span></h1>
<p>The robot does the work <b>on your machine</b> — a pull request, a text, an action.</p>
<code>the-ponos.app</code></div>`;

const cells = (theme) => Object.entries(STATES).map(([name, s]) => `
  <figure><div class="bot">${standalone({ state: name, theme })}</div><figcaption><b>${name}</b>${s.means}</figcaption></figure>`).join('');
const sizes = [24, 32, 48, 96, 160].map((px) => `<div class="box" style="width:${px}px">${standalone({ theme: 'dark' })}</div>`).join('');
const faces = Object.keys(STATES).map((name) => `<div class="box" style="width:24px">${standalone({ state: name, theme: 'dark' })}</div>`).join('');

const sheet = `<!doctype html><meta charset="utf-8">${fonts}
<style>
  html, body { margin: 0; width: 1200px; }
  body { font-family: var(--sans); }
  .row { display: grid; grid-template-columns: repeat(${Object.keys(STATES).length}, 1fr); gap: 12px; padding: 28px 28px 20px; }
  .light, .dark { background: var(--background); color: var(--foreground); }
  figure { margin: 0; text-align: center; }
  .bot { width: min(150px, 100%); margin: 0 auto; }
  figcaption { font-size: 13px; opacity: .75; margin-top: 8px; }
  figcaption b { display: block; font: 600 15px var(--mono); opacity: 1; margin-bottom: 2px; }
  .sizes { display: flex; align-items: flex-end; gap: 28px; padding: 16px 28px 32px; }
  .sizes span { font: 12px/1.5 var(--mono); opacity: .6; align-self: center; max-width: 150px; }
  .sizes .faces { display: flex; gap: 14px; margin-left: auto; align-self: center; }
  .box { container-type: inline-size; flex: none; }
</style>
<div class="row light">${cells('light')}</div>
<div class="dark"><div class="row">${cells('dark')}</div>
<div class="sizes">${sizes}<span>Ponos at 24 · 32 · 48 · 96 · 160 px, one SVG</span><div class="faces">${faces}</div><span>every state at 24 px</span></div></div>`;

const chrome = process.env.CHROME || 'google-chrome';
const scratch = mkdtempSync(join(tmpdir(), 'mascot-'));
function shoot(html, target, width, height, { clear = false } = {}) {
  const page = join(scratch, `${basename(target)}.html`);
  writeFileSync(page, html);
  execFileSync(chrome, [
    '--headless=new', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=1',
    `--window-size=${width},${height}`, '--virtual-time-budget=4000',
    ...(clear ? ['--default-background-color=00000000'] : []),
    `--screenshot=${target}`, pathToFileURL(page).href,
  ], { stdio: 'ignore' });
}

/* An .ico is a directory of PNGs: six bytes of header, sixteen per image,
   then the images as they are — every browser since Vista reads it so. */
function ico(pngs) {
  const header = Buffer.alloc(6 + 16 * pngs.length);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(pngs.length, 4);
  let offset = header.length;
  pngs.forEach(([px, data], n) => {
    const at = 6 + 16 * n;
    header.writeUInt8(px % 256, at);
    header.writeUInt8(px % 256, at + 1);
    header.writeUInt16LE(1, at + 4);
    header.writeUInt16LE(32, at + 6);
    header.writeUInt32LE(data.length, at + 8);
    header.writeUInt32LE(offset, at + 12);
    offset += data.length;
  });
  return Buffer.concat([header, ...pngs.map(([, data]) => data)]);
}

/* An app icon is the robot on the dark ground of the console, filling the
   square. The maskable one keeps the robot inside the safe zone the platform
   crops to, so a round or squircle mask never cuts an arm. */
const pwa = join(root, 'frontend', 'public', 'pwa');
const icon = (px, fill) => `<!doctype html><meta charset="utf-8"><style>
  html, body { margin: 0; width: ${px}px; height: ${px}px; overflow: hidden; background: #141414; }
  div { width: 100%; height: 100%; display: grid; place-items: center; }
  .bot { width: ${fill}%; }
</style><div><div class="bot">${standalone({ theme: 'dark' })}</div></div>`;

/* A desktop icon has no ground: the robot alone, on a transparent square that
   a dock or a notification draws on its own colour — an opaque one is drawn as
   a black square. The tab's icon is the face of favicon.svg, cut out the same. */
const desktop = join(root, 'src', 'ponos', 'icons');
const cutout = (px, svg) => `<!doctype html><meta charset="utf-8"><style>
  html, body { margin: 0; width: ${px}px; height: ${px}px; overflow: hidden; background: transparent; }
  svg { display: block; width: 100%; height: 100%; }
</style>${svg}`;
try {
  shoot(og, join(out, 'og.png'), 1200, 630);
  shoot(sheet, join(out, 'states.png'), 1200, 696);
  shoot(icon(512, 84), join(pwa, 'icon-512.png'), 512, 512);
  shoot(icon(192, 84), join(pwa, 'icon-192.png'), 192, 192);
  shoot(icon(180, 84), join(pwa, 'apple-touch-icon.png'), 180, 180);
  shoot(icon(512, 62), join(pwa, 'icon-maskable-512.png'), 512, 512);
  copyFileSync(join(pwa, 'apple-touch-icon.png'), join(root, 'docs', 'apple-touch-icon.png'));
  for (const px of [48, 64, 128, 256]) {
    shoot(cutout(px, standalone({ theme: 'light' })), join(desktop, `ponos-${px}.png`), px, px, { clear: true });
  }
  const faces = [16, 32, 48].map((px) => {
    const target = join(scratch, `favicon-${px}.png`);
    shoot(cutout(px, standalone({ small: true, theme: 'light' })), target, px, px, { clear: true });
    return [px, readFileSync(target)];
  });
  writeFileSync(join(root, 'docs', 'favicon.ico'), ico(faces));
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
console.log('docs/mascot: robot.svg, favicon.svg, og.png, states.png; frontend/public/pwa: the app icons; docs: favicon.ico, apple-touch-icon.png; src/ponos/icons: the desktop icons');
