#!/bin/sh
# Install Ponos.
#
#   curl -LsSf https://raw.githubusercontent.com/hermez-agency/ponos/main/install.sh | sh
#
# Environment variables:
#   TR_REPO       source repository        (default: hermez-agency/ponos)
#   TR_REF        branch or tag            (default: main; a tag pins the version,
#                                          a branch is followed by the auto-update)
#   TR_SRC        local folder to copy     (install from a clone, no network,
#                                          and no auto-update: there is no remote)
#   TR_INTERVAL   seconds between runs     (default: 1800, i.e. 30 min)
#   TR_NO_SERVICE=1   do not install the systemd units (timer nor console)
#   TR_NO_WEB=1       install the console's unit, but leave it stopped
#   TR_NO_OPEN=1      do not open the console in the browser at the end
set -eu

TR_REPO="${TR_REPO:-hermez-agency/ponos}"
TR_REF="${TR_REF:-main}"
TR_INTERVAL="${TR_INTERVAL:-1800}"

APP_ROOT="$HOME/.local/share/ponos"
# A link to the version in use, app-<commit> beside it — see update.py.
APP_DIR="$APP_ROOT/app"
BIN_DIR="$HOME/.local/bin"
BIN="$BIN_DIR/ponos"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ponos"
CONFIG="$CONFIG_DIR/config.toml"
UNIT_DIR="$HOME/.config/systemd/user"

BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; RESET=""
if [ -t 1 ]; then
    BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); GREEN=$(printf '\033[32m')
    YELLOW=$(printf '\033[33m'); RED=$(printf '\033[31m'); RESET=$(printf '\033[0m')
fi

say()  { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$1"; }
ok()   { printf '    %s✓%s %s\n' "$GREEN" "$RESET" "$1"; }
warn() { printf '    %s!%s %s\n' "$YELLOW" "$RESET" "$1"; }
die()  { printf '%serror:%s %s\n' "$BOLD" "$RESET" "$1" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- 1. prerequisites --------------------------------------------------------
# Everything missing is said at once, each with the command that installs it on
# this machine: somebody stopped at the first missing tool, who runs the script
# again only to be stopped at the second, has been told half of it twice. The
# commands are the ones prerequisites.py gives `doctor` and the console — a test
# keeps the two in step.
say "Checking what this machine needs"
OS=$(uname -s)
MISSING=0
lack() {  # what is missing, and the command that fixes it
    printf '    %s✗%s %s\n' "$RED" "$RESET" "$1"
    [ -n "${2:-}" ] && printf '        %s\n' "$2"
    MISSING=$((MISSING + 1))
}
package() {  # the tool, as the package manager names it
    case "$1:$2" in
        pacman:python3) echo python ;;
        pacman:gh) echo github-cli ;;
        brew:python3) echo python@3.12 ;;
        *) echo "$2" ;;
    esac
}
install_hint() {  # the command that installs $1 here
    if [ "$1" = claude ]; then echo "curl -fsSL https://claude.ai/install.sh | bash"; return; fi
    if [ "$OS" = Darwin ]; then
        if have brew; then echo "brew install $(package brew "$1")"
        else echo "install Homebrew (https://brew.sh), then: brew install $(package brew "$1")"; fi
        return
    fi
    if have apt-get; then echo "sudo apt-get install -y $(package apt-get "$1")"
    elif have dnf; then echo "sudo dnf install -y $(package dnf "$1")"
    elif have pacman; then echo "sudo pacman -S --noconfirm $(package pacman "$1")"
    elif have brew; then echo "brew install $(package brew "$1")"
    else echo "install $1 with your package manager"; fi
}

# The newest Python that is recent enough, whatever it is called: a Mac's own
# python3 is 3.9, Ubuntu 22.04's is 3.10, and both machines often have a newer
# one beside it under its versioned name.
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
    if have "$candidate" && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        PYTHON="$(command -v "$candidate")"
        break
    fi
done
if [ -n "$PYTHON" ]; then
    ok "python $("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])') — $PYTHON"
elif have python3; then
    lack "python3 is $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])'), and Ponos needs 3.11 or newer (tomllib is part of the standard library since then)" \
        "$(install_hint python3 | sed 's/python3$/python3.11/')"
else
    lack "python3 is missing — Ponos needs 3.11 or newer" "$(install_hint python3)"
fi

