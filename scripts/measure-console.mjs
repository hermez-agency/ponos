#!/usr/bin/env node
/*
 * How long the console takes to go from page to page on a big board.
 *
 *   node scripts/measure-console.mjs [--runs 3] [--throttle 4] [--keep]
 *
 * Writes a throwaway Markdown board — 350 tickets, 340 of them Done, six
 * projects, three schedules —, starts `ponos serve` on it from this
 * checkout (`PYTHONPATH=src`, so what is measured is `src/ponos/web/
 * static` as the last `npm run build` left it), and drives headless Chrome
 * ($CHROME, or google-chrome on the PATH) over the DevTools protocol. Nothing
 * of yours is read or written: the configuration, the state directory and the
 * board all live in a temporary directory, removed at the end (`--keep` leaves
 * it, and prints where).
 *
 * Node, not a test in tests/run.py: what is measured is a browser, and the
 * suites promise never to need one. No Playwright either — the project installs
 * nothing to be tested, and Node 22+ speaks WebSocket on its own, which is all
 * the protocol asks for.
 *
 * What a line says:
 *   arrive / leave   the board, reached from the projects page by the menu, and
 *                    left for it again: the time until the page is drawn, and the
 *                    longest stretch the main thread was held ("blocked") —
 *                    what a click that does not answer feels like
 *   /api/projects    the request alone, once the list of projects is in cache
 *   Projects         from the click to the list drawn, and to its counts filled
 *   Schedules        from the click to the rows drawn
 * Each figure is the median of the runs.
 */

import { spawn, execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as sleep } from 'node:timers/promises';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const argv = process.argv.slice(2);
const runs = Number(argv[argv.indexOf('--runs') + 1]) || 3;
const keep = argv.includes('--keep');
// A laptop on battery, or a machine busy running sessions: Chrome slowed down
// by this factor (1 is the machine as it is).
const throttle = argv.includes('--throttle') ? Number(argv[argv.indexOf('--throttle') + 1]) : 1;

const TOTAL = 350;
const DONE = 340;
const SERVER_PORT = 8790 + Math.floor(Math.random() * 100);
const CHROME_PORT = 9290 + Math.floor(Math.random() * 100);
const TOKEN = 'measure-console';

const scratch = mkdtempSync(join(tmpdir(), 'ponos-measure-'));
const board = join(scratch, 'board');
const config = join(scratch, 'config.toml');
mkdirSync(join(scratch, 'workspace'));
writeFileSync(
  config,
  `[storage]\nmode = "markdown"\npath = "${board}"\n\n[runner]\nworkspace_root = "${join(scratch, 'workspace')}"\n\n[web]\nport = ${SERVER_PORT}\ntoken = "${TOKEN}"\n`,
);

/* -- the board -------------------------------------------------------------- */

// Written with the board's own writer, so the files are the ones a real
// Markdown board holds; `edited` spread over the last months, one ticket an
// hour, so "the most recent Done" means something.
const seed = `
import datetime, sys
from pathlib import Path
from ponos import files

board = files.Board(Path(sys.argv[1]))
prop = board.settings().prop
projects = [board.create_row("projects", f"Projet {i}", {"Repository": f"user/repo-{i}"}) for i in range(6)]
others = ["ready", "progress", "review", "blocked"]
now = datetime.datetime.now(datetime.timezone.utc)
for i in range(${TOTAL}):
    status = "done" if i < ${DONE} else others[i % len(others)]
    page = board.create_row("tickets", f"Ticket numéro {i}", {prop("status"): status, prop("project"): [projects[i % 6]]})
    _, path = board._find(page)
    front, body = files.parse(path.read_text(encoding="utf-8"))
    front["edited"] = (now - datetime.timedelta(hours=i)).isoformat(timespec="seconds")
    path.write_text(files.render(front, "Un ticket de mesure."), encoding="utf-8")
for i, cadence in enumerate(["Daily", "Weekly", "Monthly"]):
    board.create_row("schedules", f"Revue {cadence}", {prop("cadence"): cadence, prop("at"): "09:00", prop("active"): True, prop("project"): [projects[i]]})
`;
execFileSync('python3', ['-c', seed, board], { env: { ...process.env, PYTHONPATH: join(root, 'src') } });

/* -- the server and the browser --------------------------------------------- */

const children = [];
const stop = () => {
  for (const child of children) child.kill('SIGTERM');
  if (!keep) rmSync(scratch, { recursive: true, force: true });
};
process.on('exit', stop);

const server = spawn('python3', ['-m', 'ponos', 'serve', '--port', String(SERVER_PORT)], {
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
    '--window-size=1512,900',
    '--no-first-run',
    'about:blank',
  ],
  { stdio: 'ignore' },
);
children.push(chrome);

async function until(check, what, timeout = 20_000) {
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

await send('Page.enable');
await send('Runtime.enable');
if (throttle > 1) await send('Emulation.setCPUThrottlingRate', { rate: throttle });
// Every stretch of 50 ms or more the main thread spends without answering.
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: `window.__long = [];
    new PerformanceObserver((list) => { for (const entry of list.getEntries()) window.__long.push([entry.startTime, entry.duration]) })
      .observe({ type: "longtask", buffered: true });`,
});

/* -- in the page ------------------------------------------------------------ */

