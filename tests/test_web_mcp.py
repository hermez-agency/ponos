"""`web/mcp.py`: the MCP server, its keys, and the MCP tab."""

from __future__ import annotations

import contextlib
import io
import json
import threading
import time
from email.message import Message

from support import _board, _ideas_api, _time_passes, case

from ponos import config as C
from ponos import db, state, store, voice
from ponos import http as http_module
from ponos.__main__ import main as cli_main

# -- the MCP server ----------------------------------------------------------


def _mcp_call(api, grant, name: str, **arguments) -> dict:
    from ponos.web import mcp as web_mcp

    answer = web_mcp.handle(
        api,
        grant,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    return answer["result"]


@case
def an_mcp_client_lists_what_waits_creates_a_task_and_answers_a_question(state_home):
    """The three gestures the connector exists for, on a board made of files.

    Nothing in what comes back names a page, a database or a property: a task,
    a project, a status. A task created goes through `create_ticket`, an answer
    is the comment the console's discussion writes, under the question — and
    every write is in the journal, with its client.
    """
    from ponos.web import mcp as web_mcp
    from ponos.web import oauth as web_oauth

    with _board() as board:
        project = board.create_row("projects", "Usine", {"Repository": "user/usine"})
        settings = C.Notion()
        blocked = board.create_row(
            "tickets", "Choisir l'hébergeur", {"Status": settings.state("blocked")}
        )
        board.update("tickets", blocked, {"Project": [project]})
        board.comment(blocked, f"{voice.MARKS['blocked']} Bloqué.\nQuestion : Dokploy ou Vercel ?")
        board.create_row("tickets", "Autre chose", {"Status": settings.state("ready")})
        api = _ideas_api(board)
        grant = web_oauth.Grant(client="c-1", name="claude.ai", scopes=frozenset({"read", "write"}))

        projects = _mcp_call(api, grant, "list_projects")["structuredContent"]["projects"]
        assert [(item["name"], item["repository"]) for item in projects] == [
            ("Usine", "user/usine")
        ]

        waiting = _mcp_call(api, grant, "list_tasks", waiting_for_you=True)["structuredContent"]
        assert [task["title"] for task in waiting["tasks"]] == ["Choisir l'hébergeur"]
        task = waiting["tasks"][0]
        assert (
            task["project"] == "Usine" and task["status"] == "blocked" and task["waiting_for_you"]
        )
        assert "url" not in task, "a task is not a Notion page"

        detail = _mcp_call(api, grant, "get_task", task=task["short"])["structuredContent"]
        assert "Dokploy ou Vercel" in detail["question"]
        assert detail["conversation"][-1]["from"] == "ponos"

        created = _mcp_call(
            api,
            grant,
            "create_task",
            title="Brancher le domaine",
            description="Sur Dokploy.",
            project="usine",
            type="code",
            priority=80,
        )
        assert not created["isError"], created
        made = board.page(created["structuredContent"]["id"])
        assert made.title == "Brancher le domaine"
        assert store.read(made, "Project") == [project]
        assert not store.read(made, "Status"), "a draft unless ready is asked for"
        assert "Sur Dokploy." in board.blocks_text(made.id)

        unknown = _mcp_call(api, grant, "create_task", title="X", project="Nulle part")
        assert unknown["isError"] and "Usine" in unknown["content"][0]["text"]

        refused = _mcp_call(
            api, grant, "answer_question", task=created["structuredContent"]["id"], answer="oui"
        )
        assert refused["isError"], "only a blocked task is answered"

        answered = _mcp_call(
            api, grant, "answer_question", task=task["id"], answer="Dokploy", ready=True
        )
        assert not answered["isError"], answered
        said = board.comments(blocked)[-1].text
        assert said.endswith("Dokploy") and said != "Dokploy", "relayed, as the console's answer is"
        assert api.outbox.marks()[task["id"]].column == "ready"

        journal_lines = web_mcp.calls()
        assert [line["tool"] for line in journal_lines] == [
            "answer_question",
            "answer_question",
            "create_task",
            "create_task",
        ]
        assert journal_lines[0]["outcome"] == "ok" and journal_lines[0]["name"] == "claude.ai"
        assert journal_lines[1]["outcome"].startswith("refused")
        assert all(line["client"] == "c-1" and line["at"] for line in journal_lines)


# -- the goals ----------------------------------------------------------------


@case
def an_mcp_client_lists_the_goals_and_creates_a_task_for_one(state_home):
    """A goal named as a person names it, in any case — and a task that serves it.

    How far a goal has gone is the console's count: done, out of every task but
    those given up. A goal nobody has is refused with the ones there are.
    """
    from ponos.web import oauth as web_oauth

    with _board() as board:
        project = board.create_row("projects", "Usine", {"Repository": "user/usine"})
        launch = board.create_row(
            "goals",
            "Lancer la v1",
            {"Statut": "actif", "Échéance": "2026-12-31", "Projets": [project]},
        )
        board.create_row("goals", "Ranger", {"Statut": "atteint"})
        settings = C.Notion()
        for title, column in (("Fait", "done"), ("En cours", "running"), ("Laissé", "cancelled")):
            ticket = board.create_row("tickets", title, {"Status": settings.state(column)})
            board.update("tickets", ticket, {"Objectif": [launch]})
        api = _ideas_api(board)
        grant = web_oauth.Grant(client="c-1", name="claude.ai", scopes=frozenset({"read", "write"}))

        listed = _mcp_call(api, grant, "list_goals")["structuredContent"]
        goals = {goal["name"]: goal for goal in listed["goals"]}
        assert set(goals) == {"Lancer la v1", "Ranger"}, listed
        goal = goals["Lancer la v1"]
        assert goal["active"] and goal["status"] == "actif" and goal["due"] == "2026-12-31"
        assert goal["projects"] == ["Usine"]
        assert (goal["progress"]["done"], goal["progress"]["total"]) == (1, 2), goal
        assert not goals["Ranger"]["active"] and goals["Ranger"]["progress"]["total"] == 0

        tasks = _mcp_call(api, grant, "list_tasks")["structuredContent"]["tasks"]
        assert {task["title"]: task["goal"] for task in tasks}["Fait"] == "Lancer la v1"

        created = _mcp_call(
            api, grant, "create_task", title="Brancher le domaine", goal="lancer LA V1"
        )
        assert not created["isError"], created
        made = created["structuredContent"]
        assert made["goal"] == "Lancer la v1"
        assert store.read(board.page(made["id"]), "Objectif") == [goal["id"]]
        api._goals_at = 0.0  # the index the cards are named from, read again
        detail = _mcp_call(api, grant, "get_task", task=made["id"])["structuredContent"]
        assert detail["goal"] == "Lancer la v1", detail

        unknown = _mcp_call(api, grant, "create_task", title="X", goal="Conquérir le monde")
        assert unknown["isError"], unknown
        said = unknown["content"][0]["text"]
        assert "Conquérir le monde" in said and "Lancer la v1" in said
        assert "X" not in [task.title for task in board.query("tickets")], "nothing created"


# -- deciding on a card that waits on you -------------------------------------


@case
def an_mcp_client_lists_the_solutions_of_a_blocked_task_and_applies_one(state_home):
    from ponos.web import oauth as web_oauth

    settings = C.Notion()
    with _board() as board:
        blocked = board.create_row(
            "tickets", "Install Tailscale", {"Status": settings.state("blocked")}
        )
        board.comment(
            blocked,
            f"{voice.MARKS['blocked']} Bloqué\nAction manuelle requise : il faut l'installer à la main\nC'est fait ?",
        )
        api = _ideas_api(board)
        grant = web_oauth.Grant(client="c-1", name="claude.ai", scopes=frozenset({"read", "write"}))
        listed = _mcp_call(api, grant, "list_solutions", task=blocked)["structuredContent"]
        assert listed["category"] == "manual" and listed["declared"]
        assert listed["reason"] == "il faut l'installer à la main"
        assert listed["solutions"][0]["key"] == "answer"
        applied = _mcp_call(api, grant, "apply_solution", task=blocked, solution="done-retry")
        assert not applied["isError"], applied
        assert board.comments(blocked)[-1].text.startswith(
            ("Répondu depuis MCP.", "Answered from MCP.")
        )
        assert api.outbox.marks()[blocked].column == "ready"
        wrong = _mcp_call(api, grant, "apply_solution", task=blocked, solution="validate")
        assert wrong["isError"]


@case
def an_mcp_client_sorts_ideas_without_deleting_any(state_home):
    from ponos.web import oauth as web_oauth

    with _board() as board:
        project = board.create_row("projects", "Usine", {})
        api = _ideas_api(board)
        grant = web_oauth.Grant(
            client="c-1", name="Claude Code", scopes=frozenset({"read", "write"})
        )
        idea = _mcp_call(api, grant, "create_idea", title="Un mode sombre", project="Usine")[
            "structuredContent"
        ]
        assert idea["status"] == "proposed" and idea["kind"] == "ticket"
        assert _mcp_call(
            api, grant, "create_idea", title="Un club", project="Usine", kind="project"
        )["isError"]
        sorted_one = _mcp_call(
            api,
            grant,
            "create_idea",
            title="Un audit des jetons",
            project="Usine",
            category="security",
        )["structuredContent"]
        assert sorted_one["category"] == "security" and idea["category"] == ""
        assert _mcp_call(
            api, grant, "create_idea", title="Un tag", project="Usine", category="marketing"
        )["isError"]
        listed = _mcp_call(api, grant, "list_ideas", project="Usine")["structuredContent"]["ideas"]
        assert [item["title"] for item in listed] == ["Un mode sombre", "Un audit des jetons"]
        assert _mcp_call(api, grant, "list_ideas")["structuredContent"]["ideas"] == [], (
            "the workspace's are apart"
        )

        thrown = _mcp_call(api, grant, "set_idea_state", idea=idea["id"], state="discard")[
            "structuredContent"
        ]
        assert thrown["status"] == "discarded"
        back = _mcp_call(api, grant, "set_idea_state", idea=idea["id"], state="new")[
            "structuredContent"
        ]
        assert back["status"] == "proposed"
        kept = _mcp_call(api, grant, "set_idea_state", idea=idea["id"], state="keep")[
            "structuredContent"
        ]
        assert kept["status"] == "kept" and not kept["task"], "keeping writes nothing on the board"
        made = _mcp_call(api, grant, "set_idea_state", idea=idea["id"], state="ticket")[
            "structuredContent"
        ]
        assert made["status"] == "ticket" and made["task"]
        ticket = board.page(made["task"])
        assert ticket.title == "Un mode sombre" and store.read(ticket, "Project") == [project]


@case
def a_read_only_mcp_client_sees_and_can_call_no_tool_that_writes(state_home):
    from ponos.web import mcp as web_mcp
    from ponos.web import oauth as web_oauth

    with _board() as board:
        api = _ideas_api(board)
        reader = web_oauth.Grant(client="c-2", name="lecteur", scopes=frozenset({"read"}))
        listed = web_mcp.handle(api, reader, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {tool["name"] for tool in listed["result"]["tools"]}
        assert names == {
            "whoami",
            "list_projects",
            "list_tasks",
            "get_task",
            "runner_status",
            "list_ideas",
            "list_goals",
            "list_solutions",
        }
        assert all(tool["annotations"]["readOnlyHint"] for tool in listed["result"]["tools"])
        me = _mcp_call(api, reader, "whoami")["structuredContent"]
        assert me["client"] == "lecteur" and me["access"] == "lecture seule", me
        refused = _mcp_call(api, reader, "create_task", title="Rien")
        assert refused["isError"] and "lecture" in refused["content"][0]["text"]
        assert api.board()["tickets"] == [], "nothing was written"
        assert web_mcp.calls()[0]["outcome"].startswith("refused"), (
            "a refused write is journalled too"
        )
        state.record({"id": "x", "status": "done", "project": "Usine", "cost_usd": 1.25})
        state.record({"id": "y", "status": "done", "cost_usd": 0.5})
        # Today's figure is what the sessions were written down as costing as
        # they ended, the history's is the tickets': a run writes both.
        state.spend(1.25, "x")
        state.spend(0.5, "y")
        status = _mcp_call(api, reader, "runner_status", days=7)["structuredContent"]
        assert status["spend"]["period_usd"] == 1.75 and status["spend"]["today_usd"] == 1.75
        assert [item["project"] for item in status["spend"]["by_project"]] == [
            "Usine",
            "(sans projet)",
        ]
        assert status["run_in_progress"] is False and status["sessions"] == []


@case
def no_mcp_tool_starts_a_run_runs_a_command_or_deletes_anything():
    """The whole list, written down: a tool added is a decision, not a drift."""
    from ponos.web import mcp as web_mcp

    names = [tool["name"] for tool in web_mcp.TOOLS]
    assert set(names) == set(web_mcp.HANDLERS)
    assert names == [
        "whoami",
        "list_projects",
        "list_tasks",
        "get_task",
        "runner_status",
        "list_ideas",
        "list_goals",
        "create_task",
        "answer_question",
        "list_solutions",
        "apply_solution",
        "create_idea",
        "set_idea_state",
    ]
    writes = [tool["name"] for tool in web_mcp.TOOLS if tool["scope"] == "write"]
    assert writes == [
        "create_task",
        "answer_question",
        "apply_solution",
        "create_idea",
        "set_idea_state",
    ]
    status = next(tool for tool in web_mcp.TOOLS if tool["name"] == "create_task")
    assert status["inputSchema"]["properties"]["status"]["enum"] == ["draft", "ready"]
    for tool in web_mcp.TOOLS:
        assert len(tool["description"]) > 80, f"{tool['name']}: a description Claude can choose by"
        assert tool["title"] and len(tool["title"]) < 40, (
            f"{tool['name']}: a title a person reads in a list"
        )
    titles = [tool["title"] for tool in web_mcp.TOOLS]
    assert len(set(titles)) == len(titles), "two tools Claude would show under one name"


@case
def the_mcp_connector_says_its_name_and_who_holds_the_key(state_home):
    """What Claude shows once the address is pasted, and the first call to try.

    The icon is served from the site, never from the console: Claude fetches
    it without a key, and a console's files are behind its sign-in.
    """
    from ponos.web import mcp as web_mcp
    from ponos.web import oauth as web_oauth

    with _board() as board:
        board.create_row("projects", "Usine", {"Repository": "user/usine"})
        board.create_row("tickets", "Choisir l'hébergeur", {"Status": C.Notion().state("blocked")})
        api = _ideas_api(board)
        api._config.web.email = "moi@example.com"
        writer = web_oauth.Grant(
            client="c-1", name="claude.ai", scopes=frozenset({"read", "write"})
        )
        hello = web_mcp.handle(
            api,
            writer,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            },
        )["result"]["serverInfo"]
        assert (
            hello["name"] == "ponos"
            and hello["title"] == "Ponos"
            and hello["websiteUrl"] == "https://the-ponos.app"
        )
        assert hello["description"] and all(
            icon["src"].startswith("https://the-ponos.app/") for icon in hello["icons"]
        )
        answer = web_mcp.handle(
            api,
            writer,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "whoami", "arguments": {}},
            },
            "https://ponos.example",
        )["result"]
        me = answer["structuredContent"]
        assert not answer["isError"]
        assert me["console"] == "https://ponos.example" and me["email"] == "moi@example.com"
        assert me["client"] == "claude.ai" and me["access"] == "lecture et écriture"
        assert (
            me["projects"] == 1
            and me["waiting_for_you"] == 1
            and me["board"] == api.config.storage.mode
        )
        assert web_mcp.calls() == [], "reading who you are is no write"
        refused = _mcp_call(api, writer, "whoami", qui="moi")
        assert refused["isError"], "whoami takes no argument"


