"""`uninstall.sh`: everything `install.sh` put on the machine, taken back.

Run for real, in a home of the case's own, with the commands it calls
replaced by stand-ins that write down how they were called: a desktop, a Mac
and a tailnet are not things a test machine has, and what is checked is that
the script asks each of them to let go.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from support import ROOT, case

# The commands the script talks to, each a line in `calls` when it is called.
FAKES = (
    "systemctl",
    "launchctl",
    "xdg-mime",
    "tailscale",
    "update-desktop-database",
    "gtk-update-icon-cache",
)


def _executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _installed(home: Path, calls: Path) -> None:
    """The files install.sh leaves on Linux and on a Mac, both in one home."""
    _executable(
        home / ".local/bin/ponos",
        f'echo "ponos $*" >> "{calls}"\n[ "$1" = serve ] && while :; do sleep 1; done\nexit 0\n',
    )
    (home / ".local/share/ponos/app").mkdir(parents=True)
    units = home / ".config/systemd/user"
    for unit in ("ponos.timer", "ponos.service", "ponos-web.service", "ponos-tailscale.service"):
        (units / unit).parent.mkdir(parents=True, exist_ok=True)
        (units / unit).write_text("[Unit]\n", encoding="utf-8")
    (units / "ponos.service.d").mkdir()
    (units / "ponos.service.d/credentials.conf").write_text("[Service]\n", encoding="utf-8")
    (units / "ponos-web.service.d").mkdir()
    (units / "other.service").write_text("[Unit]\n", encoding="utf-8")
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    for label in ("app.ponos.run", "app.ponos.web"):
        (agents / f"{label}.plist").write_text("<plist/>\n", encoding="utf-8")
    applications = home / ".local/share/applications"
    applications.mkdir(parents=True)
    (applications / "ponos-url-handler.desktop").write_text("[Desktop Entry]\n", encoding="utf-8")
    (home / ".config/mimeapps.list").write_text(
        "[Default Applications]\n"
        "x-scheme-handler/ponos=ponos-url-handler.desktop\n"
        "x-scheme-handler/ticket-runner=ponos-url-handler.desktop\n"
        "text/plain=editor.desktop\n",
        encoding="utf-8",
    )
    for size in (48, 64, 128, 256):
        icon = home / f".local/share/icons/hicolor/{size}x{size}/apps/ponos.png"
        icon.parent.mkdir(parents=True)
        icon.write_bytes(b"png")


# What the script may find of the machine: the plain tools, linked one by one,
# so that a systemctl, a tailscale or an xdg-mime of the machine running the
# suite is never reached by a home that is not theirs.
TOOLS = ("sh", "rm", "mv", "cat", "ls", "sed", "ps", "kill", "sleep", "uname", "grep")


def _uninstall(home: Path, fakes: Path, **variables: str) -> subprocess.CompletedProcess[str]:
    tools = home.parent / "tools"
    tools.mkdir(exist_ok=True)
    for tool in TOOLS:
        found = shutil.which(tool)
        if found and not (tools / tool).exists():
            (tools / tool).symlink_to(found)
    environment = {
        "HOME": str(home),
        "PATH": f"{fakes}:{tools}",
        **variables,
    }
    return subprocess.run(
        [str(home.parent / "tools/sh"), str(ROOT / "uninstall.sh")],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@case
def uninstalling_takes_back_everything_install_sh_put_down():
    """Launchd agents, the ponos:// handler, the icons, the drop-ins, the console, the doors."""
    with tempfile.TemporaryDirectory() as directory:
        home, fakes = Path(directory) / "home", Path(directory) / "fakes"
        calls = Path(directory) / "calls"
        calls.touch()
        for fake in FAKES:
            _executable(fakes / fake, f'echo "{fake} $*" >> "{calls}"\n')
        _installed(home, calls)
        # The console install.sh started with nohup, where neither systemd nor
        # launchd keeps it: its PID beside the runner's state.
        console = subprocess.Popen(
            ["sh", str(home / ".local/bin/ponos"), "serve"], start_new_session=True
        )
        try:
            web = home / ".local/state/ponos/web"
            web.mkdir(parents=True)
            (web / "serve.pid").write_text(f"{console.pid}\n", encoding="utf-8")

            done = _uninstall(home, fakes)
            assert done.returncode == 0, done.stdout + done.stderr

            assert console.wait(timeout=10) is not None, "the background console still runs"
        finally:
            if console.poll() is None:
                console.kill()
                console.wait()
        said = calls.read_text(encoding="utf-8").splitlines()
        # The doors are taken down while the binary that knows them is still there.
        assert "ponos tailscale disable" in said, said
        for label in ("app.ponos.run", "app.ponos.web"):
            plist = home / f"Library/LaunchAgents/{label}.plist"
            assert f"launchctl unload -w {plist}" in said, said
        left = [
            str(path.relative_to(home))
            for place in (
                "Library/LaunchAgents",
                ".local/share/applications",
                ".config/systemd/user",
            )
            for path in (home / place).glob("ponos*")
        ]
        left += [
            str(path.relative_to(home))
            for path in (home / ".local/share/icons/hicolor").glob("*/apps/ponos*")
        ]
        left += [
            str(path.relative_to(home))
            for path in (home / "Library/LaunchAgents").glob("app.ponos.*")
        ]
        assert not left, left
        assert not (home / ".local/bin/ponos").exists()
        assert (home / ".config/systemd/user/other.service").exists(), "only ponos's own units go"
        handlers = (home / ".config/mimeapps.list").read_text(encoding="utf-8")
        assert "ponos-url-handler" not in handlers and "text/plain=editor.desktop" in handlers
        # Kept without TR_PURGE: the configuration and the history are yours.
        assert (home / ".local/state/ponos").is_dir()


@case
def uninstalling_without_a_tailnet_or_a_desktop_still_ends_well():
    """Nothing but sh: no tailscale to ask, no launchctl, no xdg — every step is optional."""
    with tempfile.TemporaryDirectory() as directory:
        home, fakes = Path(directory) / "home", Path(directory) / "fakes"
        fakes.mkdir()
        calls = Path(directory) / "calls"
        _executable(home / ".local/bin/ponos", f'echo "ponos $*" >> "{calls}"\n')
        (home / ".local/state/ponos").mkdir(parents=True)
        (home / ".config/ponos").mkdir(parents=True)

        done = _uninstall(home, fakes, TR_PURGE="1")

        assert done.returncode == 0, done.stdout + done.stderr
        assert not calls.exists(), "without tailscale there are no doors to take down"
        assert not (home / ".local/state/ponos").exists()
        assert not (home / ".config/ponos").exists()
        assert not os.path.exists(home / ".local/bin/ponos")
