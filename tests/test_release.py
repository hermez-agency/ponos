"""`scripts/release.py`, the build that is committed, and the pages that are published."""

from __future__ import annotations

import contextlib
import gzip
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import release
from support import FRONTEND, ROOT, _bare_api, _head, _plain, _TalkClient, case

from ponos import __version__, update
from ponos import config as C
from ponos.__main__ import banner, build_parser, subcommands, welcome
from ponos.__main__ import main as cli_main
from ponos.web import api as web_api
from ponos.web import settings as web_settings

# -- releases ----------------------------------------------------------------


@case
def the_version_and_the_changelog_never_drift():
    """The one invariant the whole release system rests on.

    `__version__` and the newest released section of CHANGELOG.md are written by
    the same command, in the same breath. If they are ever seen apart, something
    edited one of them by hand — and the release that follows would ship a
    number whose notes describe a different one.
    """
    version = release.read_version()
    release.parse(version)  # raises if it is not a version at all

    entries = release.released(release.CHANGELOG.read_text(encoding="utf-8"))
    for name, dated, body in entries:
        release.parse(name)
        assert dated, f"[{name}] has no date"
        assert body.strip(), f"[{name}] has no notes"

    order = [release.order(name) for name, _date, _body in entries]
    assert order == sorted(order, reverse=True), "the changelog runs newest first"

    if entries:
        assert entries[0][0] == version, (
            f"__version__ is {version}, the newest changelog section is [{entries[0][0]}]"
        )


@case
def the_dokploy_template_pins_the_image_of_this_version():
    """Never `latest`: the image the tag of this tree publishes, and `bump` moves it."""
    version = release.read_version()
    assert release.read_pins() == {"docker-compose.yml": version, "meta.json": version}

    copy = Path(tempfile.mkdtemp())
    for name in release.PINS:
        shutil.copy(release.BLUEPRINT / name, copy / name)
    release.write_pins("9.8.7", copy)
    assert release.read_pins(copy) == {"docker-compose.yml": "9.8.7", "meta.json": "9.8.7"}
    assert json.loads((copy / "meta.json").read_text(encoding="utf-8"))["version"] == "9.8.7"


@case
def the_dokploy_template_keeps_to_the_catalogues_rules():
    """What Dokploy/templates refuses, and the variables both files must agree on."""
    import tomllib

    compose = (release.BLUEPRINT / "docker-compose.yml").read_text(encoding="utf-8")
    template = tomllib.loads((release.BLUEPRINT / "template.toml").read_text(encoding="utf-8"))
    meta = json.loads((release.BLUEPRINT / "meta.json").read_text(encoding="utf-8"))

    for refused in ("ports:", "container_name", "networks:", ":latest"):
        assert refused not in compose, f"{refused} is not allowed in a Dokploy template"
    assert re.search(r"^services:\n  ponos:$", compose, re.MULTILINE), (
        "the service is the folder's name"
    )
    assert (
        [domain["serviceName"] for domain in template["config"]["domains"]]
        == [meta["id"]]
        == ["ponos"]
    )
    assert template["config"]["domains"][0]["port"] == 8787
    assert (release.BLUEPRINT / meta["logo"]).is_file()
    # An array of `KEY=value` strings: the catalogue's AGENTS.md refuses the table form.
    entries = template["config"]["env"]
    assert isinstance(entries, list), "env is an array of strings, not a table"
    env = dict(entry.split("=", 1) for entry in entries)
    given = set(env)
    read = set(re.findall(r"\$\{(\w+)\}", compose))
    assert given == read, given ^ read
    secrets = {"PONOS_WEB_PASSWORD", "PONOS_WEB_TOKEN"}
    assert all(env[name].startswith("${") for name in secrets), "generated, never written"
    for name in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "GH_TOKEN", "PONOS_NOTION_TOKEN"):
        assert env[name] == "", f"{name} is the user's to give"


@case
def a_release_only_ever_moves_forward():
    assert release.next_version("0.1.0", "patch") == "0.1.1"
    assert release.next_version("0.1.9", "minor") == "0.2.0"
    assert release.next_version("0.9.3", "major") == "1.0.0"
    assert release.next_version("1.2.3", "2.0.0") == "2.0.0"

    for backwards in ("0.1.0", "1.2.2", "1.0.0"):
        try:
            release.next_version("1.2.3", backwards)
        except release.Problem:
            pass
        else:
            raise AssertionError(f"{backwards} after 1.2.3 must be refused")

    # Once, in a repository's life: nothing released yet, so the number the tree
    # already carries is the number to release it under.
    assert release.next_version("0.1.0", "0.1.0", first=True) == "0.1.0"


@case
def a_bump_promotes_the_notes_and_opens_an_empty_unreleased():
    text = (
        "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- A thing.\n\n"
        "## [0.1.0] - 2026-01-01\n\n### Added\n\n- The first thing.\n"
    )
    moved = release.promote(text, "0.2.0", "2026-08-31")

    names = [name for name, _date, _body in release.sections(moved)]
    assert names == ["Unreleased", "0.2.0", "0.1.0"], names

    assert release.notes_for(moved, "0.2.0") == "### Added\n\n- A thing."
    assert release.notes_for(moved, "0.1.0") == "### Added\n\n- The first thing."
    unreleased = dict((name, body) for name, _date, body in release.sections(moved))
    assert unreleased["Unreleased"].strip() == "", "the next cycle starts empty"


@case
def an_empty_unreleased_is_not_a_release():
    """A tag with no notes is a tag, and nobody came here for a tag."""
    for refused in (
        "# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-01-01\n\n- One.\n",
        "# Changelog\n\n## [0.1.0] - 2026-01-01\n\n- One.\n",
    ):
        try:
            release.promote(refused, "0.2.0", "2026-08-31")
        except release.Problem:
            pass
        else:
            raise AssertionError("an empty or missing [Unreleased] must be refused")

    already = "# Changelog\n\n## [Unreleased]\n\n- New.\n\n## [0.2.0] - 2026-01-01\n\n- Old.\n"
    try:
        release.promote(already, "0.2.0", "2026-08-31")
    except release.Problem:
        pass
    else:
        raise AssertionError("a version that already has a section must be refused")


@case
def the_dash_in_a_changelog_heading_is_whichever_one_was_typed():
    """The file is written by hand, and a hand that writes em dashes writes them here.

    A heading the parser fails to see is a release whose notes silently come out
    empty, which is only noticed once it is published.
    """
    for dash in ("-", "\u2013", "\u2014"):
        text = f"# Changelog\n\n## [0.1.0] {dash} 2026-01-01\n\n- One.\n"
        assert release.notes_for(text, "0.1.0") == "- One.", dash


