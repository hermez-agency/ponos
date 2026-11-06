"""`browser.py`: which browser a ticket acts in, the guard of a login, the profiles, the live view."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from support import _config, case

from ponos import browser, project_settings, prompt, session, vault_store
from ponos.web import app as web_app


@case
def a_login_is_typed_on_its_own_site_and_its_subdomains_only() -> None:
    entry = "https://dokploy.cardona.digital/login"
    assert browser.same_site("https://dokploy.cardona.digital/dashboard", entry)
    assert browser.same_site("https://eu.dokploy.cardona.digital/", entry), "a subdomain"
    assert browser.same_site("dokploy.cardona.digital", entry), "an address without its scheme"
    assert not browser.same_site("https://cardona.digital/", entry), "not the parent"
    assert not browser.same_site("https://dokploy.cardona.digital.evil.io/", entry)
    assert not browser.same_site("https://evil-dokploy.cardona.digital.io/", entry)
    assert not browser.same_site("https://dokploy.cardona.digital/", ""), "no address, no site"
    assert not browser.same_site("not a url at all", entry)


@case
def a_ticket_names_its_browser_over_its_project_over_the_file(state_home: Path) -> None:
    config = _config("")
    assert config.browser.default == "ponos" and config.browser.headless
    assert browser.named("Ouvre Dokploy.\nNavigateur : Chrome\n") == "chrome"
    assert browser.named("- **Browser:** Ponos") == "ponos"
    assert browser.named("Le navigateur chrome est lent.") == "", "a sentence names nothing"
    project = "0123456789abcdef0123456789abcdef"
    assert browser.chosen(config, project) == "ponos"
    project_settings.set_browser(project, "Brevo", "chrome")
    assert project_settings.browser(project) == "chrome"
    assert browser.chosen(config, project) == "chrome", "the project's own word"
    assert browser.chosen(config, project, "browser: ponos") == "ponos", "the ticket's, over it"
    project_settings.set_browser(project, "Brevo", None)
    assert browser.chosen(_config('[browser]\ndefault = "chrome"\n'), project) == "chrome"


@case
def a_profile_keeps_what_every_session_left_and_forgets_on_reset(state_home: Path) -> None:
    def cookie(name: str, domain: str, value: str) -> dict[str, object]:
        return {"name": name, "domain": domain, "path": "/", "value": value, "expires": -1}

    assert browser.load("Brevo") is None and browser.profiles() == []
    browser.save("Brevo", {"cookies": [cookie("sid", ".app.brevo.com", "one")], "origins": []})
    browser.save("Brevo", {"cookies": [cookie("sid", "dokploy.io", "two")], "origins": []})
    browser.save("Brevo", {"cookies": [cookie("sid", ".app.brevo.com", "three")], "origins": []})
    state = browser.load("Brevo")
    assert state is not None
    assert sorted(c["value"] for c in state["cookies"]) == ["three", "two"], state
    assert browser.sites(state) == ["app.brevo.com", "dokploy.io"]
    # Signed out by a session: the cookie it no longer has goes from the profile too.
    browser.save("Brevo", {"cookies": [], "origins": []}, {"sid|dokploy.io|/"})
    assert browser.sites(browser.load("Brevo")) == ["app.brevo.com"]
    expired = cookie("old", "gone.io", "x")
    expired["expires"] = time.time() - 60
    browser.save("Brevo", {"cookies": [expired], "origins": []})
    assert browser.sites(browser.load("Brevo")) == ["app.brevo.com"], (
        "an expired cookie signs nothing in"
    )

    target = browser.profile_path("Brevo")
    assert target.stat().st_mode & 0o777 == 0o600, oct(target.stat().st_mode)
    assert target.parent.stat().st_mode & 0o777 == 0o700
    assert [profile["slug"] for profile in browser.profiles()] == ["brevo"]
    assert browser.reset("Brevo") and browser.load("Brevo") is None
    assert not browser.reset("Brevo"), "nothing to forget the second time"


@case
def a_session_is_given_ponos_browser_instead_of_claude_in_chrome(state_home: Path) -> None:
    environment = browser.server_environment(
        project="Brevo",
        ticket="t1",
        session="s1",
        headless=True,
        logins={"BREVO": "https://app.brevo.com/login"},
        downloads=state_home,
    )
    written = browser.mcp_config(state_home / "s1.mcp.json", environment)
    server = json.loads(written.read_text())["mcpServers"]["ponos-browser"]
    assert server["args"] == ["-m", "ponos.browser_server"]
    assert json.loads(server["env"]["PONOS_BROWSER_LOGINS"]) == {
        "BREVO": "https://app.brevo.com/login"
    }
    assert written.stat().st_mode & 0o777 == 0o600

    command = session._command(
        "claude",
        "s1",
        resume=False,
        permission_mode="bypassPermissions",
        model="",
        max_budget_usd=0,
        chrome=False,
        mcp_config=written,
    )
    assert "--chrome" not in command and command[command.index("--mcp-config") + 1] == str(written)
    usual = session._command(
        "claude",
        "s1",
        resume=False,
        permission_mode="bypassPermissions",
        model="",
        max_budget_usd=0,
    )
    assert "--chrome" in usual and "--mcp-config" not in usual, "every other session as before"


@case
def the_prompt_names_the_logins_and_never_their_values() -> None:
    said = prompt.held_browser({"BREVO": "https://app.brevo.com/login", "OVH": ""})
    assert "`browser_login`" in said and "`BREVO` — app.brevo.com" in said, said
    assert "`OVH` — no site address yet" in said
    assert "CATEGORY: manual" in said, "a second factor is a stop"
    assert "No login of the vault is granted" in prompt.held_browser({})


@case
def a_login_carries_its_site_and_its_sign_ins_are_in_the_journal(vault_home: Path) -> None:
    made = vault_store.create(
        "BREVO",
        "login",
        {"user": "ada@hermez.dev", "password": "hunter2-hunter2"},
        ["Brevo"],
        url="app.brevo.com/login",
    )
    assert made["url"] == "https://app.brevo.com/login", "an address without its scheme is https"
    vault_store.create("OTHER", "login", {"user": "x" * 8, "password": "y" * 8}, ["Leadz"])
    vault_store.create("TOKEN", "token", {"value": "z" * 16}, ["Brevo"])
    assert vault_store.logins("Brevo") == {"BREVO": "https://app.brevo.com/login"}
    assert vault_store.logins("brevo") == vault_store.logins("Brevo"), "a project by its name"
    assert vault_store.logins("Leadz") == {"OTHER": ""}
    try:
        vault_store.change("BREVO", url="ftp://nowhere")
    except vault_store.Refused as error:
        assert error.field == "url"
    else:
        raise AssertionError("an address that is no site is refused")
    assert vault_store.change("BREVO", url="")["url"] == ""

    vault_store.signed_in("BREVO", "t1", "Brevo", vault_store.SIGNED_IN)
    vault_store.signed_in("BREVO", "t2", "Brevo", vault_store.SECOND_FACTOR)
    actions = [(moment["action"], moment["ticket"]) for moment in vault_store.history(made["id"])]
    assert actions[:2] == [("login-second-factor", "t2"), ("login", "t1")], actions
    try:
        vault_store.signed_in("BREVO", "t3", "Brevo", "maybe")
    except ValueError:
        pass
    else:
        raise AssertionError("a sign-in ends in one of four ways")


@case
def a_vault_written_before_the_url_is_read_and_given_one(vault_home: Path) -> None:
    import sqlite3

    vault_store.create("OLD", "login", {"user": "x" * 8, "password": "y" * 8}, ["Brevo"])
    with sqlite3.connect(vault_store.path()) as connection:
        connection.execute("ALTER TABLE entries DROP COLUMN url")
    assert vault_store.logins("Brevo") == {"OLD": ""}
    assert vault_store.change("OLD", url="https://old.example")["url"] == "https://old.example"


@case
def the_live_view_lists_running_browsers_and_hands_them_the_console_actions(
    state_home: Path,
) -> None:
    folder = browser.live_dir()
    folder.mkdir(parents=True)
    (folder / "s1.json").write_text(json.dumps({"project": "Brevo", "pid": os.getpid()}))
    (folder / "gone.json").write_text(json.dumps({"project": "Brevo", "pid": 0}))
    (folder / "s1.png").write_bytes(b"\x89PNG")
    assert [item["id"] for item in browser.live()] == ["s1"], (
        "a browser whose process is gone is not"
    )
    shown = browser.screen("s1")
    assert shown is not None and (folder / "s1.watch").exists(), "somebody is looking"
    assert browser.screen("../s1") is None or browser.screen("../s1") == shown
    browser.send("s1", {"action": "type", "text": "123456"})
    browser.send("s1", {"action": "press", "key": "Enter"})
    lines = (folder / "s1.in").read_text().splitlines()
    assert [json.loads(line)["action"] for line in lines] == ["type", "press"]
    for wrong, error in (({"action": "eval"}, ValueError), ({"action": "close"}, LookupError)):
        try:
            browser.send("nobody" if error is LookupError else "s1", wrong)
        except error:
            continue
        raise AssertionError(f"{wrong} should be refused")


@case
def the_browser_and_its_profiles_are_an_admins() -> None:
    assert web_app.needed("GET", "/api/browser") == "admin", "the live view shows dashboards"
    assert web_app.needed("POST", "/api/browser/reset") == "admin"
    assert web_app.needed("POST", "/api/browser/live/s1") == "admin"


@case
def doctor_says_whether_ponos_browser_can_start_and_how_to_install_it() -> None:
    from ponos.health import machine

    french = (Path(__file__).resolve().parents[1] / "frontend/src/lib/health-french.ts").read_text()
    available, chromium = browser.available, browser.chromium
    try:
        for installed, found, state in (
            (False, "", "warn"),
            (True, "", "warn"),
            (True, "/x", "ok"),
        ):
            browser.available = lambda installed=installed: installed  # type: ignore[misc]
            browser.chromium = lambda found=found: found  # type: ignore[misc]
            (check,) = machine._browser(_config(""))
            (quiet,) = machine._browser(_config('[browser]\ndefault = "chrome"\n'))
            assert check.code == "machine.browser" and check.state == state, check
            assert quiet.state in ("info", "ok"), quiet
            if state == "warn":
                assert "playwright install chromium" in check.text(check.steps[0]), check.steps
            for said in (check, quiet):
                for sentence in (said.title, said.said, said.cause, *said.steps):
                    assert not sentence or f'"{sentence}"' in french, (
                        f"nothing translates “{sentence}” — add it to health-french.ts"
                    )
    finally:
        browser.available, browser.chromium = available, chromium
