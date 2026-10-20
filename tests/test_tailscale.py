"""`tailscale.py`: the MCP doors published on the tailnet."""

from __future__ import annotations

import json
import subprocess
import threading

from support import _board, _ideas_api, case

# -- the vault ---------------------------------------------------------------


def _serve_status(
    name: str, port: int = 8787, funnel: bool = True, extra: dict | None = None
) -> str:
    local = f"http://127.0.0.1:{port}"
    web = {
        f"{name}:8443": {"Handlers": {"/": {"Proxy": local}}},
        f"{name}:443": {
            "Handlers": {
                path: {"Proxy": local + path} for path in ("/mcp", "/oauth", "/.well-known")
            }
        },
    }
    web[f"{name}:443"]["Handlers"].update(extra or {})
    return json.dumps({"Web": web, "AllowFunnel": {f"{name}:443": True} if funnel else {}})


@case
def tailscale_publishes_the_mcp_paths_on_the_funnel_port_and_the_console_on_another():
    """Funnel is per host and port: the console on 443 beside /mcp would be public."""
    from ponos import tailscale

    lines = tailscale.commands(8787)
    assert lines[0] == ["serve", "--bg", "--https=8443", "http://127.0.0.1:8787"], lines[0]
    funnelled = [line for line in lines if line[0] == "funnel"]
    assert [line[3] for line in funnelled] == [
        "--set-path=/mcp",
        "--set-path=/oauth",
        "--set-path=/.well-known",
    ]
    assert all(line[2] == "--https=443" for line in funnelled)
    assert all(not line[-1].endswith(":8787") for line in funnelled), (
        "the root must never be funnelled"
    )


@case
def a_request_through_the_funnel_reaches_the_mcp_doors_and_nothing_else(state_home):
    import urllib.error
    import urllib.request

    from ponos import tailscale
    from ponos.web import server as web_server

    assert tailscale.funnel_allowed("/mcp") and tailscale.funnel_allowed("/oauth/token")
    assert tailscale.funnel_allowed("/.well-known/oauth-protected-resource/mcp")
    assert not tailscale.funnel_allowed("/") and not tailscale.funnel_allowed("/api/tickets")
    assert not tailscale.funnel_allowed("/mcpx"), "a prefix of a name is not the path"

    with _board() as board:
        api = _ideas_api(board)
        api._config.web.token = "tok"
        console = web_server.Console(("127.0.0.1", 0), web_server.Handler, api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        port = console.server_address[1]

        def status(path: str, funnel: bool, method: str = "GET") -> int:
            headers = {tailscale.FUNNEL_HEADER: "?1"} if funnel else {}
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}",
                headers=headers,
                method=method,
                data=b"{}" if method == "POST" else None,
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status
            except urllib.error.HTTPError as error:
                return error.code

        try:
            assert status("/api/tickets?token=tok", funnel=True) == 404
            assert status("/healthz", funnel=True) == 404
            assert status("/api/tickets", funnel=True, method="POST") == 404
            assert status("/.well-known/oauth-protected-resource/mcp", funnel=True) == 200
            assert status("/mcp", funnel=True, method="POST") == 401, "the keys still apply"
            assert status("/healthz", funnel=False) == 200, "inside the tailnet nothing changes"
        finally:
            console.shutdown()
            console.server_close()


@case
def tailscale_serve_status_is_read_as_in_place_only_when_both_doors_are_exactly_ours():
    from ponos import tailscale

    name = "laptop.tail1234.ts.net"
    assert tailscale.configured(_serve_status(name), name, 8787)
    assert not tailscale.configured("{}", name, 8787), "nothing published yet"
    assert not tailscale.configured("not json", name, 8787)
    assert not tailscale.configured(_serve_status(name, port=9000), name, 8787), "the console moved"
    assert not tailscale.configured(_serve_status(name, funnel=False), name, 8787), (
        "funnel not allowed"
    )
    extra = {"/": {"Proxy": "http://127.0.0.1:8787"}}
    assert not tailscale.configured(_serve_status(name, extra=extra), name, 8787), (
        "a root handler on the funnel port is the console, public"
    )


@case
def the_tailscale_watch_waits_for_the_tailnet_then_publishes_and_republishes_after_a_drift():
    import subprocess

    from ponos import tailscale

    name = "laptop.tail1234.ts.net"
    state = {"backend": "Stopped", "serve": "{}"}
    ran: list[list[str]] = []

    def run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        ran.append(arguments)
        out = ""
        if arguments[:2] == ["status", "--json"]:
            out = json.dumps({"BackendState": state["backend"], "Self": {"DNSName": name + "."}})
        elif arguments[:2] == ["serve", "status"]:
            out = state["serve"]
        elif arguments[0] in ("serve", "funnel"):
            state["serve"] = _serve_status(name)
        return subprocess.CompletedProcess(arguments, 0, out, "")

    said: list[str] = []
    ticks = iter(range(100))

    def sleep(_: float) -> None:
        step = next(ticks)
        if step == 1:
            state["backend"] = "Running"  # the lid is open, the Wi-Fi is back
        if step == 4:
            state["serve"] = "{}"  # tailscaled lost it

    tailscale.watch(8787, 30, run=run, sleep=sleep, log=said.append, rounds=7)
    published = [line for line in ran if line[0] in ("serve", "funnel") and "status" not in line]
    assert len(published) == 2 * 4, ("once on connecting, once after the drift", published)
    assert said[0].startswith("tailscale is Stopped"), said
    assert sum("serving" in line for line in said) == 2, said


@case
def a_missing_tailscale_binary_is_said_once_by_the_watcher_and_does_not_stop_it():
    from ponos import tailscale

    said: list[str] = []

    def run(arguments: list[str]):
        raise tailscale.TailscaleError("tailscale is not installed")

    tailscale.watch(8787, 1, run=run, sleep=lambda _: None, log=said.append, rounds=3)
    assert said == ["tailscale is not installed"], said