@case
def a_bare_command_line_presents_the_product_and_its_version(state_home):
    """`ponos`, typed alone, is somebody's first look at what they installed.

    So it answers the two questions that come with that — what is this, and
    which version am I on — before it lists the verbs. The frame is drawn from
    the uncoloured text, which is what keeps it square once colours are on.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert cli_main([]) == 0
    printed = _plain(buffer.getvalue())

    assert f"Ponos {__version__}" in printed
    assert "Turns ready Notion tickets into Claude Code sessions." in printed
    for name in subcommands():
        assert f"\n    {name} " in printed or f"\n    {name}  " in printed, (
            f"{name} is a command the welcome screen does not name"
        )

    framed = [line for line in _plain(banner()).splitlines() if line.strip()]
    assert len({len(line) for line in framed}) == 1, "the frame is not square"


@case
def a_waiting_update_is_said_on_the_welcome_screen(state_home):
    """The one thing worth adding to a version number: that it is not the newest.

    Read from the stamp a run already wrote — a welcome screen that fetched
    would be a network round trip for every `ponos` typed by mistake.
    """
    update.remember(update.Status(current="a" * 40, latest="b" * 40))
    assert "b" * 8 in _plain(banner())
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        welcome(build_parser())
    assert "ponos update" in _plain(buffer.getvalue())


@case
def the_console_header_and_the_command_line_agree_on_the_version(state_home):
    """One number, two surfaces: what --version prints is what the browser shows.

    The console reads it bare — an update waiting is a separate field, so the
    header can print a version where a version belongs rather than a sentence.
    It follows the number with the commit it runs, read from git: between two
    releases every commit ran under the same number, and only the commit says
    which code answers.
    """
    running = update.running()
    number, _, short = running["version"].partition("+")
    assert number == __version__ and len(short) >= 7 and _head(ROOT).startswith(short), running
    assert running["commit"] == _head(ROOT), "the tooltip names another commit"
    assert running["date"] and running["subject"], "the tooltip has nothing to say"
    assert web_api._update_available() == "", "nothing checked yet is not an update"
    # Compared against what is on disk: the stamp has to be about this checkout.
    update.remember(update.Status(current=_head(ROOT), latest="b" * 40))
    assert web_api._update_available() == "b" * 8


@case
def a_copy_that_is_not_a_repository_says_its_number_alone():
    """No `.git` beside the sources — a copy, an image: the number, and no commit."""
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "app"
        shutil.copytree(ROOT / "src", copy / "src", ignore=shutil.ignore_patterns("__pycache__"))
        said = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json; from ponos import update; print(json.dumps(update.running()))",
            ],
            env={**os.environ, "PYTHONPATH": str(copy / "src")},
            cwd=scratch,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    assert json.loads(said) == {"version": __version__, "commit": "", "date": "", "subject": ""}, (
        said
    )


STATIC = ROOT / "src/ponos/web/static"


def _shipped() -> list[Path]:
    """Every file the console hands a browser, as it sits in the package.

    `frontend/` is the source; this is the build, and the build is what is
    committed — the installer is a `git clone` onto a machine that has python3
    and git and no reason to have Node.
    """
    return [STATIC / "index.html", *sorted((STATIC / "assets").glob("*"))]


def _built(extension: str) -> Path:
    """The console's own file of that kind, whatever hash the build gave it."""
    found = sorted((STATIC / "assets").glob(f"console-*.{extension}"))
    assert len(found) == 1, f"one console.{extension} expected, the build left {found}"
    return found[0]


@case
def the_console_ships_its_built_bundle():
    """A clone of this repository is a console that opens, with nothing built.

    `ponos` installs by cloning and running `python3`. If the bundle
    lived only in `frontend/` and were built on the way in, the install would
    need Node — which is exactly the dependency this tool exists without.
    """
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    bundle, style = _built("js"), _built("css")
    # The names are hashed, so the page is what says which build it is: a file
    # it names that is not in the package is a console that opens blank.
    assert f"/static/assets/{bundle.name}" in page, "the page does not load the bundle"
    assert f"/static/assets/{style.name}" in page, "the page does not load the stylesheet"
    for named in re.findall(r'"/static/(assets/[^"]+)"', page):
        assert (STATIC / named).is_file(), f"the page names a file the build did not write: {named}"
    assert (FRONTEND / "package.json").is_file(), "the source the bundle is built from is gone"
    assert (FRONTEND / "components.json").is_file(), "shadcn/ui is no longer configured"


@case
def the_console_is_downloaded_once_and_compressed():
    """A second load fetches the page and nothing else; the first, gzipped.

    On 1 October 2026 every load of the console downloaded 1.3 MB again: every
    file was `no-store`, nothing was compressed, and the names were fixed, so
    nothing could have been kept safely either. The names now change with what
    the files hold, so `assets/` is kept for a year and `index.html` — the one
    file that says which names are current — is never kept at all.
    """
    import urllib.request

    from ponos.web import app as web_app

    api = _bare_api(_TalkClient([]))
    console = web_app.Console(("127.0.0.1", 0), api, "tok")
    threading.Thread(target=console.serve_forever, daemon=True).start()
    port = console.server_address[1]

    def get(path: str, **headers: str):
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", headers={"Authorization": "Bearer tok", **headers}
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.headers, response.read()

    bundle = _built("js")
    try:
        headers, _ = get("/")
        assert headers["Cache-Control"] == "no-store", "the page that names the build was kept"
        headers, body = get(f"/static/assets/{bundle.name}", **{"Accept-Encoding": "gzip, br"})
        assert (
            "immutable" in headers["Cache-Control"]
            and "max-age=31536000" in headers["Cache-Control"]
        )
        assert headers["Content-Encoding"] == "gzip" and headers["Vary"] == "Accept-Encoding"
        assert gzip.decompress(body) == bundle.read_bytes(), "gzipped is not the same file"
        assert int(headers["Content-Length"]) == len(body) < bundle.stat().st_size / 2
        headers, body = get(f"/static/assets/{bundle.name}")
        assert headers["Content-Encoding"] is None and body == bundle.read_bytes(), (
            "a client that never asked for gzip got it"
        )
        headers, _ = get(f"/static/assets/{bundle.name}", **{"Accept-Encoding": "gzip;q=0"})
        assert headers["Content-Encoding"] is None, "q=0 means never"
    finally:
        console.shutdown()
        console.server_close()

    # What the first load fetches — the page, the bundle and what it preloads,
    # the stylesheet and the icon — under the 500 kB the ticket set, gzipped.
    # For a reader of French, that is with the dictionary the page then asks
    # for: the heavier of the two first loads is the one held to the budget.
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    first = [STATIC / "index.html"] + [
        STATIC / named for named in re.findall(r'"/static/(assets/[^"]+)"', page)
    ]
    french = sorted((STATIC / "assets").glob("french-*.js"))
    assert len(french) == 1, f"one French dictionary expected, the build left {french}"
    assert french[0] not in first, "the French dictionary is fetched by readers of English too"
    weight = sum(len(gzip.compress(path.read_bytes(), compresslevel=9)) for path in first + french)
    assert weight < 500_000, f"the first load in French is {weight // 1000} kB compressed"


