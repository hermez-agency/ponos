#!/usr/bin/env node
/*
 * The loop the landing page shows after its hero, filmed on the real console.
 *
 *   node scripts/film-console.mjs [--theme light|dark] [--keep] [--look]
 *
 * Writes docs/media/console-loop-{light,dark}.mp4, 1280 × 800, and a poster
 * for each (-poster.webp): one ticket written in "New ticket", taken by Ponos,
 * back in review with what it cost, and validated — about eighteen seconds,
 * the last picture fading into the first so that the loop has no seam. Then it
 * writes into docs/index.html the second at which each of the four gestures
 * begins (data-cues-light, data-cues-dark), for the legend under the film to
 * follow it. `--look` films without writing anything, and leaves a contact
 * sheet of the frames to look at instead (with `--keep`).
 *
 * What is filmed is the console as this checkout builds it (`PYTHONPATH=src`,
 * `src/ponos/web/static` as the last `npm run build` left it), served
 * by `ponos service run` on a throwaway board in a `ponos.db` — the demonstration
 * board of docs/console/*.webp, three projects and a few tickets — and driven
 * by headless Chrome ($CHROME, or google-chrome) over the DevTools protocol, as
 * scripts/measure-console.mjs does. Nothing of yours is read or written: the
 * configuration, the state directory, HOME and the board all live in a
 * temporary directory, removed at the end (`--keep` leaves it, and prints
 * where). ffmpeg turns the frames into the videos.
 *
 * No Claude Code session runs, and nothing is paid for. The run is played by a
 * stand-in (RUN below) that does what a pass leaves behind it, with the
 * runner's own pieces: it holds the run lock (`state.lock`), writes the session
 * log where a session writes it (`state.log_file`), in Claude Code's
 * stream-json — the console tails it into the card's live line and Ponos's
 * face, as it does for a real session — and moves the ticket and writes its
 * cost with the board's own writer. Then it asks the console to read the board
 * again (`/api/refresh`, the bar's "Resynchronise now") rather
 * than wait the fifteen seconds of its poll. What the visitor sees of the
 * console is the console, untouched. The one thing laid over it is a pointer,
 * since a headless browser draws none, and a click nobody sees made is a card
 * that moves on its own.
 */

import { spawn, execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as sleep } from 'node:timers/promises';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const argv = process.argv.slice(2);
const keep = argv.includes('--keep');
const look = argv.includes('--look');
const themes = argv.includes('--theme') ? [argv[argv.indexOf('--theme') + 1]] : ['light', 'dark'];
const out = join(root, 'docs', 'media');

// A laptop's screen rather than a 1440 one: the board's text comes out a size
// larger in the film, which the page shows a little narrower than that.
const WIDTH = 1280;
const HEIGHT = 800;
const TOKEN = 'film-console';
const TITLE = 'Add a FAQ to the pricing page';

// What the console writes is kept to its owner, as the health band checks.
process.umask(0o077);
const scratch = mkdtempSync(join(tmpdir(), 'ponos-film-'));
const children = [];
const stop = () => {
  for (const child of children) child.kill('SIGTERM');
  if (!keep) rmSync(scratch, { recursive: true, force: true });
};
process.on('exit', stop);
process.on('SIGINT', () => process.exit(130));

/* -- the board -------------------------------------------------------------- */

// The demonstration board of the console's screenshots, written through
// the board's own store. Nothing in progress: the board opens on Ready, In
// review and Validated, and the one ticket that moves is the one filmed. Each
// type of work is written once, or the health band opens on a warning.
const SEED = `
import datetime
from ponos import config, db, ledger, pages

settings = config.Notion()
board = ledger.Ledger(pages.Pages(settings), settings)
board.workspace(settings)
prop = settings.prop
projects = {name: board.create_row("projects", name, {"Repository": f"acme/{slug}"})
            for name, slug in (("Landing page", "landing"), ("Billing API", "billing"), ("Newsletter", "newsletter"))}
now = datetime.datetime.now(datetime.timezone.utc)
for title, status, project, kind, priority, cost, days in (
    ("Add a dark mode to the pricing page", "ready", "Landing page", "Code", 75, 0, 3),
    ("Fix rounding on VAT totals", "review", "Billing API", "Code", 75, 1.64, 5),
    ("Draft the October newsletter", "done", "Newsletter", "Rédaction", 50, 0.52, 12),
    ("Write the release notes for 2.4", "done", "Newsletter", "Publication", 50, 0.73, 19),
    ("Book the launch webinar", "validated", "Newsletter", "Action externe", 25, 0.31, 9),
    ("Compress the hero images", "validated", "Landing page", "Code", 50, 1.12, 16),
):
    values = {prop("status"): status, prop("project"): [projects[project]], prop("type"): kind, prop("priority"): priority}
    if kind == "Code":
        values[prop("subtype")] = "Feature"
    if cost:
        values[prop("cost")] = cost
    page = board.create_row("tickets", title, values)
    board.replace_markdown(page, "A ticket of the demonstration board.")
    moment = (now - datetime.timedelta(days=days)).isoformat(timespec="seconds")
    with db.transaction() as connection:
        connection.execute("UPDATE tickets SET created_at = ?, edited_at = ? WHERE id = ?", (moment, moment, page))
print(projects["Landing page"])
`;

