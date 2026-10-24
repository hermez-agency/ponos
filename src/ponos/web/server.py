"""The console's door: who may come in, and the pages they are shown first.

**What is on the other side of this port matters more than the port.** The
runner starts Claude Code sessions with `bypassPermissions`; so does the chat.
Anything that can talk to this server can run code on this machine as you. That
is why:

- the default bind is `127.0.0.1`, and a non-loopback host without a configured
  token — or a configured sign-in — is refused rather than served;
- every request carries a token — as a header, as the cookie the first `?token=`
  sets, or as the cookie signing in with an email and a password sets;
- until somebody has said how this console is opened, there is nothing to carry:
  a console nobody claimed serves the first connection instead (see `setup`),
  and the password typed there is what closes that door — to this machine
  alone, or to whoever has the installation code `serve` printed when it
  started: a console behind a domain is a console the whole Internet reaches
  first;
- behind a proxy that says the browser came in over HTTPS (`X-Forwarded-Proto`),
  every cookie is `Secure`, so it never travels in clear on the way back, and
  the answer says HSTS, so the browser never tries it in clear again;
- a password, a token or an installation code typed wrong is counted per
  address, and the address waits longer after each (`attempts`); a sign-in lasts
  thirty days from its last use (`sessions`), and the password is kept as a
  digest (`passwords`);
- a page is served under a Content-Security-Policy that runs no script but the
  bundle's files and the few lines written into the page itself, hashed;
- a request from a browser page that is not the console is rejected: writes
  demand a header a cross-origin form cannot set, and the `Host` header must
  name the address the console was reached on, which is what stops a hostile
  page from resolving its own domain to 127.0.0.1 and talking to you through it.

The application that does all this — FastAPI, served by uvicorn — is `app.py`.
This module holds what it is checked against, and stays the standard library's
alone, for a reason older than the application: an installation still on
v0.1.0 checks that a new version starts by importing this very module, with the
machine's Python, before it moves to it (`update.verify`). Were FastAPI imported
here, that check would fail on every such machine, and the update that brings
the environment holding FastAPI would never be installed. `serve` imports the
application when it is asked to serve, and says what is missing when it is not
there.
"""

from __future__ import annotations

import base64
import errno
import hashlib
import hmac
import html
import json
import logging
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

from .. import config as config_module
from .. import github_app, legacy, passwords, voice
from ..config import Config, state_dir
from . import oauth, sessions

logger = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"
COOKIE = "ponos_token"


def cookie_name(port: int) -> str:
    """The cookie of the console on `port`: a browser keys cookies by host, not port.

    Two consoles at one address — the demo and the real one, an e2e run, two
    installations — would otherwise take turns in one cookie, and opening the
    one signed out of the other. `COOKIE`, the name of before, is still read.
    """
    return f"{COOKIE}_{port}"


# Migration filet: the cookie a browser was given before the rename, still good
# for the year it was given for — a rename is not a reason to sign in again.
LEGACY_COOKIE = legacy.OLD.replace("-", "_") + "_token"

# The build names every file under `assets/` after a hash of what it holds, so
# a file there never changes under its name: a browser keeps it for a year and
# asks again only when `index.html` — never cached — points somewhere new.
IMMUTABLE = "public, max-age=31536000, immutable"

# The bundle is text, a megabyte and more of it, sent on every first load and
# over a tunnel as often as over loopback. Compressed once per file, on the first
# request that accepts it, and kept: the files only change when the code does,
# and the code changing is a restart.
COMPRESSIBLE = ("text/", "application/javascript", "application/json", "image/svg+xml")
_compressed: dict[tuple[Path, int, str], bytes] = {}

# A header no cross-origin form, image or script tag can set. Its presence is
# what tells "the console asked this" from "some page you had open asked this".
GUARD_HEADER = "X-Ponos"

LOOPBACK = ("127.0.0.1", "::1", "localhost", "[::1]")