@case
def the_console_is_installable_as_an_app():
    """A manifest, three icons and a worker, served to a browser with no cookie.

    A browser fetches the manifest and the worker for itself, and a manifest
    request leaves without the cookie unless the page says `use-credentials` —
    so these answer to nobody in particular, and what they answer is whole: every
    icon the manifest names is a file of the build, the worker is served from
    `/` so that it may control `/`, and it is never kept, or an installed app
    would stay on the build it was installed with.
    """
    import json
    import urllib.error
    import urllib.request

    from ponos.web import app as web_app

    api = _bare_api(_TalkClient([]))
    console = web_app.Console(("127.0.0.1", 0), api, "tok")
    threading.Thread(target=console.serve_forever, daemon=True).start()
    port = console.server_address[1]

    def get(path: str):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            return response.headers, response.read()

    try:
        headers, body = get("/static/manifest.webmanifest")
        assert headers["Content-Type"].startswith("application/manifest+json")
        manifest = json.loads(body)
        assert manifest["display"] == "standalone" and manifest["start_url"] == "/"
        assert manifest["name"] and manifest["short_name"]
        sizes = {(icon["sizes"], icon["purpose"]) for icon in manifest["icons"]}
        assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes
        for icon in manifest["icons"]:
            headers, data = get(icon["src"])
            assert headers["Content-Type"] == "image/png" and data.startswith(b"\x89PNG")
        headers, body = get("/sw.js")
        assert headers["Content-Type"].startswith("application/javascript") or headers[
            "Content-Type"
        ].startswith("text/javascript")
        assert headers["Cache-Control"] == "no-store", (
            "an installed app would never see a new build"
        )
        assert b"__BUILD__" not in body, "the worker was shipped as a template"
        get("/static/offline.html")
        # And the console itself is still behind its key.
        try:
            get("/api/board")
            raise AssertionError("the board answered without a key")
        except urllib.error.HTTPError as error:
            assert error.code == 401
    finally:
        console.shutdown()
        console.server_close()

    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'rel="manifest"' in page and 'crossorigin="use-credentials"' in page


@case
def the_console_and_the_landing_page_draw_one_robot():
    """The mascot is one file, and the console bundles it rather than a copy.

    The landing page loads `docs/mascot/ponos-robot.js` from a <script>
    tag; the console imports that very module through Vite, and takes its
    favicon from the same directory. A second copy of the drawing would be a
    robot that changes on one page and not on the other.
    """
    mascot = ROOT / "docs/mascot/ponos-robot.js"
    assert mascot.is_file(), "the mascot's one source is gone"
    copies = [
        path
        for path in ROOT.rglob("ponos-robot.js")
        if "node_modules" not in path.parts and path != mascot
    ]
    assert not copies, f"a copy of the mascot: {copies}"
    robot = (FRONTEND / "src/components/console/robot.tsx").read_text(encoding="utf-8")
    assert '"@mascot/ponos-robot.js"' in robot, "the console draws a robot of its own"
    vite = (FRONTEND / "vite.config.ts").read_text(encoding="utf-8")
    assert '"../docs/mascot"' in vite, "@mascot no longer points at the landing page's file"
    page = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert "../docs/mascot/favicon.svg" in page, "the console's favicon is not the mascot's"
    source = mascot.read_text(encoding="utf-8")
    assert "waiting:" in source, "a ticket waiting on a person has no face of its own"
    assert "'still'" in source, "a board of robots cannot hold them still"


LANDING = ROOT / "docs/index.html"


@case
def the_console_and_the_landing_page_share_one_set_of_tokens():
    """One file of colours, faces and radius, and the site has no other.

    The console imports `frontend/src/tokens.css`; the site has no build step,
    so it links `docs/tokens.css`, which `npm run build` copies. A copy that
    drifts is two identities again — and the site's own stylesheet naming a
    colour of its own is the same drift, written by hand.
    """
    source = (FRONTEND / "src/tokens.css").read_text(encoding="utf-8")
    copy = (ROOT / "docs/tokens.css").read_text(encoding="utf-8")
    assert copy == source, "docs/tokens.css is stale — run npm run build in frontend/ and commit it"
    for name in (
        "--primary",
        "--background",
        "--radius",
        "--tr-green",
        "--series-1",
        "--sans",
        "--mono",
        "--heading",
    ):
        assert f"{name}:" in source, f"{name} is not among the tokens"
    assert ".dark {" in source, "the tokens have no dark theme"
    index = (FRONTEND / "src/index.css").read_text(encoding="utf-8")
    assert '@import "./tokens.css";' in index, "the console no longer reads the tokens"
    assert "--primary:" not in index, "the console declares a colour outside the tokens"
    vite = (FRONTEND / "vite.config.ts").read_text(encoding="utf-8")
    assert '"../docs/tokens.css"' in vite, "the build no longer publishes the tokens for the site"

    page = LANDING.read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="tokens.css">' in page, "the site does not load the tokens"
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]
    stray = re.findall(r"#[0-9a-fA-F]{3,8}\b", style)
    assert not stray, f"the site names colours of its own: {stray}"
    for gone in ("Inter", "Instrument Serif", "#3b82f6"):
        # A whole word: `IntersectionObserver` is not the old face.
        assert not re.search(rf"(?<!\w){re.escape(gone)}(?!\w)", page), (
            f"{gone} is the old identity"
        )
    assert "family=Bricolage+Grotesque" in page, "the site does not load the headings' face"
    for gone in ("DM+Sans", "JetBrains+Mono"):
        assert gone not in page, f"{gone} is the old identity"
    assert "ponos-theme" in page and "prefers-color-scheme" in page, (
        "the site has no light and dark"
    )


@case
def the_landing_page_opens_on_ponos_and_tells_the_loop_in_seven_sections():
    """Seven sections at most, the first one Ponos and the promise.

    Seventeen sections at the same level is a manual, and the manual is the
    README: the site says the promise, the four kinds of task, the loop and
    three proofs, the console, the integrations — Notion among them, not
    before them —, the install and who made it, and links the rest.
    """
    page = LANDING.read_text(encoding="utf-8")
    sections = re.findall(r"<section\b[^>]*>", page)
    assert 0 < len(sections) <= 7, f"{len(sections)} sections — the site is a manual again"
    hero = page.split("<section", 2)[1]
    assert 'id="top"' in hero.split(">", 1)[0], "the page does not open on its hero"
    assert "<ponos-robot" in hero and "Ponos" in hero, "Ponos is not on the first screen"
    assert "Write the ticket." in hero and "It comes back done." in hero, (
        "the promise is not the headline"
    )
    title = re.search(r"<title>(.*?)</title>", page).group(1)
    assert "Write the ticket. It comes back done." in title
    assert "Notion" not in title and "Claude" not in title, (
        "the promise leans on somebody else's brand"
    )
    description = re.search(r'<meta name="description" content="([^"]*)"', page).group(1)
    assert "It comes back done." in description
    assert "It comes back done." in re.search(
        r'<meta property="og:title" content="([^"]*)"', page
    ).group(1)
    assert "It comes back done." in (ROOT / "docs/llms.txt").read_text(encoding="utf-8")