if have git; then ok "$(git --version)"; else lack "git is missing" "$(install_hint git)"; fi
if [ -n "${TR_SRC:-}" ] && ! have tar; then lack "tar is missing" "$(install_hint tar)"; fi

# Room for the code is little; room for a ticket is a worktree and its build.
FREE_MB=$(df -Pk "$HOME" 2>/dev/null | awk 'NR == 2 { print int($4 / 1024) }')
if [ -n "$FREE_MB" ] && [ "$FREE_MB" -lt 500 ]; then
    lack "only ${FREE_MB} MB free in $HOME — the installation alone needs 500 MB" "free some space, then run this again"
elif [ -n "$FREE_MB" ] && [ "$FREE_MB" -lt 5120 ]; then
    warn "${FREE_MB} MB free — enough to install, but a ticket only starts above 5120 MB"
elif [ -n "$FREE_MB" ]; then
    ok "${FREE_MB} MB free"
fi

if [ "$MISSING" -gt 0 ]; then
    printf '\n%s%d thing(s) to install first%s — run the command(s) above, then this one again:\n\n' "$BOLD" "$MISSING" "$RESET"
    printf '    curl -LsSf https://raw.githubusercontent.com/%s/%s/install.sh | sh\n\n' "$TR_REPO" "$TR_REF"
    exit 1
fi

# Claude Code is what does the work. Missing, it is offered rather than refused:
# its installer is one script, needs no root, and the question is asked only
# when somebody is there to answer it.
if ! have claude && (exec 3</dev/tty) 2>/dev/null; then
    printf '    %s!%s Claude Code is not installed — it is what runs the tickets.\n' "$YELLOW" "$RESET"
    printf '      Install it now (%s)? [Y/n] ' "$(install_hint claude)"
    read -r answer </dev/tty || answer="n"
    case "$answer" in
        ""|y|Y|yes|o|O|oui)
            curl -fsSL https://claude.ai/install.sh | bash || warn "the Claude Code installer failed"
            PATH="$HOME/.local/bin:$PATH"
            ;;
    esac
fi
if have claude; then
    ok "claude $(claude --version 2>/dev/null | head -1)"
    # Signed in with an account, or not — what `provider.cli_login` asks too.
    if claude auth status 2>/dev/null | "$PYTHON" -c 'import json, sys; sys.exit(0 if json.load(sys.stdin).get("loggedIn") else 1)' 2>/dev/null; then
        ok "Claude Code is signed in"
    else
        warn "Claude Code is not signed in: claude auth login — or give the console an API key"
    fi
else
    warn "Claude Code is missing — no ticket can run without it: $(install_hint claude)"
fi

if have gh; then
    if gh auth status >/dev/null 2>&1; then
        ok "gh authenticated"
    else
        warn "gh found but not authenticated — the console connects GitHub in one click instead"
    fi
else
    warn "gh missing — fine: the console connects GitHub in one click (for pull requests)"
fi

# --- 2. sources -------------------------------------------------------------
# Each version in a directory of its own, and `app` moved onto it in one rename:
# a pass the timer starts meanwhile runs on the old version or on the new one,
# never on a mixture of the two. The version replaced is kept, for what still
# runs on it and for going back.
mkdir -p "$APP_ROOT" "$BIN_DIR"
STAGE="$APP_ROOT/app.partial"
rm -rf "$STAGE"
if [ -n "${TR_SRC:-}" ]; then
    say "Copying sources from $TR_SRC"
    have tar || die "tar is required"
    [ -d "$TR_SRC/src/ponos" ] || die "$TR_SRC does not contain src/ponos"
    mkdir -p "$STAGE"
    # `node_modules` is the console's build-time dependency and is measured in
    # hundreds of megabytes; what the console actually serves is already built
    # and committed under src/ponos/web/static. `.venv` is a contributor's
    # tools: the version gets an environment of its own below.
    tar -C "$TR_SRC" --exclude='.git' --exclude='__pycache__' --exclude='node_modules' --exclude='.venv' \
        -cf - . | tar -C "$STAGE" -xf -
    LABEL="copy-$(date +%s)"
    WHAT="a copy: it will not update itself"
else
    # A clone rather than a tarball: it is what lets the runner answer "am I
    # still on the latest version" with one git fetch, once an hour, and update
    # itself when the answer is no. Shallow, because no run ever reads history.
    say "Cloning $TR_REPO ($TR_REF)"
    GIT_TERMINAL_PROMPT=0 git clone --quiet --depth 1 --branch "$TR_REF" \
        "https://github.com/$TR_REPO.git" "$STAGE" \
        || die "clone failed (private repository, or no such branch?)"
    LABEL="$(git -C "$STAGE" rev-parse --short=12 HEAD)"
    WHAT="$(git -C "$STAGE" rev-parse --short HEAD)"