# What every answer that is not a page is served under: a JSON file opened on
# its own runs nothing, loads nothing and is framed by nobody.
LOCKED_POLICY = "default-src 'none'; frame-ancestors 'none'"
# The service worker's own: its CSP is the one it runs under, and it fetches.
WORKER_POLICY = "default-src 'self'"
# The browser's powers a page here never needs — but the microphone, which
# dictation asks for, from this origin only.
PERMISSIONS = "camera=(), geolocation=(), microphone=(self), payment=(), usb=()"
# A year, once the proxy says HTTPS: see `_secure`.
HSTS = "max-age=31536000"
# How long the token's cookie is kept. A sign-in's is `sessions.LIFETIME`.
TOKEN_COOKIE_AGE = 31536000

_INLINE_SCRIPT = re.compile(
    rb"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL
)
_INLINE_STYLE = re.compile(rb"<style[^>]*>(.*?)</style\s*>", re.IGNORECASE | re.DOTALL)


def _hashes(pattern: re.Pattern[bytes], page: bytes) -> str:
    found = (
        base64.b64encode(hashlib.sha256(text).digest()).decode() for text in pattern.findall(page)
    )
    return "".join(f" 'sha256-{digest}'" for digest in dict.fromkeys(found))


def page_policy(page: bytes, *, bundle: bool = False, leaves: bool = False) -> str:
    """The Content-Security-Policy of one HTML page, from what that page holds.

    Scripts: the files of `/static/`, and the lines a page carries inline —
    the theme read before the first paint, the sign-in's fetch — by the hash
    of exactly those lines, so a script anybody manages to write into a page
    is one the browser refuses to run. Hashed when the page is served rather
    than written down here, because the build rewrites `index.html`.

    Styles: the same for the pages written in Python. The bundle (`bundle`) is
    the exception: what it carries — the toasts, the scroll lock of a dialog,
    the editor — writes `<style>` elements at runtime, with contents of their
    own making, so inline styles are allowed there. A style runs no code.

    `leaves` is the consent page, whose form is answered by a redirect to the
    client that asked: `form-action` would stop it on the way out. The bundle's
    forms go to this console, and to GitHub — the manifest a GitHub App is
    created from is a form posted there (`github-page.tsx`).
    """
    styles = "'self' 'unsafe-inline'" if bundle else "'self'" + _hashes(_INLINE_STYLE, page)
    policy = [
        "default-src 'self'",
        "script-src 'self'" + _hashes(_INLINE_SCRIPT, page),
        f"style-src {styles}",
        # A ticket's Markdown shows pictures from wherever they are hosted.
        "img-src 'self' data: blob: https:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "media-src 'self' blob:",
        "worker-src 'self'",
        "manifest-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
    ]
    if not leaves:
        site = urlparse(github_app.web())
        policy.append(
            f"form-action 'self' {site.scheme}://{site.netloc}" if bundle else "form-action 'self'"
        )
    return "; ".join(policy)


def accepts_gzip(header: str) -> bool:
    """`Accept-Encoding` names gzip, and not with `q=0` — which means "never"."""
    for part in header.split(","):
        coding, _, params = part.strip().partition(";")
        if coding.strip().lower() != "gzip":
            continue
        quality = params.strip().lower().replace(" ", "")
        return not (quality.startswith("q=") and quality[2:].strip("0.") == "")
    return False


def token_path() -> Path:
    path = state_dir() / "web"
    path.mkdir(parents=True, exist_ok=True)
    return path / "token"


def token(config: Config) -> str:
    """The console's token: the configured one, or one drawn once and kept.

    Kept on disk rather than drawn per start, because a token that changed on
    every restart would make the bookmark useless — and a console you reach by
    pasting a fresh secret every morning is a console you stop opening.
    """
    if config.web.token:
        return config.web.token
    path = token_path()
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    fresh = secrets.token_urlsafe(24)
    from ..disk import write_private  # 0600 from its first byte, not after a chmod

    write_private(path, fresh + "\n")
    return fresh


def landing(query: str) -> str:
    """Where a `?token=…` address goes once the token is in a cookie.

    Everything the address carried except the token, because the rest of it is
    not a secret, it is a destination: `serve` prints `/?token=…` and a deep
    link is shared as `/?token=…&view=console/projects/list`. Redirecting both
    to a bare `/` put the second one on the board.
    """
    rest = urlencode([pair for pair in parse_qsl(query) if pair[0] != "token"])
    return f"/?{rest}" if rest else "/"


