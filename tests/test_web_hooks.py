"""`triggers.py` et `web/hooks.py` : une URL webhook crée un ticket."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from support import _board, _ideas_api, case

from ponos import db, store, tailscale, triggers

SENTRY: dict[str, Any] = {
    "action": "created",
    "installation": {"uuid": "abc"},
    "data": {
        "issue": {
            "id": "4501",
            "title": "TypeError: x is undefined",
            "culprit": "app/checkout.py in pay",
            "level": "error",
            "web_url": "https://sentry.io/organizations/acme/issues/4501/",
            "project": {"slug": "shop"},
        }
    },
}

GITHUB: dict[str, Any] = {
    "action": "completed",
    "workflow_run": {
        "id": 99,
        "run_attempt": 1,
        "name": "CI",
        "conclusion": "failure",
        "head_branch": "main",
        "head_sha": "abc123",
        "html_url": "https://github.com/acme/shop/actions/runs/99",
        "head_commit": {"message": "Casse tout"},
    },
    "repository": {"full_name": "acme/shop", "default_branch": "main"},
}


def _post(port: int, path: str, body: Any, funnel: bool = False) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if funnel:
        headers[tailscale.FUNNEL_HEADER] = "?1"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return int(response.status), json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


@case
def a_template_takes_its_values_from_the_json_and_leaves_the_rest_empty() -> None:
    assert triggers.render("{{ event.a.b }} / {{ c }}", {"a": {"b": "x"}, "c": 3}) == "x / 3"
    assert triggers.render("[{{ event.nope }}]", {}) == "[]"
    assert triggers.render("{{ event.a.0.n | event.b }}", {"a": [{"n": "first"}]}) == "first"
    assert triggers.render("{{ event.a | event.b }}", {"b": "fallback"}) == "fallback"
    # What the JSON holds is never read as a template.
    assert triggers.render("{{ event.a }}", {"a": "{{ event.b }}", "b": "no"}) == "{{ event.b }}"
    assert triggers.tidy("- Lien : \n- Où : ici\n\n\n\nfin") == "- Où : ici\n\nfin"


@case
def the_presets_keep_only_the_events_they_are_made_for() -> None:
    assert triggers.accepts("sentry", SENTRY)
    assert not triggers.accepts("sentry", {**SENTRY, "action": "resolved"})
    assert triggers.accepts("github", GITHUB)
    assert not triggers.accepts("github", {"zen": "ping"})
    run = {**GITHUB["workflow_run"], "head_branch": "feature"}
    assert not triggers.accepts("github", {**GITHUB, "workflow_run": run})
    run = {**GITHUB["workflow_run"], "conclusion": "success"}
    assert not triggers.accepts("github", {**GITHUB, "workflow_run": run})


@case
def a_key_is_kept_as_its_digest_and_a_revoked_one_is_found_no_more(state_home: Path) -> None:
    hook, key = triggers.create({"name": "Sentry", "preset": "sentry", "project": "p1"})
    assert hook.status == "draft" and hook.kind == "code" and hook.per_hour == 10
    assert triggers.find(key) == hook and triggers.find("x" * 32) is None
    stored = db.connect().execute("SELECT digest FROM hooks").fetchone()[0]
    assert stored == triggers.digest(key) and key not in stored
    assert triggers.mask(f"/api/hooks/{key}") == "/api/hooks/…"
    assert triggers.revoke(hook.id) and not triggers.revoke(hook.id)
    assert triggers.find(key) is None
    assert [item.revoked for item in triggers.listing()] == [True]
    for bad in ({"name": ""}, {"name": "x", "preset": "nope"}, {"name": "x", "status": "done"}):
        try:
            triggers.create(bad)
        except triggers.Refused:
            continue
        raise AssertionError(f"{bad} should have been refused")


@case
def a_sentry_event_makes_one_draft_with_its_link_and_the_second_delivery_makes_none(
    state_home: Path,
) -> None:
    from ponos.web import app as web_app

    with _board() as board:
        project = board.create_row("projects", "Boutique", {"Repository": "acme/shop"})
        api = _ideas_api(board)
        api._config.web.token = "tok"
        console = web_app.Console(("127.0.0.1", 0), api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        port = console.server_address[1]
        try:
            created = api.create_trigger(
                {"name": "Sentry", "preset": "sentry", "project": project, "priority": 80}
            )
            key = created["key"]
            path = f"/api/hooks/{key}"
            status, said = _post(port, path, SENTRY)
            assert status == 201, said
            page = board.page(said["ticket"])
            assert page.title == "[Sentry] TypeError: x is undefined"
            assert store.read(page, "Project") == [project]
            assert store.read(page, "statut") == "draft", "a draft by default"
            text = board.blocks_text(page.id)
            assert "https://sentry.io/organizations/acme/issues/4501/" in text
            assert "app/checkout.py in pay" in text

            again, repeated = _post(port, path, SENTRY)
            assert again == 200 and repeated == {"duplicate": True, "ticket": said["ticket"]}
            assert len(board.query("tickets")) == 1

            other, _ = _post(
                port, path, {**SENTRY, "data": {"issue": {**SENTRY["data"]["issue"], "id": "9"}}}
            )
            assert other == 201 and len(board.query("tickets")) == 2

            assert _post(port, path, {**SENTRY, "action": "resolved"}) == (200, {"ignored": True})
            assert len(board.query("tickets")) == 2

            # Through Funnel the route is reachable, and the key still applies.
            assert _post(port, path, SENTRY, funnel=True)[0] == 200

            hook_id = created["hook"]["id"]
            assert api.revoke_trigger(hook_id) == {"id": hook_id}
            assert _post(port, path, SENTRY)[0] == 404, "a revoked key is a missing route"
            # A wrong key is a miss like any other, and waited for by its address.
            assert _post(port, "/api/hooks/short", SENTRY)[0] == 429
        finally:
            console.shutdown()
            console.server_close()


@case
def a_key_makes_no_more_tickets_than_its_ceiling_an_hour(state_home: Path) -> None:
    with _board() as board:
        project = board.create_row("projects", "Boutique", {"Repository": "acme/shop"})
        api = _ideas_api(board)
        created = api.create_trigger(
            {"name": "CI", "preset": "github", "project": project, "per_hour": 2, "status": "ready"}
        )
        key = created["key"]
        for number, expected in ((1, 201), (2, 201), (3, 429)):
            run = {**GITHUB["workflow_run"], "id": number}
            status, said, headers = api.receive(
                key, json.dumps({**GITHUB, "workflow_run": run}).encode()
            )
            assert status == expected, (number, said)
        assert int(headers["Retry-After"]) > 0
        assert len(board.query("tickets")) == 2
        # The refused one was not written down: it passes once there is room.
        again = api.receive(
            key,
            json.dumps({**GITHUB, "workflow_run": {**GITHUB["workflow_run"], "id": 3}}).encode(),
        )
        assert again[0] == 429
        ticket = board.query("tickets")[0]
        assert ticket.title == "[CI] CI en échec sur main"
        assert store.read(ticket, "statut"), "ready was asked for"


@case
def a_body_without_an_identifier_counts_once_by_its_digest(state_home: Path) -> None:
    with _board() as board:
        project = board.create_row("projects", "Boutique", {"Repository": "acme/shop"})
        api = _ideas_api(board)
        key = api.create_trigger({"name": "Maison", "project": project})["key"]
        body = json.dumps({"title": "Disque plein", "url": "https://x.test/1"}).encode()
        assert api.receive(key, body)[0] == 201
        assert api.receive(key, body)[0] == 200
        assert api.receive(key, b"not json")[0] == 400
        assert [page.title for page in board.query("tickets")] == ["Disque plein"]
