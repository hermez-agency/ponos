#!/usr/bin/env node
/*
 * What a card of a crowded board costs to point at and to open.
 *
 *   node scripts/measure-board.mjs [--runs 5] [--throttle 4] [--whole] [--keep]
 *
 * The board of `measure-console.mjs` is mostly Done, which draws thirty cards
 * whatever it holds. This one is the other kind: 1 800 tickets in flight —
 * drafts, ready, blocked, in review — plus a done of 300, which is
 * the board the audit of November 2026 measured. Each column draws its first
 * page; `--whole` opens every one of them to its last card first, the way
 * "Show more" does, for what a board drawn whole costs. The same throwaway
 * set-up (a Markdown board, `ponos service run` from this checkout on
 * `src/ponos/web/static` as the last `npm run build` left it, headless Chrome
 * over the DevTools protocol), the same promise: nothing of yours is read or
 * written.
 *
 * The mouse is the protocol's (`Input.dispatchMouseEvent`), not a script's
 * `click()`: a pointer the browser moves is what sets `:hover` and fires
 * `pointerenter`, and what Event Timing reports on.
 *
 * What a line says, each the median of the runs, at 1440 px:
 *   hover         the longest Event Timing entry of moving onto a card — from
 *                 the event to the next frame painted after it
 *   click         the longest entry of pressing and releasing on the first
 *                 card of the draft column (pointerdown, pointerup, click)
 *   window drawn  from the press to the ticket's window in the page
 */

import { spawn, execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as sleep } from 'node:timers/promises';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const argv = process.argv.slice(2);
const runs = Number(argv[argv.indexOf('--runs') + 1]) || 5;
const keep = argv.includes('--keep');
const throttle = argv.includes('--throttle') ? Number(argv[argv.indexOf('--throttle') + 1]) : 1;
const whole = argv.includes('--whole');

// In flight, by column; and Done, of which the board draws thirty.
const SPREAD = { draft: 700, ready: 500, blocked: 400, review: 200 };
const DONE = 300;
const TOTAL = Object.values(SPREAD).reduce((a, b) => a + b, DONE);
const SERVER_PORT = 8790 + Math.floor(Math.random() * 100);
const CHROME_PORT = 9290 + Math.floor(Math.random() * 100);
const TOKEN = 'measure-board';

const scratch = mkdtempSync(join(tmpdir(), 'ponos-measure-'));
const board = join(scratch, 'board');
const config = join(scratch, 'config.toml');
mkdirSync(join(scratch, 'workspace'));
writeFileSync(
  config,
  `[storage]\nmode = "markdown"\npath = "${board}"\n\n[runner]\nworkspace_root = "${join(scratch, 'workspace')}"\n\n[web]\nport = ${SERVER_PORT}\ntoken = "${TOKEN}"\n`,
);

/* -- the board -------------------------------------------------------------- */

const seed = `
import datetime, json, sys
from pathlib import Path
from ponos import files

board = files.Board(Path(sys.argv[1]))
prop = board.settings().prop
projects = [board.create_row("projects", f"Projet {i}", {"Repository": f"user/repo-{i}"}) for i in range(6)]
spread = json.loads(sys.argv[2]) | {"done": ${DONE}}
now = datetime.datetime.now(datetime.timezone.utc)
i = 0
for status, count in spread.items():
    for _ in range(count):
        page = board.create_row("tickets", f"Ticket numéro {i}", {prop("status"): status, prop("project"): [projects[i % 6]]})
        _, path = board._find(page)
        front, body = files.parse(path.read_text(encoding="utf-8"))
        front["edited"] = (now - datetime.timedelta(hours=i)).isoformat(timespec="seconds")
        path.write_text(files.render(front, "Un ticket de mesure."), encoding="utf-8")
        i += 1
`;
execFileSync('python3', ['-c', seed, board, JSON.stringify(SPREAD)], {
  env: { ...process.env, PYTHONPATH: join(root, 'src') },
});

/* -- the server and the browser --------------------------------------------- */

const children = [];
const stop = () => {
  for (const child of children) child.kill('SIGTERM');
  // Chrome may still be writing its profile as it goes: tried again a few times.
  if (!keep) rmSync(scratch, { recursive: true, force: true, maxRetries: 10 });
};
process.on('exit', stop);

const server = spawn('python3', ['-m', 'ponos', 'service', 'run', '--port', String(SERVER_PORT)], {
  cwd: root,
  env: {
    ...process.env,
    PYTHONPATH: join(root, 'src'),
    PONOS_CONFIG: config,
    XDG_STATE_HOME: join(scratch, 'state'),
  },
  stdio: 'ignore',
});
children.push(server);

const chrome = spawn(
  process.env.CHROME || 'google-chrome',
  [
    '--headless=new',
    `--remote-debugging-port=${CHROME_PORT}`,
    `--user-data-dir=${join(scratch, 'chrome')}`,
    '--window-size=1440,900',
    '--no-first-run',
    'about:blank',
  ],
  { stdio: 'ignore' },
);
children.push(chrome);

async function until(check, what, timeout = 30_000) {
  const start = Date.now();
  for (;;) {
    try {
      const value = await check();
      if (value) return value;
    } catch {
      // Not up yet.
    }
    if (Date.now() - start > timeout) throw new Error(`gave up waiting for ${what}`);
    await sleep(100);
  }
}