fi
# The same commit installed again gets a name of its own: the directory in use
# is never written over.
[ -e "$APP_ROOT/app-$LABEL" ] && LABEL="$LABEL-$(date +%s)"
mv "$STAGE" "$APP_ROOT/app-$LABEL"

# Its environment, made before `app` names it (environment.py says why): a
# version whose packages cannot be installed is removed, and the version in use
# — when there is one — stays in use, untouched. It is made from the Python
# chosen in step 1.
if ! ENV_PROBLEM=$(PYTHONPATH="$APP_ROOT/app-$LABEL/src" "$PYTHON" - "$APP_ROOT/app-$LABEL" <<'PY'
import pathlib, sys
from ponos import environment
problem = environment.create(pathlib.Path(sys.argv[1]))
print(problem)
sys.exit(1 if problem else 0)
PY
); then
    rm -rf "$APP_ROOT/app-$LABEL"
    die "the environment could not be made: $ENV_PROBLEM — nothing changed"
fi
if [ -x "$APP_ROOT/app-$LABEL/.venv/bin/python" ]; then
    ok "environment in $APP_ROOT/app-$LABEL/.venv"
else
    warn "no environment (this python3 cannot make one) — the machine's python3 runs ponos, as before"
fi
PREVIOUS=""
if [ -L "$APP_DIR" ]; then
    PREVIOUS="$(readlink "$APP_DIR")"
elif [ -e "$APP_DIR" ]; then
    # Installed before versions had directories: that one becomes the previous.
    PREVIOUS="app-before-$(date +%s)"
    mv "$APP_DIR" "$APP_ROOT/$PREVIOUS"
fi
rm -f "$APP_ROOT/.app.link"
ln -s "app-$LABEL" "$APP_ROOT/.app.link"
# `mv` onto a link to a directory would move into it; a rename replaces it.
python3 -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' "$APP_ROOT/.app.link" "$APP_DIR"
for old in "$APP_ROOT"/app-*; do
    name="${old##*/}"
    [ "$name" = "app-$LABEL" ] || [ "$name" = "${PREVIOUS##*/}" ] || rm -rf "$old"
done
ok "sources in $APP_ROOT/app-$LABEL ($WHAT)"

# --- 3. executable ----------------------------------------------------------
# The Python chosen above: the launcher prefers the version's environment, and
# falls back on this one while a version has none.
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@PYTHON@|$PYTHON|g" \
    "$APP_DIR/bin/ponos.in" > "$BIN"
chmod +x "$BIN"
ok "command installed: $BIN"