@case
def the_heros_picture_is_the_loop_and_ends_on_your_decision():
    """Three numbered steps, and the third a decision rather than a pull request.

    The promise is *nothing ships until you say yes*: the picture shows the two
    gestures the console really offers on a ticket in review — Validate, Run
    again — and the way back to Ponos. Without script or motion it rests on
    that decision, and the ticket of the first step stays Ready all along.
    """
    page = LANDING.read_text(encoding="utf-8")
    figure = page.split('<figure class="card flow" id="flow"', 1)[1].split("</figure>", 1)[0]
    assert 'data-step="3"' in figure.split(">", 1)[0], (
        "without script, the picture is not at the decision"
    )
    steps = re.findall(r'<span class="flow-num">(\d)</span><b>([^<]+)</b>', figure)
    assert [n for n, _ in steps] == ["1", "2", "3"], (
        f"the steps are not numbered one to three: {steps}"
    )
    assert "Ponos" in steps[1][1], "the second step is not Ponos's"
    assert ">Validate<" in figure and ">Run again<" in figure, (
        "the decision has lost one of its two buttons"
    )
    assert "flow-link to-you" in figure and "your note" in figure, "the way back to Ponos is gone"
    assert "<ponos-robot" in figure
    statuses = re.findall(r'<span class="status[^"]*">([^<]+)</span>', figure)
    assert statuses == ["Ready"], f"the ticket of step one moves on: {statuses}"
    label = re.search(r'role="img" aria-label="([^"]+)"', figure).group(1)
    assert "Validate" in label and "Run again" in label, (
        "the picture's description does not tell the decision"
    )
    # The console's own words, so the picture does not promise a button that is not there.
    bits = (FRONTEND / "src/components/console/ticket-bits.tsx").read_text(encoding="utf-8")
    assert 't("Validate and publish")' in bits and 't("Run again")' in bits


@case
def the_landing_page_shows_the_console_filmed_right_after_its_hero():
    """The hero promises; the section under it shows the real console doing it.

    A schematic board drawn in the page's own markup came second, and it looked
    like no screen of the product. What comes second now is the console itself,
    filmed by `scripts/film-console.mjs`: light and dark, each light enough for
    the second screen of a page, fetched only as the section comes near and
    started by the script — never by an `autoplay` the browser would honour
    before the page could ask whether motion is welcome. The four gestures stay
    under it as its legend, lit from the film's clock.
    """
    page = LANDING.read_text(encoding="utf-8")
    order = re.findall(r'<section\b[^>]*\bid="([^"]+)"', page)
    assert order[:3] == ["top", "loop", "tasks"], f"the loop no longer follows the hero: {order}"
    assert "board-demo" not in page and 'id="board"' not in page, "the schematic board is back"
    loop = page.split('<section id="loop">', 1)[1].split("</section>", 1)[0]
    video = re.search(r"<video\b[^>]*>", loop, re.S).group(0)
    for attribute in ("muted", "loop", "playsinline", 'preload="none"'):
        assert re.search(rf"\s{attribute}(?=[\s>])", video), f"the film is not {attribute}"
    assert "autoplay" not in video, "the film starts before the page can ask about motion"
    assert re.search(r'\sposter="media/console-loop-light-poster\.webp"', video), (
        "the film has no poster"
    )
    for theme in ("light", "dark"):
        for attribute, name in (
            (f"data-{theme}", f"console-loop-{theme}.mp4"),
            (f"data-poster-{theme}", f"console-loop-{theme}-poster.webp"),
        ):
            assert f'{attribute}="media/{name}"' in video, f"the {theme} film lacks {attribute}"
            file = ROOT / "docs/media" / name
            assert file.exists(), f"docs/media/{name} is missing — node scripts/film-console.mjs"
            assert file.stat().st_size < 2_000_000, (
                f"docs/media/{name} is too heavy for the second screen"
            )
    for theme in ("light", "dark"):
        cues = [
            float(at) for at in re.search(rf'data-cues-{theme}="([^"]+)"', video).group(1).split()
        ]
        assert len(cues) == 4 and cues[0] == 0 and cues == sorted(cues), (
            f"one cue per gesture, in order: {cues}"
        )
    assert loop.count('class="card step"') == 4, "the four gestures are no longer the legend"
    assert loop.index("<video") < loop.index('class="grid g4 gestures"'), (
        "the legend comes before the film"
    )
    script = (ROOT / "scripts/film-console.mjs").read_text(encoding="utf-8")
    assert "data-cues" in script, "the film's script no longer writes the cues into the page"
    assert "node scripts/film-console.mjs" in (ROOT / "README.md").read_text(encoding="utf-8"), (
        "the command that films the console is not documented"
    )


@case
def the_site_answers_the_icons_a_browser_asks_for_and_a_page_of_its_own_for_a_lost_one():
    """`/favicon.ico` and `/apple-touch-icon.png` are asked for whatever the page declares.

    A browser, a feed reader or an iPhone saving the page look for them at the
    root without reading a <link> — a 404 there is a blank square on a home
    screen. And an address that does not exist lands on GitHub Pages' own 404
    unless `docs/404.html` is there to say Ponos.
    """
    import struct

    ico = (ROOT / "docs/favicon.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", ico[:6])
    assert (reserved, kind) == (0, 1) and count >= 2, "favicon.ico is not an icon with its sizes"
    sizes = {ico[6 + 16 * n] or 256 for n in range(count)}
    assert {16, 32} <= sizes, f"favicon.ico lacks the tab's sizes: {sizes}"
    touch = (ROOT / "docs/apple-touch-icon.png").read_bytes()
    assert touch.startswith(b"\x89PNG") and struct.unpack(">II", touch[16:24]) == (180, 180)
    page = LANDING.read_text(encoding="utf-8")
    assert 'rel="apple-touch-icon" href="apple-touch-icon.png' in page, (
        "the page does not declare its touch icon"
    )
    lost = (ROOT / "docs/404.html").read_text(encoding="utf-8")
    assert "Ponos" in lost and 'href="/"' in lost, "the 404 does not lead back to the site"
    assert 'href="/mascot/favicon.svg' in lost, (
        "a 404 at any depth loses its icon with a relative path"
    )
    script = (ROOT / "scripts/mascot.mjs").read_text(encoding="utf-8")
    assert "favicon.ico" in script and "apple-touch-icon.png" in script, (
        "the site's icons are not drawn from the mascot"
    )


@case
def the_repository_s_homepage_is_the_site():
    """The package says where Ponos lives, and the example says whose repositories a session may touch."""
    import tomllib

    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    assert package["homepage"] == "https://the-ponos.app", package["homepage"]
    example = tomllib.loads((ROOT / "config.example.toml").read_text(encoding="utf-8"))
    assert example["permissions"]["allowed"] == list(C.ALLOWED), (
        "config.example.toml says other rules than the code"
    )
    assert example["permissions"]["ask"] == list(C.ASK)