/* -- the run, played ---------------------------------------------------------- */

// One line on stdin, one thing a pass does. `claim` takes the lock and moves
// the ticket to In progress; `use` is a tool call in the session's log;
// `deliver` ends the session — its result, with its cost —, writes the cost
// and moves the ticket to In review, and lets the lock go.
const RUN = `
import json, sys, time, urllib.request
from ponos import config, ledger, pages, state
from ponos.ticket import short_id

settings = config.Notion()
board = ledger.Ledger(pages.Pages(settings), settings)
board.workspace(settings)
prop = settings.prop
base, token = sys.argv[1], sys.argv[2]
lock = None
log = None
page = ""

def refresh():
    request = urllib.request.Request(base + "/api/refresh", data=b"{}", method="POST", headers={
        "Content-Type": "application/json", "X-Ponos": "1", "Cookie": "ponos_token=" + token})
    urllib.request.urlopen(request).read()

def write(event):
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\\n")

for line in sys.stdin:
    command, _, rest = line.strip().partition(" ")
    if command == "claim":
        page = next(row.id for row in board.query("tickets") if row.title == rest)
        lock = state.lock()
        lock.__enter__()
        log = state.log_file(short_id(page))
        write({"type": "system", "subtype": "init"})
        board.update("tickets", page, {prop("status"): "progress"})
        refresh()
    elif command == "use":
        name, given = json.loads(rest)
        write({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": given}]}})
    elif command == "deliver":
        cost = float(rest)
        write({"type": "result", "result": "Done.", "total_cost_usd": cost, "duration_ms": 372000, "num_turns": 27})
        board.update("tickets", page, {prop("status"): "review", prop("cost"): cost})
        # The report a run leaves on the page, which the Decide tab reads back.
        board.comment(page, "\u2705 Done \u2014 6 min, $%.2f\\nAdds a FAQ under the pricing table: six questions, one accordion.\\nhttps://github.com/acme/landing/pull/42" % cost)
        lock.__exit__(None, None, None)
        refresh()
    print("ok", flush=True)
`;

/* -- a stage per film ------------------------------------------------------------ */

// Each theme is filmed on a board of its own, fresh: the ticket the first
// film validated is not on the second one's board.
const CHROME_PORT = 9390 + Math.floor(Math.random() * 100);
// The console's own checks need a `claude`, a `gh` and a `systemctl` that
// answer for themselves, or the health band opens the dashboard on a thing to
// fix: scripts/workbench.py writes them, with a configuration, a state
// directory and a HOME of their own, and says which environment points there.
// The `python3` of the machine may not have FastAPI: the checkout's `.venv` does.
const venv = join(root, '.venv', 'bin', 'python');
const python = existsSync(venv) ? venv : 'python3';
const STAGE = `
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import workbench
workbench.stage(Path(sys.argv[2]), token=sys.argv[3])
print(json.dumps({k: os.environ[k] for k in ("PATH", "HOME", "PONOS_CONFIG", "XDG_STATE_HOME", "PYTHONPATH")}))
`;

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

async function stage(theme) {
  const here = join(scratch, theme);
  const config = join(here, 'config.toml');
  const port = 8890 + Math.floor(Math.random() * 100);
  mkdirSync(here, { recursive: true });
  const env = {
    ...process.env,
    ...JSON.parse(execFileSync(python, ['-c', STAGE, join(root, 'scripts'), here, TOKEN], { encoding: 'utf-8' })),
  };
  // The workspace folder the health band looks for, and a state nobody else may read.
  mkdirSync(join(env.HOME, 'workspace'));
  execFileSync('chmod', ['-R', 'go-rwx', join(env.XDG_STATE_HOME, 'ponos')]);
  execFileSync(python, ['-c', SEED], { env });
  const server = spawn(python, ['-m', 'ponos', 'service', 'run', '--port', String(port)], {
    cwd: root,
    env,
    stdio: 'ignore',
  });
  children.push(server);
  const base = `http://127.0.0.1:${port}`;
  await until(() => fetch(`${base}/`).then((answer) => answer.status < 500), 'the console');

  const run = spawn(python, ['-c', RUN, base, TOKEN], { env, stdio: ['pipe', 'pipe', 'inherit'] });
  children.push(run);
  let answered = () => {};
  run.stdout.on('data', () => answered());
  const play = (line) =>
    new Promise((resolve) => {
      answered = resolve;
      run.stdin.write(`${line}\n`);
    });
  const close = () => {
    run.kill('SIGTERM');
    server.kill('SIGTERM');
  };
  return { base, play, close };
}