@dataclass(frozen=True)
class SignIn:
    """An email, a password's digest, and what a browser that typed them is given.

    `proof` is *derived* from the email and what `secrets.env` keeps for the
    password rather than drawn at random: a console that restarts — and its unit
    restarts with the machine — does not sign you out, while changing the
    password signs out every browser that ever held a session. It is an HMAC
    under the console's own token, so nothing derived from it says anything
    about the password. A session is that proof, dated and signed again — see
    `sessions`.
    """

    email: str
    digest: str
    proof: str

    def session(self) -> str:
        """A new session, as the cookie carries it."""
        return sessions.issue(self.proof)

    def holds(self, cookie: str) -> int | None:
        """When that cookie's session was given, if it is one of this sign-in's and alive."""
        return sessions.issued(self.proof, cookie)

    def opens(self, email: str, password: str) -> bool:
        """The email and the password, as somebody typed them.

        Both compared before the answer is given: an early return here would
        answer "that email does not exist" by taking less time to say so.
        """
        known_email = hmac.compare_digest(
            email.strip().lower().encode(), self.email.lower().encode()
        )
        known_password = passwords.matches(password, self.digest)
        return known_email and known_password


def sign_in(config: Config, secret: str) -> SignIn | None:
    """How this console is opened, when it is not opened with its token.

    None unless both halves are set: an email without a password is somebody
    half-way through configuring one, and it must not be a way in.
    """
    email = config.web.email.strip()
    password = config.web.password
    if not email or not password:
        return None
    proof = hmac.new(
        secret.encode(), f"{email.lower()}\n{password}".encode(), hashlib.sha256
    ).hexdigest()
    # A password still in clear is the environment's — the file's is a digest
    # since the launch that read it (`config.hash_password`). Digested here,
    # in memory, so that nothing past this line holds it as it was typed.
    digest = password if passwords.is_digest(password) else passwords.digest(password)
    return SignIn(email=email, digest=digest, proof=proof)


# The installation code's letters: no 0 and O, no 1 and I, nothing a log line
# read off a phone gets wrong.
CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# The headers a proxy adds. A request carrying one came through something — a
# Traefik, an nginx on the same machine — and is not "somebody at this machine",
# whatever address it arrived from.
FORWARDED = ("Forwarded", "X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host", "X-Real-IP")


def installation_code() -> str:
    """Eight letters, drawn once per start of a console nobody has claimed."""
    letters = "".join(secrets.choice(CODE_LETTERS) for _ in range(8))
    return f"{letters[:4]}-{letters[4:]}"


def same_code(offered: str, expected: str) -> bool:
    """The code as somebody types it: any case, with or without its dash."""

    def bare(code: str) -> bytes:
        return re.sub(r"[^0-9A-Za-z]", "", code).upper().encode()

    return bool(expected) and hmac.compare_digest(bare(offered), bare(expected))


def claimable(config: Config, entry: SignIn | None) -> bool:
    """Has anybody decided how this console is opened? — see `setup`.

    Two ways of deciding it, and neither has been taken: a sign-in, which is
    `None` until an email *and* a password are set, in the file or in the
    environment; or a token written in the configuration on purpose. The token
    drawn on first start is not a decision — it is what the console does when
    nobody has said anything, and it is the state the first connection is for.
    """
    return entry is None and not config.web.token


# -- the pages a browser sees before it is in ---------------------------