@case
def ponos_is_named_on_the_site_in_the_readme_and_in_the_console():
    """The robot's name, in both languages, wherever the robot is."""
    assert "Ponos" in LANDING.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Write the ticket. It comes back done." in readme.split("---", 1)[0], (
        "the README opens elsewhere"
    )
    assert "## Ponos, the mascot" in readme
    shell = (FRONTEND / "src/components/console/shell.tsx").read_text(encoding="utf-8")
    mark = shell.split("export function Mark()", 1)[1].split("\n}\n", 1)[0]
    assert 'title="Ponos"' in mark and ">Ponos<" in mark, "the console's robot has no name"
    mascot = (ROOT / "docs/mascot/ponos-robot.js").read_text(encoding="utf-8")
    assert "Ponos" in mascot.split("*/", 1)[0], "the component's documentation does not say Ponos"
    assert "customElements.define('ponos-robot'" in mascot, (
        "the tag changed name — pages that embed it would lose their robot"
    )
    assert "<title>Ponos" in (ROOT / "docs/mascot/robot.svg").read_text(encoding="utf-8")


@case
def the_landing_page_tells_notion_in_one_band_with_its_badge_served_locally():
    """Notion is optional: one band, not four rows longer than the console.

    One window chains the three captures and steps that follow it; a video
    plays muted and inline or a phone opens it full screen, and nothing loads
    before the band is near. The mark is Notion's own "Made for Notion" badge,
    in both of its variants, from docs/ — their guidelines forbid the bare logo,
    and a third-party CDN would see every visit.
    """
    page = LANDING.read_text(encoding="utf-8")
    assert page.count('id="notion"') == 1, "the links to #notion land nowhere"
    band = page.split('id="notion"', 1)[1].split('class="notion-foot"', 1)[0]
    assert 'class="rows"' not in page and ".rows " not in page, "the four rows are back"
    videos = re.findall(r"<video\b[^>]*>", band)
    for name in ("notion-read-result", "notion-text", "notion-validate"):
        assert f'src="media/notion/{name}.mp4"' in band, f"{name}.mp4 is not in the band"
    assert (
        band.index("notion-read-result.mp4")
        < band.index("notion-text.mp4")
        < band.index("notion-validate.mp4")
    )
    assert len(videos) == 3 and band.count('class="window loop"') == 1, (
        "the band holds more than one window"
    )
    for video in videos:
        assert "muted" in video and "playsinline" in video, (
            "a video would play aloud, or full screen"
        )
        assert 'preload="none"' in video, "a video loads before the band is near"
        assert 'aria-label="' in video, "a video says nothing to a screen reader"
        assert " loop " not in video, "a video loops on itself instead of calling the next"
    steps = re.findall(r"<button\b[^>]*\bdata-step=[^>]*>", band)
    assert len(steps) == 3 and all("aria-pressed" in b for b in steps), (
        "the steps are not buttons that say their state"
    )
    assert "data-toggle" in band and "data-play" in band, (
        "the window lost its pause or its play button"
    )
    badges = re.findall(r'<img\b[^>]*alt="Made for Notion"[^>]*>', band)
    assert len(badges) == 2, "the badge needs its light and its dark variant"
    for badge in badges:
        src = re.search(r'src="([^"]+)"', badge).group(1)
        assert src.startswith("media/notion/") and (ROOT / "docs" / src).exists(), (
            f"the badge is not served from docs/: {src}"
        )
        assert 'height="48"' in badge, "Notion asks for a badge 48 px high on screen"
    assert 'class="notion-foot"' in page, "the line on Notion and the files kept in step is gone"


def _readme_anchors() -> set[str]:
    """The anchors GitHub gives the README's headings, and the ones it declares.

    GitHub's rule: lowercase, drop what is neither a letter, a digit, a space, a
    hyphen nor an underscore, and turn spaces into hyphens. Headings inside a
    code block are not headings.
    """
    anchors: set[str] = set()
    fenced = False
    for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = re.match(r"#{1,6} (.+)", line)
        if heading:
            text = heading.group(1).strip().lower().replace("`", "")
            anchors.add(re.sub(r"[^\w\- ]", "", text).replace(" ", "-"))
        anchors.update(re.findall(r'<a id="([^"]+)"', line))
    return anchors


@case
def the_landing_page_and_the_readme_link_to_anchors_that_exist():
    """A link into the documentation is a promise the documentation keeps.

    The site sends everything it no longer explains to a README heading, and
    the README sends its reader around itself: a heading renamed without its
    links is a reader landing at the top of a very long page.
    """
    page = LANDING.read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', page))
    for anchor in re.findall(r'href="#([^"]*)"', page):
        assert anchor in ids, f"the site links #{anchor}, which it does not have"
    for target in re.findall(r'href="([^"#:]+)"', page):
        # `?v=` only makes a browser fetch the file again: the file is what has to exist.
        target = target.split("?", 1)[0]
        assert (ROOT / "docs" / target).exists(), (
            f"the site links {target}, which docs/ does not have"
        )
    anchors = _readme_anchors()
    linked = re.findall(r'href="https://github\.com/hermez-agency/ponos#([^"]+)"', page)
    assert linked, "the site no longer points at the documentation"
    for anchor in linked:
        assert anchor == "readme" or anchor in anchors, (
            f"the site links README#{anchor}, which has no such heading"
        )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for anchor in re.findall(r"\]\(#([^)]+)\)", readme):
        assert anchor in anchors, f"the README links #{anchor}, which has no such heading"


@case
def the_console_says_the_version_it_is_running_beside_the_stream_s_dot():
    """The number reaches the page, rather than staying in the payload.

    It used to be a pill in the bar, beside four others — the timer, a run in
    flight, what had been spent — and a row of states you cannot act on, drawn
    over every page, is noise with a border around it. The version, and the day
    a newer one is waiting, are said once, where the stream's own dot is: the
    end of the admin layout's bar, the one place it leaves to the application.

    Read from the React source rather than the bundle: the bundle is minified,
    and asserting on minified identifiers is asserting on the minifier.
    """
    shell = (FRONTEND / "src/components/console/shell.tsx").read_text(encoding="utf-8")
    badge = (FRONTEND / "src/components/console/version-badge.tsx").read_text(encoding="utf-8")
    assert "Pill" not in shell, "the bar carries a row of pills again"
    assert "<VersionBadge" in shell, "the bar lost the version"
    assert "runner.version" in badge, "the console has nowhere to print the version"
    assert "runner.upgrade" in badge, "an update waiting has to be said too"
    assert "api.upgrade()" in badge, "and offered, rather than left to a terminal"