/* -- the browser and its protocol ------------------------------------------------- */

const chrome = spawn(
  process.env.CHROME || 'google-chrome',
  [
    '--headless=new',
    `--remote-debugging-port=${CHROME_PORT}`,
    `--user-data-dir=${join(scratch, 'chrome')}`,
    `--window-size=${WIDTH},${HEIGHT}`,
    '--hide-scrollbars',
    '--no-first-run',
    'about:blank',
  ],
  { stdio: 'ignore' },
);
children.push(chrome);
const target = await until(
  () =>
    fetch(`http://127.0.0.1:${CHROME_PORT}/json/list`)
      .then((answer) => answer.json())
      .then((list) => list.find((item) => item.type === 'page')),
  'headless Chrome',
);

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve) => socket.addEventListener('open', resolve, { once: true }));
let next = 0;
const pending = new Map();
const listeners = new Map();
socket.addEventListener('message', (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    pending.get(message.id)(message);
    pending.delete(message.id);
  } else if (message.method && listeners.has(message.method)) {
    listeners.get(message.method)(message.params);
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
await send('Network.enable');
await send('Emulation.setDeviceMetricsOverride', { width: WIDTH, height: HEIGHT, deviceScaleFactor: 1, mobile: false });
await send('Emulation.setLocaleOverride', { locale: 'en-US' });

/* -- in the page ---------------------------------------------------------------- */

// Where the pointer waits between two gestures.
const REST = { x: Math.round(WIDTH * 0.8), y: Math.round(HEIGHT * 0.9) };

// The pointer: drawn over the page, moved where the next click lands, and
// the click itself dispatched by the protocol as a real one.
const POINTER = `
  (() => {
    const pointer = document.createElement("div");
    pointer.id = "__pointer";
    pointer.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M5 3l14 8-6.5 1.5L10 19z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    pointer.style.cssText = "position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;filter:drop-shadow(0 1px 2px rgb(0 0 0 / .35));transition:transform .5s cubic-bezier(.4,0,.2,1);transform:translate(${REST.x}px,${REST.y}px)";
    document.body.appendChild(pointer);
  })()
`;

async function pointAt({ x, y }) {
  await evaluate(`document.getElementById("__pointer").style.transform = "translate(${x - 5}px, ${y - 3}px)"`);
  await sleep(520);
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
}

async function click(at) {
  await pointAt(at);
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', ...at, button: 'left', clickCount: 1 });
  await sleep(90);
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...at, button: 'left', clickCount: 1 });
}

// The centre of the element the expression finds, once it is there.
async function where(expression, what) {
  return until(
    () =>
      evaluate(`(() => {
        const element = ${expression};
        if (!element) return null;
        const box = element.getBoundingClientRect();
        return box.width ? { x: Math.round(box.x + box.width / 2), y: Math.round(box.y + box.height / 2) } : null;
      })()`),
    what,
  );
}

const named = (selector, name, scope = 'document') =>
  `[...${scope}.querySelectorAll(${JSON.stringify(selector)})].find((e) => e.innerText.trim() === ${JSON.stringify(name)})`;
const card = (title) =>
  `[...document.querySelectorAll('[draggable="true"]')].find((c) => c.innerText.includes(${JSON.stringify(title)}))`;
// Which column a card stands in, told by what it offers: set aside in Ready,
// validate in review, make ready once validated.
const offers = (title, name) => `!!${named('button', name, card(title))}`;

async function type(text) {
  for (const character of text) {
    await send('Input.insertText', { text: character });
    await sleep(25 + Math.random() * 30);
  }
}

/* -- the film ------------------------------------------------------------------- */