# The palette, the card, the field and the button are the console's own — Hermez's
# stone and orange, the values of `frontend/src/tokens.css` and the shapes of its
# shadcn `Card`, `Input` and `Button` — copied rather than linked, because the
# bundle is behind this door. Dark unless this browser chose light in the console:
# the same line of `localStorage` its `index.html` reads before the first paint,
# so the door and the room behind it are the same colour.
_STYLE = """<style>
 :root{--background:#fafaf9;--foreground:#1c1917;--card:#fff;--field:#f5f5f4;--border:#e7e5e4;
       --muted-foreground:#57534e;--primary:#bf4a02;--primary-foreground:#fff;--ring:#e46212;
       --destructive:#cc2020;--shadow:0 1px 2px 0 rgb(28 25 23/.064);color-scheme:light}
 .dark{--background:#0c0a09;--foreground:#fafaf9;--card:#1c1917;--field:#221f1d;--border:#fafaf91c;
       --muted-foreground:#a8a29e;--primary:#ff8b44;--primary-foreground:#1c1917;--ring:#e46212;
       --destructive:#f87171;--shadow:0 1px 2px 0 rgb(0 0 0/.32);color-scheme:dark}
 body{background:var(--background);color:var(--foreground);margin:0;display:grid;place-items:center;min-height:100vh;
      font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
      -webkit-font-smoothing:antialiased}
 form{box-sizing:border-box;width:min(26rem,92vw);background:var(--card);border:1px solid var(--border);
      border-radius:1.05rem;padding:1.5rem;box-shadow:var(--shadow)}
 h1{font:800 1.25rem/1.2 "Bricolage Grotesque Variable","Bricolage Grotesque",ui-sans-serif,system-ui,sans-serif;
    letter-spacing:-.025em;margin:0 0 .375rem}
 p{color:var(--muted-foreground);margin:0 0 1.25rem;font-size:.875rem}
 label{display:block;font-size:.875rem;font-weight:500;margin:1rem 0 .375rem}
 input{width:100%;box-sizing:border-box;height:2.25rem;background:var(--field);border:1px solid var(--border);
       color:inherit;border-radius:.6rem;padding:.25rem .75rem;font:inherit;outline:none}
 input:focus-visible{background:var(--background);border-color:var(--ring);box-shadow:0 0 0 3px rgb(228 98 18/.5)}
 button:focus-visible,a:focus-visible{outline:none;box-shadow:0 0 0 3px rgb(228 98 18/.5)}
 button{margin-top:1.25rem;width:100%;height:2.25rem;background:var(--primary);color:var(--primary-foreground);
        border:0;border-radius:.6rem;padding:0 1rem;font:inherit;font-weight:500;cursor:pointer}
 button:hover{opacity:.9}
 code{background:var(--field);padding:.1rem .35rem;border-radius:.45rem;color:var(--foreground);
      font:.8125rem ui-monospace,Menlo,Consolas,monospace;overflow-wrap:anywhere}
 .said{color:var(--destructive);margin:.9rem 0 0;min-height:1.2em}
</style>
"""

# Before the first paint, as the console's `index.html` does it: dark, unless the
# console was switched to light in this browser.
_THEME = (
    "<script>try{document.documentElement.classList.toggle('dark',"
    "localStorage.getItem('ponos-theme')!=='light')}catch(e){}</script>\n"
)

# What these pages say, in the two languages the console speaks. The key is
# the English, as it is in `frontend/src/lib/french.ts`: a sentence nobody
# translated is drawn as it was written rather than as a name.
_FRENCH = {
    "token": "jeton",
    "sign in": "connexion",
    "Token": "Jeton",
    "Email": "E-mail",
    "Password": "Mot de passe",
    "Open the console": "Ouvrir la console",
    "Sign in to open the console.": "Connectez-vous pour ouvrir la console.",
    "wrong email or password": "e-mail ou mot de passe incorrect",
    "This console needs its token. <code>ponos serve --print-token</code> prints it, "
    "and it is kept in {where}.": "Cette console demande son jeton. <code>ponos serve --print-token</code> "
    "l'affiche, et il est gardé dans {where}.",
    "<code>PONOS_WEB_TOKEN</code> of <code>{path}</code>": "le <code>PONOS_WEB_TOKEN</code> de <code>{path}</code>",
    "the <code>PONOS_WEB_TOKEN</code> environment variable": "la variable d'environnement <code>PONOS_WEB_TOKEN</code>",
    "The token this browser kept is not this console's: another console at this "
    "address may have replaced it.": "Le jeton gardé par ce navigateur n'est pas celui de cette console : une autre "
    "console à la même adresse l'a peut-être remplacé.",
    "connect": "connecter",
    "<strong>{client}</strong> asks to reach this Ponos.": "<strong>{client}</strong> demande l'accès à ce Ponos.",
    "Read the tasks, the projects, the ideas and what the runner is doing": "Lire les tâches, les projets, les idées et ce que fait le runner",
    "Write: create tasks, answer the blocked ones, sort the ideas": "Écrire : créer des tâches, répondre aux tâches bloquées, trier les idées",
    "No tool runs a command, starts a session on the spot, changes the settings or deletes anything.": "Aucun outil ne lance de commande, ne démarre de session sur-le-champ, ne modifie les "
    "réglages ni ne supprime quoi que ce soit.",
    "Allow": "Autoriser",
    "Refuse": "Refuser",
    "wrong token": "jeton incorrect",
    "too many attempts — try again in {seconds} s": "trop de tentatives — réessayez dans {seconds} s",
    "This console has not been set up yet.": "Cette console n'est pas encore configurée.",
}