@case
def the_discussion_opens_from_a_bubble_rather_than_from_a_column():
    """One way in, in the corner every reader already looks in for a chat.

    Half the screen used to be given to a conversation whether or not there was
    one, with an entry in the menu to reach it where there was no room for the
    column and a switch in the bar to fold it away — three things to learn for
    one thing to open. It is a drawer now, over the page rather than beside it,
    and the page keeps its full width until the bubble is pressed.

    Read from the React source rather than from the bundle: the bundle is
    minified, and what is being checked here is a decision, not a symbol.
    """
    drawer = (FRONTEND / "src/components/console/talk-drawer.tsx").read_text(encoding="utf-8")
    # shadcn's own sheet, which is the drawer: nothing here draws a panel of its
    # own, and the one the sidebar already opens on a phone is this one.
    assert "SheetContent" in drawer, "the drawer is hand-rolled again"
    assert 'side="right"' in drawer, "the drawer no longer comes in from the right"
    assert "ConsolePane" in drawer, "the drawer no longer holds the console"
    # A ticket's discussion is a tab of its page: a bubble that changed role on
    # a ticket said so nowhere, and a question waiting on you sat behind it.
    assert "TicketTalk" not in drawer, "the bubble turns into a ticket's discussion again"
    page = (FRONTEND / "src/components/console/ticket-page.tsx").read_text(encoding="utf-8")
    assert "<TicketTalk " in page, "a ticket's page no longer holds its discussion"
    app = (FRONTEND / "src/App.tsx").read_text(encoding="utf-8")
    assert "TalkDrawer" in app, "nothing opens the discussion"
    assert "ConsolePane" not in app, "the console has a column of its own again"
    assert "asideLabel" not in app, "the bar carries the switch that folds it away again"
    scope = (FRONTEND / "src/resources/scope.tsx").read_text(encoding="utf-8")
    assert "ConsolePane" not in scope, "the menu has an entry for the drawer again"


@case
def the_console_is_drawn_in_react_resource_view_s_admin_layout():
    """One admin interface, the package's, rather than two kept side by side.

    The console had a frame of its own — a sidebar, a bar, a router over the
    History API — around pages that were already react-resource-view's. The
    frame is the package's now: a scope declares the resources and the menu,
    `createAdminLayout` draws them, and TanStack Router holds the history
    through the adapter the package ships for it. What the console drew by hand
    is gone rather than kept beside it.

    Read from the React source rather than from the bundle: the bundle is
    minified, and what is being checked here is a decision, not a symbol.
    """
    scope = (FRONTEND / "src/resources/scope.tsx").read_text(encoding="utf-8")
    assert "createAdminLayout" in scope, "the console draws its own frame again"
    for resource in ("tickets", "projects", "schedules", "ideas", "sessions", "settings"):
        assert f"entry({resource}.icon" in scope, f"the menu has no entry for {resource}"
    # Configured by the places the layout leaves, not redrawn around it: the
    # pages past the first three are its footer links, which a phone reaches
    # by the More it draws, and the console's own state is its sidebar's foot.
    for option in ("logo:", "topBarEnd:", "sidebarFooter:", "footerMenu:"):
        assert option in scope, f"the layout is no longer given its {option[:-1]}"
    shell = (FRONTEND / "src/components/console/shell.tsx").read_text(encoding="utf-8")
    # The layout decides where a phone starts and does not export its hook: the
    # one question the scope asks is the menu's, which pages the bar keeps, and
    # it asks it at the layout's own breakpoint (`md`, 48rem).
    assert "matchMedia" not in shell, "the console guesses the layout's phone width again"
    assert scope.count("matchMedia") == 1 and 'matchMedia("(width < 48rem)")' in scope, (
        "the scope asks for a phone width other than the layout's"
    )
    app = (FRONTEND / "src/App.tsx").read_text(encoding="utf-8")
    assert "ScopeProvider" in app, "the pages are no longer drawn in the scope's layout"
    assert "RouterProvider" in app, "TanStack Router no longer holds the history"
    views = (FRONTEND / "src/lib/resource-view.ts").read_text(encoding="utf-8")
    assert "tanstackAdapter" in views, "the views reach the router some other way again"
    for gone in ("app-sidebar.tsx", "header.tsx", "resource-pane.tsx"):
        assert not (FRONTEND / "src/components/console" / gone).exists(), (
            f"{gone} is back, beside the layout that replaced it"
        )
    assert not (FRONTEND / "src/components/ui/sidebar.tsx").exists(), "a second sidebar is back"
    # The component that rereads the board on every event sits over every view
    # of the tickets — react-resource-view 1.0 merges a view's `components`
    # into the resource's — and no view takes it away: without it the board
    # stops following the stream.
    tickets = (FRONTEND / "src/resources/tickets.tsx").read_text(encoding="utf-8")
    assert "components: { top: BoardTop }" in tickets, (
        "the board no longer rereads itself when the stream moves it"
    )
    assert "top: null" not in tickets, "a view of the tickets no longer follows the stream"


@case
def a_project_is_a_resource_with_two_layouts_and_a_form():
    """Clickable, editable, and drawn two ways — which is what the screen is for.

    Read from the React source rather than from the bundle: the bundle is
    minified, and what is being checked here is a decision, not a symbol. A
    project drawn by hand again — a pane with rows in it — would take the page
    back to a list you can only look at.
    """
    declared = (FRONTEND / "src/resources/projects.tsx").read_text(encoding="utf-8")
    assert "createViewResource" in declared, "the projects are a hand-rolled pane again"
    assert "layout.cards(" in declared, "the card layout is gone"
    assert "layout.table(" in declared, "the second layout is gone"
    permissions = declared.split("permissions:")[1].split("\n")[0]
    assert "update" not in permissions and "readonly" not in permissions, (
        "a project is read-only again"
    )
    assert "api.saveProject" in declared, "nothing writes the project back"
    page = (FRONTEND / "src/components/console/project-page.tsx").read_text(encoding="utf-8")
    assert "ResourceViewButton" in page, "the page offers no way into the form"
    assert (
        (FRONTEND / "src/lib/router.tsx")
        .read_text(encoding="utf-8")
        .count("?view=console/projects/list")
    ), "the address the pane had stopped leading to the projects"


@case
def a_schedule_is_a_resource_drawn_in_the_package_s_own_layouts():
    """The one page whose rows are dates, laid out as dates.

    It was a pane: cards drawn by hand, a form written by hand, and a date
    formatted into "in 6 days" by hand. All three exist in the package the board
    and the projects are already drawn with, so the schedules are a resource
    like them — a table to compare them in and a calendar to read the next
    occurrence off, and no second design language on the one screen that had
    one.

    Read from the React source rather than from the bundle: the bundle is
    minified, and what is being checked here is a decision, not a symbol.
    """
    declared = (FRONTEND / "src/resources/schedules.tsx").read_text(encoding="utf-8")
    assert "createViewResource" in declared, "the schedules are a hand-rolled pane again"
    assert "layout.table(" in declared, "the table layout is gone"
    assert "layout.calendar<" in declared, "the calendar layout is gone"
    assert 'dateField: "when"' in declared, (
        "the calendar no longer lays out the launches by when they land"
    )
    assert "api.saveSchedule" in declared, "nothing writes a schedule back"
    assert "api.createSchedule" in declared, "nothing writes a new schedule"
    # The columns a pass writes back are how the runner knows an occurrence has
    # been taken; a form that offered them would let you make one happen twice,
    # or never. The list shows them; the fields the forms are built from do not.
    fields = declared.split("const fields")[1].split("const createForm")[0]
    for written_back in ("next", "last"):
        assert f"{written_back}: {{" not in fields, (
            f"the form offers `{written_back}`, which a pass writes back"
        )
    for gone in ("schedules-pane.tsx", "schedule-form.tsx"):
        assert not (FRONTEND / "src/components/console" / gone).exists(), (
            f"{gone} is back, beside the resource that replaced it"
        )
    assert "?view=console/schedules/list" in (FRONTEND / "src/lib/router.tsx").read_text(
        encoding="utf-8"
    ), "the address the pane had stopped leading to the schedules"