const base = `http://127.0.0.1:${SERVER_PORT}`;
await until(() => fetch(`${base}/`).then((answer) => answer.status < 500), 'the console');
const target = await until(
  () =>
    fetch(`http://127.0.0.1:${CHROME_PORT}/json/list`)
      .then((answer) => answer.json())
      .then((list) => list.find((item) => item.type === 'page')),
  'headless Chrome',
);

/* -- the protocol ----------------------------------------------------------- */

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve) => socket.addEventListener('open', resolve, { once: true }));
let next = 0;
const pending = new Map();
socket.addEventListener('message', (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    pending.get(message.id)(message);
    pending.delete(message.id);
  }
});
const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const id = ++next;
    pending.set(id, (message) => (message.error ? reject(new Error(message.error.message)) : resolve(message.result)));
    socket.send(JSON.stringify({ id, method, params }));
  });
const evaluate = async (expression) => {
  const { result, exceptionDetails } = await send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (exceptionDetails) throw new Error(exceptionDetails.exception?.description ?? exceptionDetails.text);
  return result.value;
};
const mouse = (type, x, y) =>
  send('Input.dispatchMouseEvent', { type, x, y, button: type === 'mouseMoved' ? 'none' : 'left', clickCount: 1 });
const key = async (name, code) => {
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: name, code: name, windowsVirtualKeyCode: code });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: name, code: name, windowsVirtualKeyCode: code });
};

await send('Page.enable');
await send('Runtime.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
if (throttle > 1) await send('Emulation.setCPUThrottlingRate', { rate: throttle });
// Every event that took 16 ms or more from its arrival to the next paint.
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: `window.__events = [];
    new PerformanceObserver((list) => { for (const entry of list.getEntries()) window.__events.push([entry.name, entry.startTime, entry.duration]) })
      .observe({ type: "event", durationThreshold: 16, buffered: true });`,
});

await send('Page.navigate', { url: `${base}/?token=${TOKEN}&view=console/tickets/list` });
const cards = `document.querySelectorAll('[data-ticket-card]').length`;
// The draft column, found by its heading, in either language.
const drafts = `[...document.querySelectorAll('[data-slot="board-column-cards"]')]
  .find((cards) => /^(Draft|Brouillon)\\s/.test(cards.parentElement.querySelector("header")?.innerText ?? ""))`;
await until(() => evaluate(`!!${drafts}?.querySelector("[data-record-card]")`), 'the board', 60_000);
// The stream's first board, and the page quiet, before anything is timed.
await sleep(3000);

// Every column opened to its last card, the way "Show more" does it.
if (whole) {
  await evaluate(`(async () => {
    for (;;) {
      const button = [...document.querySelectorAll("button")].find((b) => /^(Show more|Voir plus) \\(/.test(b.innerText));
      if (!button) return;
      button.click();
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  })()`);
  await sleep(3000);
}

// A spot on a card, by its index among the draft column's, clear of its
// title, its buttons and its foot: a press on the card itself.
const spot = (index) =>
  evaluate(`(() => {
    const card = ${drafts}.querySelectorAll("[data-record-card]")[${index}];
    card.scrollIntoView({ block: "center" });
    const box = card.getBoundingClientRect();
    return { x: box.left + box.width - 12, y: box.top + 8 };
  })()`);
const since = (from, names) =>
  evaluate(
    `Math.max(0, ...__events.filter(([name, start]) => start >= ${from} && ${JSON.stringify(names)}.includes(name)).map(([, , duration]) => duration))`,
  );

const samples = { hover: [], click: [], drawn: [] };
for (let run = 0; run < runs; run += 1) {
  // Onto a card from beside the column, twice: nothing clicked.
  for (const index of [2 + run * 2, 3 + run * 2]) {
    const { x, y } = await spot(index);
    await mouse('mouseMoved', x - 200, y);
    await sleep(300);
    const from = await evaluate('performance.now()');
    await mouse('mouseMoved', x, y);
    await sleep(500);
    samples.hover.push(await since(from, ['pointerover', 'pointerenter', 'mouseover', 'mouseenter', 'pointermove', 'mousemove']));
  }

  // The first draft, pressed and released, until its window is in the page.
  const { x, y } = await spot(0);
  await mouse('mouseMoved', x, y);
  await sleep(500);
  const from = await evaluate('performance.now()');
  await mouse('mousePressed', x, y);
  await mouse('mouseReleased', x, y);
  samples.drawn.push(
    await evaluate(`new Promise((resolve) => {
      const tick = () => document.querySelector('[role="dialog"]') ? resolve(performance.now() - ${from}) : setTimeout(tick, 2);
      tick();
    })`),
  );
  await sleep(800);
  samples.click.push(await since(from, ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']));
  await key('Escape', 27);
  await until(() => evaluate(`!document.querySelector('[role="dialog"]')`), 'the window to close');
  await sleep(800);
}

/* -- what it says ----------------------------------------------------------- */

const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
};
const ms = (value) => `${Math.round(value)} ms`;

console.log(`${TOTAL} tickets, ${await evaluate(cards)} cards drawn — ${runs} run(s), CPU ×${throttle}, median\n`);
console.log('| | |');
console.log('|---|---|');
console.log(`| Hover: longest event | ${ms(median(samples.hover))} |`);
console.log(`| Click: longest event | ${ms(median(samples.click))} |`);
console.log(`| Click: window drawn | ${ms(median(samples.drawn))} |`);
if (keep) console.log(`\nKept: ${scratch}`);

socket.close();
process.exit(0);