const PAGE_HELPERS = `
  window.__link = (resource) => [...document.querySelectorAll('a[href*="console/' + resource + '/list"]')]
    .sort((a, b) => a.getAttribute("href").length - b.getAttribute("href").length)[0];
  window.__text = () => document.querySelector("main")?.innerText ?? document.body.innerText;
  window.__wait = (check, timeout = 20000) => new Promise((resolve, reject) => {
    const start = performance.now();
    const tick = () => {
      if (check()) return resolve(performance.now() - start);
      if (performance.now() - start > timeout) return reject(new Error("timeout"));
      setTimeout(tick, 5);
    };
    tick();
  });
  // From a click on the menu to the page drawn: how long, and the longest
  // stretch the main thread was held from the click until a second of quiet.
  window.__go = async (resource, drawn) => {
    const from = performance.now();
    window.__link(resource).click();
    await window.__wait(drawn);
    const arrived = performance.now() - from;
    await new Promise((resolve) => setTimeout(resolve, 1000));
    const held = window.__long.filter(([start]) => start >= from).map(([, duration]) => duration);
    return { arrived, blocked: Math.max(0, ...held), total: held.reduce((a, b) => a + b, 0) };
  };
`;

const cards = `document.querySelectorAll('[draggable="true"]').length`;
const onBoard = `() => ${cards} > 0 && !__text().includes("Reading the board")`;
const onProjects = `() => __text().includes("Projet 5") && !document.querySelector('[draggable="true"]')`;
// The count of a project, drawn as the card draws it ("59 tickets"), in either language.
const counted = `() => /\\b5[89] tickets?\\b/.test(__text())`;
const onSchedules = `() => __text().includes("Revue Monthly")`;

await send('Page.navigate', { url: `${base}/?token=${TOKEN}&view=console/projects/list` });
await until(() => evaluate(`document.readyState === "complete" && !!document.querySelector('a[href*="console/tickets/list"]')`), 'the first page');
await evaluate(PAGE_HELPERS);
await evaluate(`__wait(${onProjects})`);
// The stream's first board, before anything is timed: the board page is a
// page the console has already read, as it is on any afternoon.
await sleep(3000);

const samples = { arrive: [], leave: [], api: [], projects: [], counts: [], schedules: [], shown: [] };
for (let run = 0; run < runs; run += 1) {
  const arrive = await evaluate(`__go("tickets", ${onBoard})`);
  samples.arrive.push(arrive);
  samples.shown.push(await evaluate(cards));
  const leave = await evaluate(`__go("projects", ${onProjects})`);
  samples.leave.push(leave);

  samples.api.push(
    await evaluate(`(async () => { const from = performance.now(); await (await fetch("/api/projects")).json(); return performance.now() - from })()`),
  );

  await evaluate(`__go("schedules", ${onSchedules})`).then((figure) => samples.schedules.push(figure));
  samples.projects.push(
    await evaluate(`(async () => {
      const from = performance.now();
      __link("projects").click();
      await __wait(${onProjects});
      const listed = performance.now() - from;
      await __wait(${counted});
      return { listed, counted: performance.now() - from };
    })()`),
  );
}

// And that the board still says the whole of Done: its heading counts every
// card, and the button under it draws the next ones.
await evaluate(`__go("tickets", ${onBoard})`);
const heading = await evaluate(`[...document.querySelectorAll("header")].map((h) => h.innerText).find((text) => /^Done/.test(text)) ?? ""`);
const before = await evaluate(cards);
await evaluate(`[...document.querySelectorAll("button")].find((b) => /^Show more|^Voir plus/.test(b.innerText))?.click()`);
await sleep(500);
const after = await evaluate(cards);

/* -- what it says ----------------------------------------------------------- */

const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
};
const ms = (value) => `${Math.round(value)} ms`;

console.log(`${TOTAL} tickets, ${DONE} Done — ${runs} run(s), CPU ×${throttle}, median\n`);
console.log('| | |');
console.log('|---|---|');
console.log(`| Board: arrive (drawn) | ${ms(median(samples.arrive.map((s) => s.arrived)))} |`);
console.log(`| Board: arrive (main thread held, longest) | ${ms(median(samples.arrive.map((s) => s.blocked)))} |`);
console.log(`| Board: cards in the page | ${median(samples.shown)} |`);
console.log(`| Board: arrive (main thread held, in all) | ${ms(median(samples.arrive.map((s) => s.total)))} |`);
console.log(`| Board: leave (drawn) | ${ms(median(samples.leave.map((s) => s.arrived)))} |`);
console.log(`| Board: leave (main thread held, longest) | ${ms(median(samples.leave.map((s) => s.blocked)))} |`);
console.log(`| Board: leave (main thread held, in all) | ${ms(median(samples.leave.map((s) => s.total)))} |`);
console.log(`| /api/projects, projects in cache | ${ms(median(samples.api))} |`);
console.log(`| Projects: list drawn | ${ms(median(samples.projects.map((s) => s.listed)))} |`);
console.log(`| Projects: counts filled | ${ms(median(samples.projects.map((s) => s.counted)))} |`);
console.log(`| Schedules: rows drawn | ${ms(median(samples.schedules.map((s) => s.arrived)))} |`);
console.log(`\nDone, as its heading says it: ${heading.replace(/\s+/g, ' ')} — ${before} cards on the board, ${after} after one "Show more".`);
if (keep) console.log(`\nKept: ${scratch}`);

socket.close();
process.exit(0);