@case
def a_session_is_followed_on_its_ticket_rather_than_on_a_page_of_sessions():
    """The live page listed sessions by the id of their log, and nothing more.

    `24f9704c` said nothing of the ticket it was: the session is read where the
    ticket is — a section of its page, a line on its card — and the page is gone.
    Its address still leads somewhere: a link somebody kept lands on the board.
    """
    assert not (FRONTEND / "src/resources/live.tsx").exists(), "the live page is back"
    assert not (FRONTEND / "src/components/console/live-pane.tsx").exists(), "the live pane is back"
    scope = (FRONTEND / "src/resources/scope.tsx").read_text(encoding="utf-8")
    assert "LIVE" not in scope, "the menu has an entry for the live page again"
    router = (FRONTEND / "src/lib/router.tsx").read_text(encoding="utf-8")
    assert 'live: "/?view=console/tickets/list"' in router, (
        "/?page=live no longer reaches the board"
    )
    page = (FRONTEND / "src/components/console/ticket-page.tsx").read_text(encoding="utf-8")
    assert "<TicketLive" in page, "a ticket's page no longer shows its session"
    assert '(running ? "live"' in page, "a running ticket no longer opens on its session"
    tickets = (FRONTEND / "src/resources/tickets.tsx").read_text(encoding="utf-8")
    assert "<CardLive" in tickets, "a running card no longer says what it is doing"
    assert "<RunnerStrip" in tickets, "the runner's figures are nowhere on the board"
    log = (FRONTEND / "src/components/console/session-log.tsx").read_text(encoding="utf-8")
    assert "<details" in log, "a tool call is no longer folded"
    assert "/worktrees/" in log, "the worktree's path is written out in full again"
    assert "outline(steps" in log, "the session is drawn step by step again, not in its broad lines"


@case
def the_console_menu_is_a_name_and_a_count():
    """Seven entries of two lines each is a page to read, not a menu to use.

    Every entry used to carry a sentence under its name — how many tickets were
    ready, whether the timer was on — which is what the pages themselves say,
    said again in the smaller type. What is worth knowing at a glance is a
    count, and a count fits beside a name — the tickets that wait for somebody
    (blocked, in review), not the finished ones the board piles up.
    """
    shell = (FRONTEND / "src/components/console/shell.tsx").read_text(encoding="utf-8")
    assert 'ticket.column === "blocked"' in shell, "the board's entry no longer counts what waits"
    assert "detail" not in shell, "an entry carries a sentence again"
    scope = (FRONTEND / "src/resources/scope.tsx").read_text(encoding="utf-8")
    assert 'entry(tickets.icon, "Dashboard", boardHref, Board' in scope, (
        "the menu is drawn without its count again"
    )


@case
def a_project_that_cannot_be_read_says_what_the_server_answered():
    """The one screen where a generic sentence cost an afternoon.

    The page a project opens on was handed `error: true` and nothing else, so
    "This project could not be read." was the whole of what a browser showed
    while the server was answering `no such route: /api/projects/<id>`. What
    the server said belongs on the page — shown, not swallowed and not replaced
    by a blank. react-resource-view 1.0 hands it over as `loadError`.
    """
    declared = (FRONTEND / "src/resources/projects.tsx").read_text(encoding="utf-8")
    getter = declared.split("getItem:")[1].split("\n")[0]
    assert "catch" not in getter, "a failed read is swallowed before the page hears of it"
    page = (FRONTEND / "src/components/console/project-page.tsx").read_text(encoding="utf-8")
    assert "why(context.loadError)" in page, "the page shows the failure without its reason again"
    assert "This project could not be read." in page, "the failure is not said at all"


@case
def no_two_routes_of_the_console_answer_one_path():
    """A path finds one route of its method, so the order they are filed in decides nothing.

    Each route is given a path its parameters accept — a Notion ID, a chat
    identifier, a number, a word — and that path must find that route alone.
    """
    from ponos.web import app, routes

    examples = {
        "[0-9a-fA-F-]{32,36}": "3eaf7e7b99c04adeae76ac6ecd52cdd0",
        "[0-9a-f]{12}": "0123456789ab",
        "[0-9]+": "42",
        r"\w+": "icon",
        r"[\w.\-]+": "20260828-112441-3eaf7e7b.jsonl",
        ".*": "assets/index.js",
    }
    table = [*routes.router.routes, *app.doors.routes]
    assert len({route.name for route in table}) == len(table), "two routes, one name"
    for route in table:
        path = route.path_format
        for name, convertor in route.param_convertors.items():
            path = path.replace(f"{{{name}}}", examples[convertor.regex])
        assert route.path_regex.fullmatch(path), (route.path, path)
        for method in route.methods:
            answering = [
                other.name
                for other in table
                if method in other.methods and other.path_regex.fullmatch(path)
            ]
            assert answering == [route.name], (method, path, answering)
    assert len(table) > 80, "the routes are filed somewhere else now"


@case
def the_console_route_of_one_project_is_the_one_the_page_asks_for():
    """The address the browser builds has to be an address the server answers.

    They are written in two languages and checked by nobody at build time: the
    page asks `/api/projects/<id>`, and the server matches that route with a
    pattern of its own. A 404 there reads, in the browser, as a project that
    could not be read.
    """
    from ponos.web import routes

    asked = "/api/projects/" + "3eaf7e7b99c04adeae76ac6ecd52cdd0"
    routed = [
        route.name
        for route in routes.router.routes
        if "GET" in route.methods and route.path_regex.fullmatch(asked)
    ]
    assert routed == ["project"], f"{asked} is not a route this server answers: {routed}"
    assert "`/api/projects/${id}`" in (FRONTEND / "src/lib/api.ts").read_text(encoding="utf-8"), (
        "the console asks for a project somewhere else now"
    )


@case
def a_turn_is_drawn_as_markdown_on_a_shadcn_bubble():
    """Both sides write markdown, so neither side is shown its source.

    A session answers in headings, lists and fenced code, on a ticket and in
    the workspace's transcript alike; a bubble that printed that as it arrived
    would be asking a reader to parse the asterisks themselves. The surface it
    is said on is shadcn's `Bubble` rather than a `div` this repository styles,
    so the palette stays the components'.
    """
    turn = (FRONTEND / "src/components/console/turn.tsx").read_text(encoding="utf-8")
    assert "<Markdown" in turn, "the transcript shows the markdown instead of drawing it"
    assert "BubbleContent" in turn, "the bubble is hand-rolled again"
    assert (FRONTEND / "src/components/ui/bubble.tsx").is_file(), "shadcn's bubble is gone"