@case
def the_mcp_server_is_reached_through_oauth_with_pkce_and_its_own_keys(state_home):
    """Discovery, registration, consent, code, token, tools — over HTTP.

    The console's own token is not a key to `/mcp`; consent asks for it when
    the browser is signed out; write is granted only when ticked; a code is
    good once, and only with its verifier.
    """
    import base64
    import hashlib
    import urllib.error
    import urllib.request
    from urllib.parse import parse_qs, urlencode, urlparse

    from ponos.web import app as web_app
    from ponos.web import oauth as web_oauth

    class Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(Stay)

    with _board() as board:
        board.create_row("tickets", "Un ticket", {"Status": C.Notion().state("blocked")})
        api = _ideas_api(board)
        api._config.web.token = "tok"
        console = web_app.Console(("127.0.0.1", 0), api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{console.server_address[1]}"

        def ask(path, data=None, headers=None, method=None):
            request = urllib.request.Request(
                base + path, data=data, headers=headers or {}, method=method
            )
            try:
                with opener.open(request, timeout=5) as response:
                    return response.status, response.headers, response.read()
            except urllib.error.HTTPError as error:
                return error.code, error.headers, error.read()

        def rpc(token, method, params=None):
            body = json.dumps(
                {"jsonrpc": "2.0", "id": 7, "method": method, "params": params or {}}
            ).encode()
            return ask(
                "/mcp",
                body,
                {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )

        try:
            code, headers, _ = rpc("tok", "tools/list")
            assert code == 401, "the console's token opens the console, not the MCP server"
            assert "resource_metadata=" in headers["WWW-Authenticate"]
            # Any first contact gets the 401 that makes Claude offer "Connect", as Leadz answers it.
            code, headers, _ = ask("/mcp")
            assert code == 401 and headers["WWW-Authenticate"] == (
                f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource/mcp"'
            ), "a GET without a key: a 401, not a 405"
            resource = json.loads(ask("/.well-known/oauth-protected-resource/mcp")[2])
            assert resource["resource"] == f"{base}/mcp" and resource["scopes_supported"] == [
                "read",
                "write",
            ]
            server = json.loads(ask("/.well-known/oauth-authorization-server")[2])
            assert server["code_challenge_methods_supported"] == ["S256"]

            code, _, body = ask(
                "/oauth/register",
                json.dumps({"redirect_uris": ["http://evil.example/cb"]}).encode(),
                {"Content-Type": "application/json"},
            )
            assert code == 400, "a code is never sent in clear across a network"
            code, _, body = ask(
                "/oauth/register",
                json.dumps(
                    {
                        "client_name": "claude.ai",
                        "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
                    }
                ).encode(),
                {"Content-Type": "application/json"},
            )
            assert code == 201, body
            client_id = json.loads(body)["client_id"]

            verifier = "v" * 50
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .rstrip(b"=")
                .decode()
            )
            params = {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "read write",
                "state": "s-1",
            }
            code, _, page = ask("/oauth/authorize?" + urlencode(params))
            assert code == 200 and b"claude.ai" in page and b'name="token"' in page, (
                "signed out: the token is asked"
            )
            assert b'name="write"' in page

            code, _, _ = ask(
                "/oauth/authorize",
                urlencode({**params, "decision": "allow", "token": "nope"}).encode(),
                {"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert code == 401
            code, _, page = ask(
                "/oauth/authorize",
                urlencode({**params, "decision": "allow", "token": "tok"}).encode(),
                {"Content-Type": "application/x-www-form-urlencoded", "Origin": base},
            )
            assert code == 429 and b"too many attempts" in page, (
                "a wrong token is waited out, on this page too"
            )
            _time_passes(console, 1)
            code, _, _ = ask(
                "/oauth/authorize",
                urlencode({**params, "decision": "allow", "token": "tok"}).encode(),
                {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "http://evil.example",
                },
            )
            assert code == 403, "a consent posted from another page"

            # Write left unticked: read only.
            code, headers, _ = ask(
                "/oauth/authorize",
                urlencode({**params, "decision": "allow", "token": "tok"}).encode(),
                {"Content-Type": "application/x-www-form-urlencoded", "Origin": base},
            )
            assert code == 302, code
            back = urlparse(headers["Location"])
            assert back.netloc == "claude.ai"
            given = parse_qs(back.query)
            assert given["state"] == ["s-1"] and given["iss"] == [base]

            def exchange(**form):
                return ask(
                    "/oauth/token",
                    urlencode(form).encode(),
                    {"Content-Type": "application/x-www-form-urlencoded"},
                )

            code, _, body = exchange(
                grant_type="authorization_code",
                code=given["code"][0],
                client_id=client_id,
                redirect_uri=params["redirect_uri"],
                code_verifier="w" * 50,
            )
            assert code == 400 and json.loads(body)["error"] == "invalid_grant", (
                "the wrong verifier"
            )
            code, _, body = exchange(
                grant_type="authorization_code",
                code=given["code"][0],
                client_id=client_id,
                redirect_uri=params["redirect_uri"],
                code_verifier=verifier,
            )
            assert code == 400, "a code refused once is spent"

            code, headers, _ = ask(
                "/oauth/authorize",
                urlencode({**params, "decision": "allow", "token": "tok"}).encode(),
                {"Content-Type": "application/x-www-form-urlencoded", "Origin": base},
            )
            fresh = parse_qs(urlparse(headers["Location"]).query)["code"][0]
            code, _, body = exchange(
                grant_type="authorization_code",
                code=fresh,
                client_id=client_id,
                redirect_uri=params["redirect_uri"],
                code_verifier=verifier,
            )
            assert code == 200, body
            tokens = json.loads(body)
            assert tokens["scope"] == "read" and tokens["token_type"] == "Bearer"

            code, _, body = rpc(
                tokens["access_token"], "initialize", {"protocolVersion": "2025-06-18"}
            )
            assert code == 200 and json.loads(body)["result"]["protocolVersion"] == "2025-06-18"
            code, _, _ = ask(
                "/mcp",
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(),
                {"Authorization": f"Bearer {tokens['access_token']}"},
            )
            assert code == 202
            listed = json.loads(rpc(tokens["access_token"], "tools/list")[2])["result"]["tools"]
            assert "create_task" not in {tool["name"] for tool in listed}
            assert (
                ask("/mcp", headers={"Authorization": f"Bearer {tokens['access_token']}"})[0] == 405
            ), "no stream"
            # A client that names where it runs is not refused for it: the key is the lock.
            code, _, body = ask(
                "/mcp",
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 8,
                        "method": "tools/call",
                        "params": {"name": "whoami"},
                    }
                ).encode(),
                {
                    "Authorization": f"Bearer {tokens['access_token']}",
                    "Content-Type": "application/json",
                    "Origin": "https://claude.ai",
                },
            )
            assert code == 200, code
            me = json.loads(body)["result"]["structuredContent"]
            assert (
                me["console"] == base
                and me["client"] == "claude.ai"
                and me["access"] == "lecture seule"
            )
            answer = json.loads(
                rpc(
                    tokens["access_token"],
                    "tools/call",
                    {"name": "list_tasks", "arguments": {"waiting_for_you": True}},
                )[2]
            )
            assert [task["title"] for task in answer["result"]["structuredContent"]["tasks"]] == [
                "Un ticket"
            ]
            answer = json.loads(
                rpc(
                    tokens["access_token"],
                    "tools/call",
                    {"name": "create_task", "arguments": {"title": "Non"}},
                )[2]
            )
            assert answer["result"]["isError"], "read only cannot create"

            # A refresh turns over; the old one is spent.
            code, _, body = exchange(
                grant_type="refresh_token",
                refresh_token=tokens["refresh_token"],
                client_id=client_id,
            )
            assert code == 200 and json.loads(body)["scope"] == "read"
            code, _, _ = exchange(
                grant_type="refresh_token",
                refresh_token=tokens["refresh_token"],
                client_id=client_id,
            )
            assert code == 400

            # Write, ticked this time; then taken back.
            code, headers, _ = ask(
                "/oauth/authorize",
                urlencode({**params, "decision": "allow", "token": "tok", "write": "1"}).encode(),
                {"Content-Type": "application/x-www-form-urlencoded", "Origin": base},
            )
            writer = parse_qs(urlparse(headers["Location"]).query)["code"][0]
            code, _, body = exchange(
                grant_type="authorization_code",
                code=writer,
                client_id=client_id,
                redirect_uri=params["redirect_uri"],
                code_verifier=verifier,
            )
            assert json.loads(body)["scope"] == "read write"
            written = json.loads(body)["access_token"]
            listed = json.loads(rpc(written, "tools/list")[2])["result"]["tools"]
            assert "create_task" in {tool["name"] for tool in listed}
            assert web_oauth.revoke(client_id) >= 2
            assert rpc(written, "tools/list")[0] == 401, "revoked"

            # Refused: no redirect to an address the client did not register.
            code, headers, _ = ask(
                "/oauth/authorize?"
                + urlencode({**params, "redirect_uri": "https://evil.example/cb"})
            )
            assert code == 400 and "Location" not in headers
            code, headers, _ = ask(
                "/oauth/authorize?" + urlencode({**params, "code_challenge_method": "plain"})
            )
            assert code == 302 and "error=invalid_request" in headers["Location"]
        finally:
            console.shutdown()
            console.server_close()


@case
def the_mcp_metadata_names_the_public_address_behind_a_proxy_that_says_nothing(state_home):
    """`web.url`, as Leadz's DEFAULT_URI: a tunnel adds no X-Forwarded-Proto.

    Without it the addresses claude.ai reads would all be `http://`, and it
    refuses them; with it, Claude Code on this machine still reads the
    loopback address it typed.
    """
    import urllib.request

    from ponos.web import app as web_app

    with _board() as board:
        api = _ideas_api(board)
        api._config.web.token = "tok"
        api._config.web.host = "0.0.0.0"  # a wider bind: the Host check is the token's then
        api._config.web.url = "https://ponos.example"
        console = web_app.Console(("127.0.0.1", 0), api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        port = console.server_address[1]

        def metadata(host: str) -> dict:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/.well-known/oauth-protected-resource/mcp",
                headers={"Host": host},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read())

        try:
            outside = metadata("abc.lhr.life")
            assert outside["resource"] == "https://ponos.example/mcp", outside
            assert outside["authorization_servers"] == ["https://ponos.example"]
            here = metadata(f"127.0.0.1:{port}")
            assert here["resource"] == f"http://127.0.0.1:{port}/mcp", here
        finally:
            console.shutdown()
            console.server_close()


@case
def a_loopback_console_answers_the_name_web_url_gives_it_and_no_other(state_home):
    """`tailscale serve` relays to 127.0.0.1 and keeps the tailnet name as Host.

    That name is the one `web.url` says, exactly: not any `*.ts.net`, which
    another page could point at this machine as well as it could any domain.
    """
    import urllib.error
    import urllib.request

    from ponos.web import app as web_app

    with _board() as board:
        api = _ideas_api(board)
        api._config.web.token = "tok"
        console = web_app.Console(("127.0.0.1", 0), api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        port = console.server_address[1]

        def status(host: str) -> int:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/.well-known/oauth-protected-resource/mcp",
                headers={"Host": host},
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status
            except urllib.error.HTTPError as error:
                return error.code

        try:
            assert status("laptop.tail1234.ts.net") == 421, "no web.url: only this machine's names"
            assert status(f"127.0.0.1:{port}") == 200
            api._config.web.url = "https://laptop.tail1234.ts.net"
            assert status("laptop.tail1234.ts.net") == 200
            assert status("laptop.tail1234.ts.net:443") == 200
            assert status("other.tail1234.ts.net") == 421, "another machine of the same tailnet"
            assert status("evil.example") == 421
            assert status(f"127.0.0.1:{port}") == 200
        finally:
            console.shutdown()
            console.server_close()


@case
def a_local_mcp_token_is_drawn_once_and_kept_as_a_digest(state_home):
    from ponos.web import oauth as web_oauth

    identifier, token = web_oauth.local("Claude Code", write=False)
    grant = web_oauth.check(token)
    assert grant is not None and grant.scope == "read" and grant.name == "Claude Code"
    with db.transaction(immediate=False) as connection:
        stored = [row[0] for row in connection.execute("SELECT hash FROM mcp_tokens")]
    assert token not in stored and web_oauth.digest(token) in stored
    assert [client["scope"] for client in web_oauth.clients()] == ["read"]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli_main(["mcp", "revoke", identifier]) == 0
    assert web_oauth.check(token) is None
    assert web_oauth.check("") is None


def _connected(web_oauth, name: str = "claude.ai") -> tuple[str, dict]:
    """A connector registered and through the consent: its id, and its first pair."""
    import base64
    import hashlib

    client_id = web_oauth.register(
        {"client_name": name, "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"]}
    )["client_id"]
    verifier = "v" * 64
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    asked = web_oauth.asked(
        {
            "client_id": client_id,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    given = web_oauth.code(asked, web_oauth.SCOPES)
    pair = web_oauth.exchange(
        {
            "grant_type": "authorization_code",
            "code": given,
            "client_id": client_id,
            "code_verifier": verifier,
        }
    )
    return client_id, pair


@case
def a_refresh_token_that_comes_back_after_it_turned_over_takes_its_client_with_it(state_home):
    """A refresh token turns over at each use: one presented twice was copied.

    Whoever got there first holds a live pair — the thief or the connector,
    nobody can tell — so the second use revokes every key of the client, the
    pair the first one drew included. Another client keeps its own.
    """
    from ponos.web import oauth as web_oauth

    client_id, first = _connected(web_oauth)
    other_id, other = _connected(web_oauth, "another")
    stolen = first["refresh_token"]
    turned = web_oauth.exchange(
        {"grant_type": "refresh_token", "refresh_token": stolen, "client_id": client_id}
    )
    assert web_oauth.check(turned["access_token"]) is not None
    try:
        web_oauth.exchange(
            {"grant_type": "refresh_token", "refresh_token": stolen, "client_id": client_id}
        )
    except web_oauth.OAuthError as error:
        assert error.error == "invalid_grant"
    else:
        raise AssertionError("a refresh token used twice is refused")
    assert web_oauth.check(turned["access_token"]) is None, "the pair it was turned into goes"
    try:
        web_oauth.exchange(
            {
                "grant_type": "refresh_token",
                "refresh_token": turned["refresh_token"],
                "client_id": client_id,
            }
        )
    except web_oauth.OAuthError:
        pass
    else:
        raise AssertionError("and so does the refresh token drawn with it")
    assert web_oauth.check(other["access_token"]) is not None, "another client is not touched"
    listed = {client["id"]: client["scope"] for client in web_oauth.clients()}
    assert listed[client_id] == "" and listed[other_id] == "read write"


@case
def signing_out_everywhere_signs_the_oauth_connectors_out_and_names_the_drawn_tokens(state_home):
    """`serve --sign-out-everywhere` used to draw a new key for the cookies alone.

    A connector kept its refresh token — ninety days, renewed at each use, so
    for ever. Every client that came in over OAuth is signed out now; a token
    drawn with `ponos mcp token` stays, as the console's token does, and the
    command names it with the line that takes it back.
    """
    from ponos.web import oauth as web_oauth

    client_id, pair = _connected(web_oauth)
    local_id, local_token = web_oauth.local("Claude Code", write=False)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli_main(["serve", "--sign-out-everywhere"]) == 0
    said = out.getvalue()
    assert web_oauth.check(pair["access_token"]) is None, "the connector answers no more"
    try:
        web_oauth.exchange(
            {
                "grant_type": "refresh_token",
                "refresh_token": pair["refresh_token"],
                "client_id": client_id,
            }
        )
    except web_oauth.OAuthError:
        pass
    else:
        raise AssertionError("nor does it draw a new pair")
    assert "2 key(s) taken back" in said, said
    assert web_oauth.check(local_token) is not None, "a token drawn here stays"
    assert f"ponos mcp revoke {local_id}" in said, said


@case
def registering_is_counted_per_address_and_answered_429_past_the_hour_s_quota(state_home):
    """`/oauth/register` is open to anybody and writes a row each time.

    Twenty an hour from one address, then `429` with `Retry-After` — and no
    row for the refused one; another address, or the next hour, registers
    again.
    """
    import urllib.error
    import urllib.request

    from ponos.web import app as web_app
    from ponos.web import attempts as web_attempts
    from ponos.web import oauth as web_oauth

    quota = web_attempts.Quota(2, 3600, clock=lambda: 0.0)
    assert quota.take("a") == 0 and quota.take("a") == 0
    assert quota.take("a") == 3600, "the third waits for the end of the window"
    assert quota.take("b") == 0, "another address has its own"
    quota.clock = lambda: 3600.0
    assert quota.take("a") == 0, "and the next window starts afresh"

    with _board() as board:
        api = _ideas_api(board)
        api._config.web.token = "tok"
        console = web_app.Console(("127.0.0.1", 0), api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{console.server_address[1]}"
        body = json.dumps({"redirect_uris": ["https://x.example/cb"]}).encode()

        def register(forwarded: str) -> tuple[int, Message]:
            request = urllib.request.Request(
                base + "/oauth/register",
                data=body,
                headers={"Content-Type": "application/json", "X-Forwarded-For": forwarded},
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, response.headers
            except urllib.error.HTTPError as error:
                return error.code, error.headers

        try:
            for _ in range(web_oauth.REGISTRATIONS_PER_HOUR):
                assert register("203.0.113.7")[0] == 201
            code, headers = register("203.0.113.7")
            assert code == 429 and int(headers.get("Retry-After")) > 3500, (code, headers)
            assert len(web_oauth.clients()) == web_oauth.REGISTRATIONS_PER_HOUR
            assert register("198.51.100.9")[0] == 201, "another address is not held back"
        finally:
            console.shutdown()
            console.server_close()


@case
def the_purge_forgets_expired_keys_and_the_clients_that_hold_none(state_home):
    """Each registration is a row and each refresh a pair: neither is kept for ever.

    A day after it expired, a code or a token goes; a registered client with
    no key left goes once it is a day old. A client just registered stays, as
    do a connected one, a revoked refresh token not yet expired — it is what
    tells a copied one — and a token drawn with `ponos mcp token`.
    """
    from datetime import timedelta

    from ponos.web import oauth as web_oauth

    abandoned = web_oauth.register({"redirect_uris": ["https://x.example/cb"]})["client_id"]
    fresh = web_oauth.register({"redirect_uris": ["https://x.example/cb"]})["client_id"]
    connected, pair = _connected(web_oauth)
    turned = web_oauth.exchange(
        {
            "grant_type": "refresh_token",
            "refresh_token": pair["refresh_token"],
            "client_id": connected,
        }
    )
    local_id, local_token = web_oauth.local("Claude Code", write=False)
    long_ago = "2026-01-01T00:00:00+00:00"
    with db.transaction() as connection:
        connection.execute(
            "UPDATE mcp_clients SET created_at = ? WHERE id IN (?, ?, ?)",
            (long_ago, abandoned, connected, local_id),
        )
        # The first pair: its access token expired two days ago.
        connection.execute(
            "UPDATE mcp_tokens SET expires_at = ? WHERE hash = ?",
            (
                web_oauth._stamp(web_oauth._now() - timedelta(days=2)),
                web_oauth.digest(pair["access_token"]),
            ),
        )
    assert web_oauth.purge() == 2, "the abandoned client and the expired access token"
    with db.transaction(immediate=False) as connection:
        ids = {row[0] for row in connection.execute("SELECT id FROM mcp_clients")}
        hashes = {row[0] for row in connection.execute("SELECT hash FROM mcp_tokens")}
    assert ids == {fresh, connected, local_id}, ids
    assert web_oauth.digest(pair["access_token"]) not in hashes
    assert web_oauth.digest(pair["refresh_token"]) in hashes, "a spent refresh token is kept"
    assert web_oauth.check(turned["access_token"]) is not None
    assert web_oauth.check(local_token) is not None
    assert web_oauth.purge() == 0


# -- why a ticket stopped -----------------------------------------------------


@case
def the_mcp_tab_reads_claude_mcp_list_without_its_keys_and_tests_the_401_a_live_server_gives():
    """`claude mcp list` is the source of the servers, and what it prints may hold a key.

    A URL keeps its host and path, a command its program; a server that wants
    signing in is neither ok nor failing. The test asks the way a client does,
    without a key, and each way the answer can be wrong is a code.
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from ponos.web import mcp_setup

    listed = mcp_setup.parse(
        "Checking MCP server health...\n\n"
        "notion: https://mcp.notion.com/mcp?key=SECRET (HTTP) - ✓ Connected\n"
        "github: https://api.example.com/mcp - ⚠ Needs authentication\n"
        "local: npx -y @x/server --token=SECRET - ✗ Failed to connect\n"
    )
    assert [(one["name"], one["state"]) for one in listed] == [
        ("notion", "ok"),
        ("github", "auth"),
        ("local", "error"),
    ], listed
    assert listed[0]["target"] == "https://mcp.notion.com/mcp" and listed[2]["target"] == "npx", (
        listed
    )
    assert "SECRET" not in json.dumps(listed)

    answers = {"/mcp": 401, "/gone/mcp": 404, "/moved/mcp": 421}
    announced = {"resource": ""}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            status = answers.get(self.path, 404)
            self.send_response(status)
            if status == 401:
                self.send_header(
                    "WWW-Authenticate",
                    f'Bearer resource_metadata="http://{self.headers["Host"]}/meta"',
                )
            self.end_headers()

        def do_GET(self):
            body = json.dumps(
                {"resource": announced["resource"] or f"http://{self.headers['Host']}/mcp"}
            ).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        assert mcp_setup.probe(f"{base}/mcp")["ok"] is True
        assert mcp_setup.probe(f"{base}/gone/mcp")["code"] == "not-found"
        assert mcp_setup.probe(f"{base}/moved/mcp")["code"] == "misrouted"
        announced["resource"] = "https://elsewhere.example/mcp"
        mismatch = mcp_setup.probe(f"{base}/mcp")
        assert (
            mismatch["code"] == "address-mismatch" and mismatch["seen"] == announced["resource"]
        ), mismatch
    finally:
        server.shutdown()
        server.server_close()
    assert mcp_setup.probe("")["code"] == "no-address"
    # Asked again, as every request is, before it is said: without the pauses.
    http_module.sleep = lambda seconds: None
    try:
        assert mcp_setup.probe("http://127.0.0.1:1/mcp")["code"] == "unreachable"
    finally:
        http_module.sleep = time.sleep
    overview = mcp_setup.overview("http://127.0.0.1:8787", "https://p.example/")
    assert (
        overview["local"] == "http://127.0.0.1:8787/mcp"
        and overview["public"] == "https://p.example/mcp"
    )
