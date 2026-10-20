"""Reaching the console from a phone, over Tailscale, without opening it.

Two doors on one machine, and they must not be the same door. The console is
arbitrary code execution (see the README) and stays inside the tailnet. The MCP
connector is called by Anthropic's servers, which are not on the tailnet, so
*that* path — and only that path — has to be public, behind the keys of
`web/oauth.py`.

**Why two ports.** Funnel is a property of a host *and port*, not of a path:
`tailscale serve` on 443 for the console and `tailscale funnel` for `/mcp` on the
same 443 would publish both. So the console is served on 8443, tailnet only,
and 443 is the funnel, with a handler for `/mcp`, `/oauth` and `/.well-known`
and for nothing else — Tailscale answers 404 to any other path. The console
refuses those other paths as well when a request carries the header Funnel adds
(`Tailscale-Funnel-Request`, see `server.py`): the second lock, for the day a
handler is added to the first by hand.

**Why a loop and not a one-shot.** `tailscaled` keeps the serve configuration
across restarts, but a laptop is closed, moved, put on another network and
logged out of its tailnet; a unit that applied the configuration once at boot
would say nothing about any of that. `watch` reads the state every half minute,
waits while the node is not connected, and puts the configuration back if it
drifted — which is the whole of "reconnecting after a sleep", since the
reconnecting itself is `tailscaled`'s.

Nothing here talks to a network but through the `tailscale` binary.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

# The one port the console is served on inside the tailnet, and the one the
# funnel opens. Funnel only accepts 443, 8443 and 10000.
PRIVATE_PORT = 8443
PUBLIC_PORT = 443

# What the funnel hands to the console: the MCP endpoint, the authorisation
# server it points to, and the metadata that says where that is. Nothing else.
PUBLIC_PATHS = ("/mcp", "/oauth", "/.well-known")

# The header Funnel puts on every request that came through it.
FUNNEL_HEADER = "Tailscale-Funnel-Request"

Run = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


class TailscaleError(RuntimeError):
    """The `tailscale` command is missing, or refused."""


@dataclass(frozen=True)
class Node:
    state: str
    """`Running` when connected; `Stopped`, `NeedsLogin`, `Starting`… otherwise."""
    name: str
    """This machine's name on the tailnet: `laptop.tail1234.ts.net`, no final dot."""

    @property
    def connected(self) -> bool:
        return self.state == "Running" and bool(self.name)


def funnel_allowed(route: str) -> bool:
    """Whether a request that came through Funnel may reach `route`."""
    return any(route == path or route.startswith(path + "/") for path in PUBLIC_PATHS)


def commands(port: int) -> list[list[str]]:
    """The `tailscale` invocations that put the two doors up, in order."""
    local = f"http://127.0.0.1:{port}"
    lines = [["serve", "--bg", f"--https={PRIVATE_PORT}", local]]
    for path in PUBLIC_PATHS:
        lines.append(["funnel", "--bg", f"--https={PUBLIC_PORT}", f"--set-path={path}", local + path])
    return lines


def withdrawals() -> list[list[str]]:
    """The invocations that take both doors down."""
    return [
        ["funnel", f"--https={PUBLIC_PORT}", "off"],
        ["serve", f"--https={PRIVATE_PORT}", "off"],
    ]


def parse_node(status: str) -> Node:
    """`tailscale status --json`, reduced to what a decision needs."""
    try:
        data = json.loads(status)
    except ValueError:
        return Node(state="unknown", name="")
    me = data.get("Self") or {}
    return Node(
        state=str(data.get("BackendState") or "unknown"),
        name=str(me.get("DNSName") or "").rstrip("."),
    )


def configured(serve: str, name: str, port: int) -> bool:
    """Whether `tailscale serve status --json` already holds exactly our two doors."""
    try:
        data = json.loads(serve)
    except ValueError:
        return False
    web = data.get("Web") or {}
    local = f"http://127.0.0.1:{port}"

    private = (web.get(f"{name}:{PRIVATE_PORT}") or {}).get("Handlers") or {}
    if not _proxies(private.get("/"), local):
        return False
    public = (web.get(f"{name}:{PUBLIC_PORT}") or {}).get("Handlers") or {}
    if set(public) != set(PUBLIC_PATHS):
        return False
    if not all(_proxies(public[path], local + path) for path in PUBLIC_PATHS):
        return False
    funnel = data.get("AllowFunnel") or {}
    return bool(funnel.get(f"{name}:{PUBLIC_PORT}")) and not funnel.get(f"{name}:{PRIVATE_PORT}")


def _proxies(handler: object, target: str) -> bool:
    proxy = handler.get("Proxy", "") if isinstance(handler, dict) else ""
    return str(proxy).rstrip("/") == target.rstrip("/")


def _run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    if not shutil.which("tailscale"):
        raise TailscaleError("tailscale is not installed — https://tailscale.com/download")
    try:
        return subprocess.run(
            ["tailscale", *arguments], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise TailscaleError(f"tailscale {' '.join(arguments)}: {error}") from error


def node(run: Run = _run) -> Node:
    return parse_node(run(["status", "--json"]).stdout)


def apply(port: int, run: Run = _run) -> None:
    """Put both doors up. Raises with what `tailscale` said if one is refused."""
    for arguments in commands(port):
        done = run(arguments)
        if done.returncode != 0:
            said = (done.stderr or done.stdout).strip().splitlines()
            raise TailscaleError(
                f"tailscale {' '.join(arguments)}: {said[-1] if said else 'refused'}"
            )


def withdraw(run: Run = _run) -> None:
    for arguments in withdrawals():
        run(arguments)


def in_place(port: int, name: str, run: Run = _run) -> bool:
    return configured(run(["serve", "status", "--json"]).stdout, name, port)


def watch(
    port: int,
    interval: int = 30,
    run: Run = _run,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
    rounds: int | None = None,
) -> None:
    """Keep the two doors up for as long as the machine is on a tailnet.

    `rounds` bounds the loop for the tests; in the unit it is endless. A failure
    to apply is said and tried again on the next round — a funnel not yet
    allowed by the tailnet's policy is something a person fixes in the admin
    console, after which this goes through without a restart.
    """
    waiting = False
    last = ""
    count = 0
    while rounds is None or count < rounds:
        count += 1
        try:
            current = node(run)
            if not current.connected:
                if not waiting:
                    log(f"tailscale is {current.state}: waiting for the tailnet")
                waiting = True
            else:
                waiting = False
                if not in_place(port, current.name, run):
                    apply(port, run)
                    log(f"serving https://{current.name}:{PRIVATE_PORT} (tailnet) and {PUBLIC_PATHS} on {PUBLIC_PORT} (funnel)")
                last = ""
        except TailscaleError as error:
            if str(error) != last:
                log(str(error))
            last = str(error)
        sleep(interval)