@case
def the_console_scrolls_in_its_own_colours():
    """The bars the console scrolls on are drawn by the console, not the browser.

    Left alone, a browser paints them for a light page — pale and wide over a
    panel that is neither — and the console scrolls almost everywhere. Both
    spellings have to stay: the pseudo-elements for Chrome and WebKit, the two
    standard properties for Firefox, which has nothing else.
    """
    for style in ((FRONTEND / "src/index.css"), _built("css")):
        text = style.read_text(encoding="utf-8")
        assert "color-scheme" in text, "the browser is left to guess at the page's colours"
        assert "::-webkit-scrollbar-thumb" in text, "Chrome and WebKit keep the browser's bar"
        assert "scrollbar-color" in text, "Firefox keeps the browser's bar"
        assert "@supports not selector(::-webkit-scrollbar)" in text, (
            "Chrome prefers the standard properties, and would drop the rounded thumb"
        )


@case
def the_console_buttons_show_the_hand():
    """Whatever can be clicked shows a hand, whatever is disabled says no.

    Tailwind 4's preflight stopped putting `cursor: pointer` on `<button>`, so
    every button without its own class kept the arrow and nothing said it could
    be clicked. The rule lives once, in the base layer, for the source and the
    built bundle both.
    """
    for style in ((FRONTEND / "src/index.css"), _built("css")):
        text = re.sub(r"\s+", "", style.read_text(encoding="utf-8"))
        assert "button:not(:disabled)" in text and "cursor:pointer" in text, (
            "the buttons keep the arrow"
        )
        assert "cursor:not-allowed" in text and "button:disabled" in text, (
            "a disabled button looks as clickable as the others"
        )


@case
def the_console_asks_for_nothing_it_did_not_ship():
    """Nothing the page loads comes from anywhere but this machine.

    The console is served by `http.server` on loopback, and a page that reached
    for a library on a CDN would be a console that looks broken on a train and
    tells somebody else when you opened it. React and shadcn/ui change nothing
    here: they are compiled into the bundle beside the page, not fetched.
    """
    # An `xmlns` is a name, not an address; what is looked for here is the
    # shapes that actually make the browser open a socket.
    reaches = (
        'src="http',
        "src='http",
        'href="http',
        "href='http",
        "url(http",
        "url('http",
        'url("http',
        "@import",
        "//unpkg",
        "//cdn",
    )
    for path in _shipped():
        text = path.read_text(encoding="utf-8", errors="replace")
        for shape in reaches:
            assert shape not in text, f"{path.name} reaches off the machine: {shape}"


@case
def the_console_says_the_configuration_in_french_too():
    """Every sentence this module writes about a setting has a French entry.

    The settings page is the one place where what the console shows comes from
    Python: a label, the line of help under it, the section it sits in. They
    reach the browser in the words written here and are looked up in
    `frontend/src/lib/french.ts` by those very words — so a sentence reworded
    on this side and not on that one would quietly go back to English on a
    console somebody set to French.

    All but one: the head of a sub-type's column in the model table, «
    Feature », is the sub-type's own word, and a sub-type is never translated
    (see `SUBTYPES` in subtypes.py) — so it must have no entry at all.
    """
    dictionary = (FRONTEND / "src/lib/french.ts").read_text(encoding="utf-8")
    said = [words for group in web_settings.GROUPS for words in (group.title, group.blurb)]
    said += [words for fold in web_settings.FOLDS.values() for words in fold]
    for section in web_settings.SECTIONS:
        said += [section.title, section.blurb]
        for field in section.fields:
            said += [field.label, field.help, field.after, field.unit, field.placeholder]
            said += [label for _, label in field.options]
            if field.grid == "subtype":
                assert f'"{field.short}":' not in dictionary, f"“{field.short}” is translated"
            else:
                said.append(field.short)
    for sentence in said:
        # As a key, not anywhere in the file: "Check the board every" is
        # in "Check the board every (seconds)", which translates nothing of it.
        keyed = f'"{sentence}":' in dictionary or re.search(
            rf"^\s*{re.escape(sentence)}:", dictionary, re.MULTILINE
        )
        assert not sentence or keyed, f"nothing translates “{sentence}” — add it to french.ts"


@case
def the_console_offers_the_two_languages_it_has():
    """The settings carry the switch, and the browser is asked before you are.

    It sat at the right edge of the bar, on every page, which is a lot of room
    for a thing somebody changes once. A language is a setting: it is drawn on
    the settings page, in the section that is about this console — even though
    it is the browser's own and never reaches `config.toml`.

    Read from the React source rather than from the bundle: the bundle is
    minified, and what is being checked here is a decision, not a symbol.
    """
    i18n = (FRONTEND / "src/lib/i18n.ts").read_text(encoding="utf-8")
    assert '"en"' in i18n and '"fr"' in i18n, "the console no longer offers both"
    assert "navigator.languages" in i18n, "the browser's own languages are not read"
    assert "resolvedOptions().timeZone" in i18n, "the time zone no longer answers for it"
    settings = (FRONTEND / "src/components/console/settings-page.tsx").read_text(encoding="utf-8")
    assert "LanguagePicker" in settings, "the settings have nowhere to change the language"


@case
def the_version_is_rewritten_where_the_product_reads_it():
    """`__version__` is what --version and the console header print.

    The rewrite is a regular expression over the real file, so this checks it
    against the real file's shape rather than against a fixture that agrees
    with it by construction.
    """
    with tempfile.TemporaryDirectory() as directory:
        init = Path(directory) / "__init__.py"
        init.write_text(release.INIT.read_text(encoding="utf-8"), encoding="utf-8")
        release.write_version("9.9.9", init)
        assert release.read_version(init) == "9.9.9"
        assert '__version__ = "9.9.9"' in init.read_text(encoding="utf-8")


@case
def the_project_file_says_the_version_the_product_says():
    """`pyproject.toml` must name a version, and it is a copy of `__version__`.

    `bump` writes both, against the real file's shape — the first `version =`
    of the file, never `requires-python` nor a dependency's — and the tree as
    committed agrees, or `check` would refuse the tag.
    """
    assert release.read_project_version() == release.read_version(), "pyproject.toml lags"
    with tempfile.TemporaryDirectory() as directory:
        pyproject = Path(directory) / "pyproject.toml"
        original = release.PYPROJECT.read_text(encoding="utf-8")
        pyproject.write_text(original, encoding="utf-8")
        release.write_project_version("9.9.9", pyproject)
        assert release.read_project_version(pyproject) == "9.9.9"
        rewritten = pyproject.read_text(encoding="utf-8")
        assert (
            rewritten.replace('version = "9.9.9"', f'version = "{release.read_version()}"', 1)
            == original
        )