def language_of(header: str) -> str:
    """The language a browser reads, from its `Accept-Language`.

    The console decides the same way — the browser's own list, in its order —
    and these pages have to agree with it: a sign-in in English opening onto a
    board in French reads as two products. The first tag that is one of the two
    spoken here wins; `voice.understood` reads it, as it reads the file's.
    """
    for part in (header or "").split(","):
        tag = part.split(";")[0].strip()
        if tag.split("-")[0].lower() in voice.LANGUAGES:
            return voice.understood(tag)
    return voice.DEFAULT


def configured(page: bytes, language: str) -> bytes:
    """The console's page, carrying the language the configuration opens it in.

    Written into the page rather than asked for over the API, because the
    console picks its language before it draws anything — a first paint in
    English, redrawn in French a request later, is the flash this avoids. An
    attribute on `<html>`, read by `frontend/src/lib/i18n.ts`, and only as a
    default: a language somebody picked in the select stays theirs.
    """
    if not language:
        return page
    return re.sub(rb"<html\b", f'<html data-language="{language}"'.encode(), page, count=1)


def _words(language: str):
    table = _FRENCH if language == "fr" else {}
    return lambda text: table.get(text, text)


def _page(title: str, body: str, style: str = "", language: str = "en") -> str:
    """The way in, drawn by this server rather than by the bundle.

    A browser that has not got in cannot load the console, so these two pages
    are the only HTML written in Python — the first connection is the
    exception, drawn by the bundle, which is served to a console nobody has
    claimed — and, like everything else served
    here, they reach for nothing that is not on this machine.
    """
    return (
        f'<!doctype html>\n<html lang="{language}" class="dark">\n<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{html.escape(title)} · Ponos</title>\n" + _THEME + _STYLE + style + body
    )


def gate_page(language: str = "en", where: str = "", said: str = "") -> str:
    """Asked for the token — and told where to find it, as this machine has it.

    `where` is the real place: the `PONOS_WEB_TOKEN` line of the `secrets.env`
    in use, or the environment, when the token was chosen; else the file it was
    drawn into — under `$XDG_STATE_HOME` when that is set, which a path printed
    as a constant got wrong on every machine that sets it. `said` is why a token
    that was offered did not open the door, already in the page's language.
    """
    say = _words(language)
    where = where or f"<code>{html.escape(str(state_dir() / 'web' / 'token'))}</code>"
    return _page(
        say("token"),
        f"""<form id="door">
  <h1>Ponos</h1>
  <p>{
            say(
                "This console needs its token. <code>ponos serve --print-token</code> prints it, "
                "and it is kept in {where}."
            ).format(where=where)
        }</p>
  <label for="t">{say("Token")}</label>
  <input id="t" name="t" autofocus autocomplete="off" spellcheck="false">
  <button type="submit">{say("Open the console")}</button>
  <p class="said" role="alert">{html.escape(said, quote=False)}</p>
</form>
<script>
document.getElementById('door').addEventListener('submit', function (event) {{
  event.preventDefault();
  location = '/?token=' + encodeURIComponent(this.t.value.trim());
}});
</script>
""",
        language=language,
    )