// The frames, as the screencast hands them over: only when the page changes,
// each with its time. ffmpeg is told how long each one stays.
let frames = [];
let recording = '';
listeners.set('Page.screencastFrame', ({ data, metadata, sessionId }) => {
  send('Page.screencastFrameAck', { sessionId });
  if (!recording) return;
  const file = join(recording, `${String(frames.length).padStart(5, '0')}.png`);
  writeFileSync(file, Buffer.from(data, 'base64'));
  frames.push({ file, at: metadata.timestamp });
});

async function film(theme) {
  const { base, play, close } = await stage(theme);
  await send('Network.setCookie', { name: 'ponos_token', value: TOKEN, url: base });
  const { identifier } = await send('Page.addScriptToEvaluateOnNewDocument', {
    source: `localStorage.setItem("ponos-theme", ${JSON.stringify(theme)}); localStorage.setItem("ponos-language", "en"); localStorage.setItem("ponos-dashboard-statistics", "folded");`,
  });
  await send('Page.navigate', { url: `${base}/` });
  await until(() => evaluate(`!!(${card('Fix rounding on VAT totals')})`), 'the board');
  // The board under the figures: the page is scrolled to it, as a person at work would.
  await evaluate(`${named('h1, h2, h3', 'Board')}.scrollIntoView({ block: 'start' })`);
  await evaluate(POINTER);
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', ...REST });
  await sleep(2000);

  recording = join(scratch, theme, 'frames');
  mkdirSync(recording);
  frames = [];
  await send('Page.startScreencast', { format: 'png', everyNthFrame: 1 });
  await sleep(300);
  // On the screencast's clock — seconds since the epoch, as each frame's
  // timestamp — so that a cue is a time in the film.
  const cues = [];
  const cue = () => cues.push(Date.now() / 1000);

  // 01 — you write the ticket.
  cue();
  await sleep(400);
  await click(await where(named('a', 'New ticket'), 'New ticket'));
  await sleep(400);
  await click(await where(`document.querySelector('[role="dialog"] [role="combobox"]')`, 'the project field'));
  await click(await where(`[...document.querySelectorAll('[role="option"]')].find((o) => o.innerText.includes("Landing page"))`, 'the project'));
  await click(await where(`document.querySelector('[role="dialog"] input')`, 'the title'));
  await type(TITLE);
  await sleep(250);
  // Ctrl+Enter, which creates the ticket from wherever the dialog is.
  const enter = { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, modifiers: 2 };
  await send('Input.dispatchKeyEvent', { type: 'rawKeyDown', ...enter });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', ...enter });
  // Drawn at the foot of Ready first, then in its place once the board is
  // read again: in sight, before Ponos takes it.
  await until(() => evaluate(`${card(TITLE)}?.getBoundingClientRect().bottom < innerHeight`), 'the new card');
  await pointAt(REST);
  await sleep(300);

  // 02 — Ponos does it.
  cue();
  await play(`claim ${TITLE}`);
  await until(() => evaluate(`!${offers(TITLE, 'set aside')}`), 'In progress');
  for (const [name, given] of [
    ['Read', { file_path: 'src/pages/pricing.tsx' }],
    ['Edit', { file_path: 'src/pages/pricing.tsx' }],
    ['Write', { file_path: 'src/components/faq.tsx' }],
    ['Bash', { command: 'npm test' }],
  ]) {
    await sleep(800);
    await play(`use ${JSON.stringify([name, given])}`);
  }
  await sleep(1000);

  // 03 — you read what came back: In review, with what it cost.
  cue();
  await play('deliver 0.84');
  await until(() => evaluate(offers(TITLE, 'Decide')), 'In review');
  await sleep(1800);

  // 04 — you say yes, and he delivers: Validated.
  cue();
  await click(await where(named('button', 'Decide', card(TITLE)), 'Decide'));
  await sleep(1500);
  await click(await where(`[...document.querySelectorAll('[data-solution]')].find((e) => e.innerText.includes("Validate"))`, 'Validate'));
  await until(() => evaluate(offers(TITLE, 'Make ready')), 'Validated');
  // The decision said, the window closed: the card stands in Validated.
  await sleep(1600);
  await click(await where(`document.querySelector('[data-ticket-window] button[aria-label="Close"], [role="dialog"] button[aria-label="Close"]')`, 'the close button'));
  await pointAt(REST);
  await sleep(1200);

  const end = Date.now() / 1000;
  await send('Page.stopScreencast');
  recording = '';
  await send('Page.removeScriptToEvaluateOnNewDocument', { identifier });
  close();
  const first = frames[0].at;
  // The film opens on the first gesture, whatever the frames before it.
  return { frames: [...frames], cues: cues.map((at, i) => (i ? at - first : 0)), length: end - first };
}