# --- migration filet: an installation from before the rename ---------------
# Ponos was installed as ticket-runner. Its timer and console are stopped and
# their units removed, the variables of their drop-ins renamed, its
# configuration and state moved under the new name (legacy.py says how, and
# that nothing is lost), its old sources removed, and the old command kept as
# a hidden alias that says so and runs ponos. Removed with the filet.
OLD_NAME=ticket-runner
OLD_UNITS="$OLD_NAME.timer $OLD_NAME.service $OLD_NAME-web.service"
if have systemctl && [ -e "$UNIT_DIR/$OLD_NAME.timer" ]; then
    say "Moving the $OLD_NAME installation over to ponos"
    systemctl --user disable --now $OLD_UNITS >/dev/null 2>&1 || true
    for unit in $OLD_UNITS; do
        rm -f "$UNIT_DIR/$unit"
        new_unit=$(printf '%s' "$unit" | sed "s/^$OLD_NAME/ponos/")
        if [ -d "$UNIT_DIR/$unit.d" ] && [ ! -e "$UNIT_DIR/$new_unit.d" ]; then
            mv "$UNIT_DIR/$unit.d" "$UNIT_DIR/$new_unit.d"
            sed -i 's/TICKET_RUNNER_/PONOS_/g' "$UNIT_DIR/$new_unit.d"/*.conf 2>/dev/null || true
        fi
    done
    systemctl --user daemon-reload || true
    ok "$OLD_NAME units removed"
fi
PYTHONPATH="$APP_DIR/src" "$PYTHON" -c 'from ponos import legacy; legacy.directories(print)' \
    | sed 's/^ponos: /    /'
if [ -d "$HOME/.local/share/$OLD_NAME" ]; then
    rm -rf "$HOME/.local/share/$OLD_NAME"
    rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/applications/$OLD_NAME-url-handler.desktop"
    sed -e "s|@BIN@|$BIN|g" "$APP_DIR/bin/former-name.in" > "$BIN_DIR/$OLD_NAME"
    chmod +x "$BIN_DIR/$OLD_NAME"
    ok "old sources removed, $OLD_NAME kept as an alias of ponos"
fi
mkdir -p "$CONFIG_DIR"

# --- 4. configuration -------------------------------------------------------
if [ -f "$CONFIG" ]; then
    ok "existing configuration kept: $CONFIG"
else
    cp "$APP_DIR/config.example.toml" "$CONFIG"
    chmod 600 "$CONFIG"
    ok "configuration created: $CONFIG"
    # Nothing more is asked here: the Notion token, the board, GitHub and the
    # first project are the console's first connection, opened at the end —
    # a form with a check behind each field says more than a terminal prompt.
fi

# The address the console answers on — read from the configuration rather than
# assumed, so a machine that moved the port is told where its own console is.
# The second word says how it is opened: "claimed" when somebody chose a token
# or a sign-in, "open" while its first connection is still waiting for one.
# Read by the runner's own loader: the token and the password are not in the
# file, they are in secrets.env or the environment.
CONSOLE_STATE=$(PYTHONPATH="$APP_DIR/src" "$PYTHON" - "$CONFIG" <<'PY'
import pathlib, sys
from ponos import config
try:
    web = config.load(pathlib.Path(sys.argv[1])).web
except (config.ConfigError, OSError, ValueError):
    web = config.Web()
chosen = web.token or (web.email and web.password)
print("http://%s:%d %s" % (web.host, web.port, "claimed" if chosen else "open"))
PY
)
CONSOLE=${CONSOLE_STATE% *}
CONSOLE_CLAIMED=${CONSOLE_STATE##* }

# --- 5. clickable session links ---------------------------------------------
# Registers ponos:// with the desktop, so the Session cell of a ticket
# opens a terminal already inside that Claude Code session.
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
if [ -d "$APP_DIR/desktop" ]; then
    say "Registering ponos:// links"
    mkdir -p "$DESKTOP_DIR"
    sed -e "s|@BIN@|$BIN|g" \
        "$APP_DIR/desktop/ponos-url-handler.desktop.in" \
        > "$DESKTOP_DIR/ponos-url-handler.desktop"
    have update-desktop-database && update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1
    if have xdg-mime; then
        # The second scheme is a migration filet: links written before the
        # rename are still in their Notion cells.
        xdg-mime default ponos-url-handler.desktop x-scheme-handler/ponos x-scheme-handler/ticket-runner \
            >/dev/null 2>&1 && ok "ponos:// links open a terminal on the session" \
            || warn "could not register ponos:// with the desktop"
    fi
fi

# The logo, cut out on a transparent background, in the sizes a desktop asks
# for: the notifications and the dock both look it up by the name `ponos`.
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
if [ -d "$APP_DIR/src/ponos/icons" ]; then
    for size in 48 64 128 256; do
        mkdir -p "$ICON_DIR/${size}x${size}/apps"
        cp "$APP_DIR/src/ponos/icons/ponos-$size.png" "$ICON_DIR/${size}x${size}/apps/ponos.png"
    done
    have gtk-update-icon-cache && gtk-update-icon-cache -q -t "$ICON_DIR" >/dev/null 2>&1
fi

# --- 6. timer and console ---------------------------------------------------
# What keeps them running depends on the machine: systemd's user session where
# there is one *that answers* — WSL, a container or an SSH session often have
# the command and no bus behind it, and asking it then fails the whole script —,
# launchd on a Mac, and otherwise the console started in the background, so
# that the one command still ends in the console.
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/ponos"
SERVICES=none
if [ "${TR_NO_SERVICE:-0}" != "1" ]; then
    if have systemctl && systemctl --user show-environment >/dev/null 2>&1; then
        SERVICES=systemd
    elif [ "$OS" = Darwin ] && have launchctl; then
        SERVICES=launchd
    else
        SERVICES=background
    fi
fi

# Does anything answer on the console's address? A 401 is an answer.
console_up() {
    "$PYTHON" - "$CONSOLE" <<'PY' 2>/dev/null
import sys, urllib.error, urllib.request
try:
    urllib.request.urlopen(sys.argv[1] + "/api/setup", timeout=2)
except urllib.error.HTTPError:
    pass
except Exception:
    sys.exit(1)
PY
}

if [ "$SERVICES" != none ]; then
    # The interval lives in the configuration, so that changing it later is one
    # number and "ponos enable" rather than a reinstall. TR_INTERVAL
    # only seeds it, on a configuration that does not set it yet.
    INTERVAL=$("$PYTHON" - "$CONFIG" "$TR_INTERVAL" <<'PY'
import pathlib, re, sys, tomllib
path, seed = pathlib.Path(sys.argv[1]), sys.argv[2]
text = path.read_text()
with path.open("rb") as handle:
    current = tomllib.load(handle).get("runner", {}).get("interval_seconds")
if current is None:
    text = re.sub(r"^(\[runner\]\n)", rf"\g<1>interval_seconds = {int(seed)}\n", text, count=1, flags=re.M)
    path.write_text(text)
    current = int(seed)
print(int(current))
PY
)
fi

if [ "$SERVICES" = systemd ]; then
    say "Installing the timer (one run every ${INTERVAL}s)"
    mkdir -p "$UNIT_DIR"
    ACCURACY=30s
    [ "$INTERVAL" -lt 60 ] && ACCURACY=1s
    # The login PATH is copied into the unit: a systemd service has neither
    # ~/.local/bin nor node in its own, so it would find neither claude nor npm.
    sed -e "s|@BIN@|$BIN|g" -e "s|@PATH@|$PATH|g" \
        "$APP_DIR/systemd/ponos.service.in" > "$UNIT_DIR/ponos.service"
    sed -e "s|@INTERVAL@|$INTERVAL|g" -e "s|@ACCURACY@|$ACCURACY|g" \
        "$APP_DIR/systemd/ponos.timer.in" > "$UNIT_DIR/ponos.timer"
    sed -e "s|@BIN@|$BIN|g" -e "s|@PATH@|$PATH|g" \
        "$APP_DIR/systemd/ponos-web.service.in" > "$UNIT_DIR/ponos-web.service"
    # Written and left off: publishing the MCP endpoint is `ponos tailscale enable`.
    sed -e "s|@BIN@|$BIN|g" -e "s|@PATH@|$PATH|g" \
        "$APP_DIR/systemd/ponos-tailscale.service.in" > "$UNIT_DIR/ponos-tailscale.service"
    systemctl --user daemon-reload
    systemctl --user enable --now ponos.timer >/dev/null 2>&1 \
        && ok "ponos.timer enabled" \
        || warn "enable it by hand: systemctl --user enable --now ponos.timer"
    # The console starts with the rest. What it opens is loopback — behind that
    # port sits a runner that starts Claude Code sessions with bypassPermissions,
    # so it is reachable from this machine and from nowhere else, and widening
    # `web.host` remains the decision it always was. A board you have to remember
    # to start by hand is a board you end up not looking at; TR_NO_WEB=1 keeps
    # the unit installed and stopped.
    if [ "${TR_NO_WEB:-0}" != "1" ]; then
        if systemctl --user enable --now ponos-web.service >/dev/null 2>&1; then
            CONSOLE_UP=1
            ok "ponos-web.service enabled — $CONSOLE"
        else
            warn "start it by hand: systemctl --user enable --now ponos-web"
        fi
    fi
    # Without lingering, the timer stops when the session closes.
    if have loginctl && [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
        warn "to keep it running with no session open: sudo loginctl enable-linger $USER"
    fi
elif [ "$SERVICES" = launchd ]; then
    # The Mac's systemd: one agent keeps the console up, the other starts a
    # pass every INTERVAL seconds. Both log beside the runner's state.
    say "Installing the launchd agents (one run every ${INTERVAL}s)"
    AGENTS="$HOME/Library/LaunchAgents"
    mkdir -p "$AGENTS" "$STATE_DIR"
    agent() {  # label, verb, the keys that say when it runs
        cat > "$AGENTS/$1.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key><array><string>$BIN</string><string>$2</string></array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$PATH</string><key>PYTHONUNBUFFERED</key><string>1</string></dict>
  <key>StandardOutPath</key><string>$STATE_DIR/$1.log</string>
  <key>StandardErrorPath</key><string>$STATE_DIR/$1.log</string>
  $3
</dict>
</plist>
PLIST
        launchctl unload "$AGENTS/$1.plist" >/dev/null 2>&1 || true
        launchctl load -w "$AGENTS/$1.plist"
    }
    agent app.ponos.run run "<key>StartInterval</key><integer>$INTERVAL</integer>" \
        && ok "app.ponos.run loaded" || warn "could not load $AGENTS/app.ponos.run.plist"
    if [ "${TR_NO_WEB:-0}" != "1" ]; then
        agent app.ponos.web serve "<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>" \
            && CONSOLE_UP=1 && ok "app.ponos.web loaded — $CONSOLE" \
            || warn "could not load $AGENTS/app.ponos.web.plist — start it by hand: ponos serve"
    fi
elif [ "$SERVICES" = background ]; then
    say "Starting the console"
    warn "no systemd session here: no timer — a ticket runs when you start it from the console, or with “ponos run”"
    if [ "${TR_NO_WEB:-0}" != "1" ]; then
        if console_up; then
            CONSOLE_UP=1
            ok "a console already answers on $CONSOLE"
        else
            mkdir -p "$STATE_DIR/web"
            nohup "$BIN" serve >>"$STATE_DIR/web/serve.log" 2>&1 </dev/null &
            # Kept for uninstall.sh: nothing else knows this process is ours.
            echo $! > "$STATE_DIR/web/serve.pid"
            CONSOLE_UP=1
            ok "started in the background — $CONSOLE (until this machine restarts: then “ponos serve”)"
        fi
    fi
else
    warn "no unit installed — run passes with “ponos run”, the console with “ponos serve”"
fi

# Started is not answering: the address is printed — and opened — once it does.
if [ "${CONSOLE_UP:-0}" = "1" ]; then
    CONSOLE_UP=0
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
        if console_up; then CONSOLE_UP=1; break; fi
        sleep 0.5
    done
    [ "$CONSOLE_UP" = 1 ] || warn "the console does not answer on $CONSOLE yet — ponos doctor says why"
fi

# --- 7. summary -------------------------------------------------------------
# The console is where the rest happens, so what is worth printing first is the
# address that opens it — and then opening it. Which address depends on what it
# is waiting for: a console nobody has claimed opens on its first connection,
# and a token would only skip the page that asks for the password. Otherwise
# the token is printed with it, since the one drawn on first start is otherwise
# readable only from a state file nobody would think to look in.
OPEN="$CONSOLE"
if [ "${CONSOLE_UP:-0}" = "1" ] && [ "$CONSOLE_CLAIMED" = "claimed" ]; then
    TOKEN=$("$BIN" serve --print-token 2>/dev/null || true)
    [ -n "$TOKEN" ] && OPEN="$CONSOLE/?token=$TOKEN"
fi

printf '\n%sPonos is installed.%s\n\n' "$BOLD" "$RESET"
if [ "${CONSOLE_UP:-0}" = "1" ]; then
    printf '  Everything else happens in the console — Notion, GitHub, a first project\n'
    printf '  and a first ticket, step by step:\n\n    %s%s%s\n\n' "$BOLD" "$OPEN" "$RESET"
    if [ "${TR_NO_OPEN:-0}" != "1" ]; then
        if [ "$OS" = Darwin ] && have open; then
            open "$OPEN" >/dev/null 2>&1 || true
        elif [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && have xdg-open; then
            xdg-open "$OPEN" >/dev/null 2>&1 &
        fi
    fi
else
    printf '  Start the console, then open %s — it walks you through the rest:\n\n    %sponos serve%s\n\n' "$CONSOLE" "$BOLD" "$RESET"
fi
printf '  %sstuck?%s         ponos doctor   %s(the same diagnosis as the console, to paste when asking for help)%s\n' "$DIM" "$RESET" "$DIM" "$RESET"
printf '  %sconfiguration%s  %s\n' "$DIM" "$RESET" "$CONFIG"
printf '  %sversion%s        kept up to date on its own — ponos update\n\n' "$DIM" "$RESET"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) RC="$HOME/.bashrc"; [ "$OS" = Darwin ] && RC="$HOME/.zshrc"
       printf '  %s!%s add %s to your PATH: echo '"'"'export PATH="$HOME/.local/bin:$PATH"'"'"' >> %s\n\n' "$YELLOW" "$RESET" "$BIN_DIR" "$RC" ;;
esac