def sign_in_page(language: str = "en") -> str:
    """The same door, with a lock somebody can remember.

    It posts rather than navigates — a form that navigated could not set the
    header that tells a request from the console apart from a request from a
    page you had open.
    """
    say = _words(language)
    return _page(
        say("sign in"),
        f"""<form id="door">
  <h1>Ponos</h1>
  <p>{say("Sign in to open the console.")}</p>
  <label for="email">{say("Email")}</label>
  <input id="email" name="email" type="email" autofocus autocomplete="username" spellcheck="false">
  <label for="password">{say("Password")}</label>
  <input id="password" name="password" type="password" autocomplete="current-password">
  <button type="submit">{say("Open the console")}</button>
  <p class="said" id="said" role="alert"></p>
</form>
<script>
const WRONG = {json.dumps(say("wrong email or password"), ensure_ascii=False)};
const TOO_MANY = {json.dumps(say("too many attempts — try again in {seconds} s"), ensure_ascii=False)};
async function enter(form){{
  const said = document.getElementById('said');
  said.textContent = '';
  try {{
    const answer = await fetch('/api/login', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json', '{GUARD_HEADER}': '1'}},
      body: JSON.stringify({{email: form.email.value, password: form.password.value}}),
    }});
    if (answer.ok) {{ location = '/'; return; }}
    const body = await answer.json().catch(() => ({{}}));
    said.textContent = answer.status === 401 ? WRONG
      : answer.status === 429 ? TOO_MANY.replace('{{seconds}}', answer.headers.get('Retry-After') || '1')
      : (body.error || WRONG);
  }} catch (error) {{
    said.textContent = String(error);
  }}
}}
document.getElementById('door').addEventListener('submit', function (event) {{
  event.preventDefault();
  enter(this);
}});
</script>
""",
        language=language,
    )


def consent_page(language: str, request, params: dict[str, str], needs: str, said: str = "") -> str:
    """Which client asks for what, and the door to sign in by when the browser is out.

    The request travels in hidden fields rather than in a server-side session:
    it is checked again in full when the form comes back, so what a browser
    changes in it is only ever another request, checked like the first.
    `needs` is `password`, `token`, or empty for a browser already in.
    """
    say = _words(language)
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(name)}" value="{html.escape(params.get(name, ""))}">'
        for name in (
            "response_type",
            "client_id",
            "redirect_uri",
            "code_challenge",
            "code_challenge_method",
            "scope",
            "state",
            "resource",
        )
        if params.get(name)
    )
    write = (
        f'<label class="scope"><input type="checkbox" name="write" value="1" checked> '
        f"{say('Write: create tasks, answer the blocked ones, sort the ideas')}</label>"
        if oauth.WRITE in request.scopes
        else ""
    )
    if needs == "password":
        door = (
            f'<label for="email">{say("Email")}</label>'
            '<input id="email" name="email" type="email" autocomplete="username" spellcheck="false" required>'
            f'<label for="password">{say("Password")}</label>'
            '<input id="password" name="password" type="password" autocomplete="current-password" required>'
        )
    elif needs == "token":
        door = (
            f'<label for="token">{say("Token")}</label>'
            '<input id="token" name="token" autocomplete="off" spellcheck="false" required>'
        )
    else:
        door = ""
    client = html.escape(request.client.name)
    return _page(
        say("connect"),
        f"""<form method="post" action="/oauth/authorize">
  <h1>Ponos</h1>
  <p>{say("<strong>{client}</strong> asks to reach this Ponos.").format(client=client)}</p>
  {hidden}
  <label class="scope"><input type="checkbox" checked disabled> {say("Read the tasks, the projects, the ideas and what the runner is doing")}</label>
  {write}
  <p>{say("No tool runs a command, starts a session on the spot, changes the settings or deletes anything.")}</p>
  {door}
  <p class="said" role="alert">{html.escape(said)}</p>
  <button type="submit" name="decision" value="allow">{say("Allow")}</button>
  <button type="submit" name="decision" value="deny" class="quiet" formnovalidate>{say("Refuse")}</button>
</form>
""",
        # Every page here is served `no-referrer`, and a form posted under that
        # policy says `Origin: null` — which `_consent` would refuse as a page
        # from elsewhere. This one says where it is from, to itself alone.
        style='<meta name="referrer" content="same-origin">\n'
        "<style>.scope{display:flex;gap:.5rem;align-items:baseline;font-weight:400}"
        ".scope input{width:auto;height:auto}.quiet{background:transparent;color:var(--muted-foreground);margin-top:.4rem}</style>\n",
        language=language,
    )