/* -- the videos ------------------------------------------------------------------- */

const FADE = 0.6;

function encode(theme, shot) {
  const here = join(scratch, theme);
  const first = shot.frames[0].at;
  const length = shot.length;
  // Each frame until the next one, the last until the camera stopped.
  const list = shot.frames
    .map((frame, i) => {
      const until = i + 1 < shot.frames.length ? shot.frames[i + 1].at : first + length;
      return `file '${frame.file}'\nduration ${(until - frame.at).toFixed(4)}`;
    })
    .join('\n');
  writeFileSync(join(here, 'frames.txt'), `ffconcat version 1.0\n${list}\nfile '${shot.frames.at(-1).file}'\n`);
  const video = join(out, `console-loop-${theme}.mp4`);
  // The last picture fades into the first, so that the loop has no seam.
  execFileSync('ffmpeg', [
    '-y', '-loglevel', 'error',
    '-f', 'concat', '-safe', '0', '-i', join(here, 'frames.txt'),
    '-loop', '1', '-t', String(FADE + 0.1), '-i', shot.frames[0].file,
    '-filter_complex',
    `[0:v]fps=30,format=yuv420p,setpts=PTS-STARTPTS[a];[1:v]fps=30,format=yuv420p[b];[a][b]xfade=transition=fade:duration=${FADE}:offset=${(length - FADE).toFixed(3)},format=yuv420p[v]`,
    '-map', '[v]', '-an',
    '-c:v', 'libx264', '-preset', 'veryslow', '-crf', '26', '-tune', 'animation', '-pix_fmt', 'yuv420p',
    '-movflags', '+faststart',
    video,
  ]);
  return video;
}

function poster(theme, shot, at) {
  const first = shot.frames[0].at;
  const frame = [...shot.frames].reverse().find((f) => f.at - first <= at) ?? shot.frames[0];
  const file = join(out, `console-loop-${theme}-poster.webp`);
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', frame.file, '-c:v', 'libwebp', '-quality', '82', file]);
  return file;
}

const size = (file) => `${(statSync(file).size / 1024).toFixed(0)} kB`;
const said = {};
for (const theme of themes) {
  const shot = await film(theme).catch(async (error) => {
    // What the page looked like when the film stopped, to see why.
    const { data } = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(join(scratch, 'failed.png'), Buffer.from(data, 'base64'));
    console.error(`${error.message} — the page as it was: ${join(scratch, 'failed.png')}${keep ? '' : ' (with --keep)'}`);
    process.exit(1);
  });
  if (look) {
    const sheet = join(scratch, theme, 'sheet.png');
    const picked = Array.from({ length: 16 }, (_, i) => shot.frames[Math.round((i * (shot.frames.length - 1)) / 15)].file);
    writeFileSync(join(scratch, theme, 'sheet.txt'), picked.map((file) => `file '${file}'`).join('\n'));
    execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', join(scratch, theme, 'sheet.txt'), '-vf', 'scale=480:-1,tile=4x4', '-frames:v', '1', sheet]);
    console.log(`${theme}: ${sheet}, ${shot.frames.length} frames in ${join(scratch, theme, 'frames')}, cues ${shot.cues.map((c) => c.toFixed(1)).join(' ')}`);
    continue;
  }
  const video = encode(theme, shot);
  // The poster is Ponos at work: the picture a visitor who asked for no motion sees.
  const still = poster(theme, shot, shot.cues[2] - 0.4);
  said[theme] = shot.cues;
  console.log(`${theme}: ${video} (${size(video)}), ${still} (${size(still)}), gestures at ${shot.cues.map((c) => c.toFixed(1)).join(' ')} s`);
}
// The page lights each gesture when the film reaches it: the times go into
// it, film by film — the board is read again a second or so after each move,
// and no two films wait the same.
if (!look) {
  for (const name of ['index.html', 'fr/index.html']) {
    const page = join(root, 'docs', name);
    let text = readFileSync(page, 'utf-8');
    for (const theme of themes) {
      const cues = said[theme].map((at) => at.toFixed(1)).join(' ');
      const attribute = new RegExp(`data-cues-${theme}="[^"]*"`);
      if (!attribute.test(text)) throw new Error(`docs/${name} has no data-cues-${theme} to write`);
      text = text.replace(attribute, `data-cues-${theme}="${cues}"`);
    }
    writeFileSync(page, text);
    console.log(`docs/${name}: the cues written`);
  }
}
if (keep) console.log(`\nKept: ${scratch}`);

socket.close();
process.exit(0);