def consent_refused(language: str, why: str) -> str:
    """A request the consent page cannot even show: said, and sent nowhere."""
    say = _words(language)
    return _page(
        say("connect"),
        f'<form><h1>Ponos</h1><p class="said">{html.escape(say(why))}</p></form>\n',
        language=language,
    )


# The English pages, as they stand: what a test reads, and what a browser that
# says nothing about its language is given.
GATE = gate_page()
SIGN_IN = sign_in_page()


def serve(
    config: Config,
    *,
    host: str = "",
    port: int = 0,
    announce: bool = True,
) -> int:
    """Run the console until interrupted. Returns a process exit code."""
    host = host or config.web.host
    port = port or config.web.port
    secret = token(config)
    entry = sign_in(config, secret)

    # In a container the console listens to a network by nature — Docker's, and
    # behind it Traefik's — and what guards a console nobody has claimed there is
    # the installation code drawn below. Everywhere else, as it always was.
    if (
        host not in LOOPBACK
        and not config.web.token
        and entry is None
        and not config_module.in_container()
    ):
        print(
            f"refusing to listen on {host}: behind this port sits a runner that starts\n"
            "Claude Code sessions with bypassPermissions, and a generated token is not a\n"
            "decision you took. Either keep the default 127.0.0.1 and reach it over ssh\n"
            "  ssh -L 8787:127.0.0.1:8787 <this machine>\n"
            "or say so on purpose: web.token, or web.email and web.password."
        )
        return 2

    # What to print as the way in. A console with a sign-in is opened by typing
    # an address, which is the whole point of having one — putting the token
    # back in that line would be telling you to paste a secret anyway. And one
    # nobody has claimed is opened by the address alone: the first connection is
    # what it serves, and asking for a token to reach it would be the circle
    # that page exists to break.
    def opening(address: str) -> str:
        if entry:
            return f"{address}  —  sign in as {entry.email}"
        if claimable(config, entry):
            return f"{address}  —  not set up yet: the first browser to open it sets its password"
        return f"{address}/?token={secret}"

    # Drawn once per start, and only while nobody has claimed the console: it is
    # what a first connection from anywhere but this machine has to give.
    code = installation_code() if claimable(config, entry) else ""

    # The application, and FastAPI with it — see the module's docstring.
    try:
        from .api import Api
        from .app import Console
    except ImportError as error:
        print(
            f"the console needs {error.name or error}, which {sys.executable} does not "
            "have: the environment of this version (.venv) is missing it — the next "
            "pass of the runner makes it again (ponos run), and a checkout makes it "
            "with uv sync",
            file=sys.stderr,
        )
        return 1

    api = Api(config)
    try:
        console = Console((host, port), api, secret, entry, code)
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            # The console's unit starts with the machine, so a taken port is the
            # ordinary answer to `serve` rather than a failure: somebody typing
            # it wants the console, and the one already listening is it.
            print(f"already listening on http://{host}:{port} — the console is running")
            print(f"  open  {opening(f'http://{host}:{port}')}")
            print("  stop  systemctl --user stop ponos-web")
            return 0
        print(f"cannot listen on {host}:{port} — {error}")
        return 1

    address = console.server_address
    shown = f"http://{address[0]}:{address[1]}"
    if announce:
        print(f"Ponos console on {shown}")
        print(f"  open  {opening(shown)}")
        if code:
            print(
                f"  code  {code}  —  asked by the first connection from anywhere but this machine"
            )
        print("  stop  Ctrl-C\n", flush=True)

    api.upgrade.watch()
    api.planned.watch()
    try:
        # In this thread: uvicorn answers Ctrl-C and systemd's SIGTERM itself,
        # lets the requests in flight finish, and gives the signal back.
        console.serve_forever()
    except KeyboardInterrupt:
        if announce:
            print("\nstopping")
    finally:
        api.watch.stop()
        console.server_close()
    return 0
